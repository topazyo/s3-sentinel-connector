#!/bin/bash
# scripts/diagnose_performance.sh

set -e

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )" # Absolute path to the script's directory
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")" # Project root directory, assuming script is in a 'scripts' subdirectory

# Colors for terminal output
RED='\033[0;31m'        # Red for errors
GREEN='\033[0;32m'      # Green for logs and success messages
# Defines a warning threshold for queue length.
# If average or P95 queue length exceeds this, a warning will be issued.
WARN_THRESHOLD_QUEUE_LENGTH=1000
YELLOW='\033[1;33m'     # Yellow for warnings
NC='\033[0m'            # No Color - reset to default terminal color

# Functions

# log <message>
# Prints a green log message with a timestamp and INFO prefix.
# Used for general script progress and information.
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%dT%H:%M:%S%z')] INFO: $1${NC}"
}

# warn <message>
# Prints a yellow warning message with a timestamp to stdout.
# Used for non-critical issues or potential areas of concern.
warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%dT%H:%M:%S%z')] WARNING: $1${NC}"
}

# error <message>
# Prints a red error message to stderr with a timestamp and exits the script with status 1.
# Used for fatal errors that prevent script continuation.
error() {
    echo -e "${RED}[$(date +'%Y-%m-%dT%H:%M:%S%z')] ERROR: $1${NC}" >&2
    exit 1 
}

# display_usage
# Prints the script's usage instructions, parameters, default values, and options.
# This function is called when -h or --help is used, or if incorrect parameters are provided.
display_usage() {
    echo "Diagnoses overall system and component performance using Azure Monitor metrics, checking latency, throughput, error rates, queue lengths, and resource utilization."
    echo ""
    echo "Usage: ./diagnose_performance.sh [environment] [component] [time_range]"
    echo ""
    echo "Parameters:"
    echo "  environment: Environment to check (e.g., dev, stage, prod). Corresponding env file must exist in ${SCRIPT_DIR}/env/"
    echo "  component: Specific component name or 'all' to check all components."
    echo "  time_range: Time range for data query (e.g., 1h, 24h, 7d)."
    echo "Default values:"
    echo "  ENV: prod"
    echo "  COMPONENT: all"
    echo "  TIME_RANGE: 1h"
    echo "Options:"
    echo "  -h, --help: Display this help message."
}

# Argument parsing and validation
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    display_usage
    exit 0
fi

ENV=${1:-"prod"}
COMPONENT=${2:-"all"}
TIME_RANGE=${3:-"1h"}

# Dependency checks
for cmd in az jq bc; do
    if ! command -v "$cmd" &> /dev/null; then
        error "$cmd command not found. Please install it and ensure it's in your PATH."
    fi
done

# Input validation
if [ ! -f "${SCRIPT_DIR}/env/${ENV}.env" ]; then
    error "Environment file ${SCRIPT_DIR}/env/${ENV}.env not found."
    display_usage
fi

if ! [[ "${TIME_RANGE}" =~ ^[0-9]+[hd]$ ]]; then
    error "Invalid TIME_RANGE format. Expected a number followed by 'h' or 'd' (e.g., 1h, 24h, 7d)."
    display_usage
fi

# Load environment variables
source "${SCRIPT_DIR}/env/${ENV}.env"

# Environment variable check
if [ -z "${WORKSPACE_ID}" ]; then # WORKSPACE_ID is expected to be sourced from the .env file
    error "WORKSPACE_ID environment variable is not set or empty. Please define it in ${SCRIPT_DIR}/env/${ENV}.env or export it."
fi

# success <message>
# Prints a green success message with a checkmark.
# Used to indicate positive diagnostic findings (e.g., stable trends).
success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# failure <message>
# Prints a red failure message with an X. (Currently not used, but available for future checks)
# Could be used for specific checks that "fail" but don't stop the script.
failure() {
    echo -e "${RED}✗ $1${NC}"
}

# diagnose_queue_length
# Diagnoses queue length metrics for specified components over a given time range.
# - Fetches average, maximum, and 95th percentile of 'queue_length' metric from Azure Monitor.
# - Displays the raw time-series data for queue lengths.
# - Issues warnings if average or P95 queue length exceeds WARN_THRESHOLD_QUEUE_LENGTH.
# - Analyzes and reports trends in queue length (sharply increasing, decreasing, or stable).
# Implicitly uses global variables: COMPONENT, TIME_RANGE, WORKSPACE_ID, WARN_THRESHOLD_QUEUE_LENGTH.
diagnose_queue_length() {
    log "Diagnosing queue length..."

    # Build KQL filter part for component if not 'all'.
    # This string will be injected into the KQL query.
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi

    # KQL query to get queue length metrics.
    # - MetricName: 'queue_length'
    # - Summarizes average, max, and 95th percentile.
    # - Bins data into 5-minute intervals using bin(TimeGenerated, 5m).
    # - Orders by time for trend analysis.
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'queue_length'
    ${COMPONENT_FILTER}
    | summarize 
        AvgQueueLength = avg(MetricValue),
        MaxQueueLength = max(MetricValue),
        P95QueueLength = percentile(MetricValue, 95)
        by bin(TimeGenerated, 5m), Component
    | order by TimeGenerated asc
    "
    
    # Execute Azure CLI query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    AZ_EXIT_STATUS=$? # Capture exit status of the az command

    # Standard error handling for Azure CLI call
    if [ ${AZ_EXIT_STATUS} -ne 0 ]; then
        warn "Failed to retrieve data for queue length analysis. Azure CLI exited with status ${AZ_EXIT_STATUS}."
        if [[ -n "$RESULT" ]]; then warn "Azure CLI output: $RESULT"; fi # Show az output if any
        return
    fi

    # Validate if RESULT is valid JSON
    if ! echo "$RESULT" | jq . > /dev/null 2>&1; then
        warn "No data returned or invalid JSON format for queue length analysis. Raw output: $RESULT"
        return
    fi

    echo -e "\nQueue Length Analysis (Time Range: ${TIME_RANGE}):"
    echo "---------------------------------------------"
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then # Check if result is empty or null JSON array
        echo "  No queue length data to display for this period."
    else
        # Use jq to format the output for each time bucket and component.
        # Fallback to "N/A" or 0 for potentially null fields.
        echo "${RESULT}" | jq -r '.[] | "  \(.TimeGenerated | sub("T";" ") | sub("\\..*Z";"Z")) | Component: \(.Component // "N/A") | AvgQL: \(.AvgQueueLength // 0), MaxQL: \(.MaxQueueLength // 0), P95QL: \(.P95QueueLength // 0)"'
        
        # Check for components with queue length exceeding the defined threshold.
        # jq filters for AvgQueueLength or P95QueueLength > threshold and creates a warning string.
        HIGH_QL_WARNINGS=$(echo "${RESULT}" | jq -r --argjson threshold "${WARN_THRESHOLD_QUEUE_LENGTH}" '.[] | select((.AvgQueueLength // 0) > $threshold or (.P95QueueLength // 0) > $threshold) | "  - Component \(.Component // "N/A"): High Queue Length detected. Avg: \(.AvgQueueLength // 0), P95: \(.P95QueueLength // 0) (Threshold: \($threshold))"')
        if [ -n "${HIGH_QL_WARNINGS}" ]; then
            warn "High Queue Length Detected (Avg or P95 > ${WARN_THRESHOLD_QUEUE_LENGTH}):"
            echo -e "${YELLOW}${HIGH_QL_WARNINGS}${NC}" # Print warning in yellow
        fi
    fi

    # Skip trend analysis if no data
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then
        log "Skipping queue length trend analysis due to no/empty data."
        echo "" # Add a newline for spacing
        return
    fi

    log "Analyzing queue length trends..."
    # Extract first and last average queue length records for each component to identify trends.
    # jq groups by Component, then maps to get the first and last AvgQueueLength.
    FIRST_RECORDS=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map({Component: (.[0].Component // "N/A"), FirstAvg: (.[0].AvgQueueLength // null)}) | .[] | select(.FirstAvg != null)')
    LAST_RECORDS=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map({Component: (.[0].Component // "N/A"), LastAvg: (.[-1].AvgQueueLength // null)}) | .[] | select(.LastAvg != null)')
    
    echo "  Queue Length Trends (comparing first and last 5-min avg in range):"
    COMPONENTS_FOR_TREND=$(echo "${FIRST_RECORDS}" | jq -r '.Component' | sort -u) # Get unique component names for trend analysis

    if [ -z "$COMPONENTS_FOR_TREND" ]; then
        echo "  Not enough distinct data points or components to analyze queue length trends."
    else
        all_stable_ql=1 # Flag to track if all components have stable trends
        for comp_trend_ql in ${COMPONENTS_FOR_TREND}; do
            FIRST_QL=$(echo "${FIRST_RECORDS}" | jq -r --arg comp "$comp_trend_ql" 'select(.Component == $comp) | .FirstAvg')
            LAST_QL=$(echo "${LAST_RECORDS}" | jq -r --arg comp "$comp_trend_ql" 'select(.Component == $comp) | .LastAvg')

            # Ensure values are numeric before using in bc
            if ! [[ "$FIRST_QL" =~ ^[0-9.]+$ ]] || ! [[ "$LAST_QL" =~ ^[0-9.]+$ ]]; then
                warn "  Could not determine numeric start/end queue length for trend analysis of ${comp_trend_ql}. First: '${FIRST_QL}', Last: '${LAST_QL}'"
                continue
            fi
            
            # Trend detection logic:
            # Sharply increasing: last > first * 2 AND last > threshold / 2 (to avoid noise at low absolute values)
            # Decreasing: last < first * 0.5 (and first > 0)
            if (( $(echo "${LAST_QL} > (${FIRST_QL} * 2) && ${LAST_QL} > (${WARN_THRESHOLD_QUEUE_LENGTH} / 2)" | bc -l) )); then
                warn "  Sharply Increasing queue length trend for ${comp_trend_ql}: ${FIRST_QL} -> ${LAST_QL}"
                all_stable_ql=0
            elif (( $(echo "${FIRST_QL} > 0 && ${LAST_QL} < (${FIRST_QL} * 0.5)" | bc -l) )); then
                success "  Decreasing queue length trend for ${comp_trend_ql}: ${FIRST_QL} -> ${LAST_QL}"
                all_stable_ql=0
            else
                echo "  Stable queue length trend for ${comp_trend_ql}: ${FIRST_QL} -> ${LAST_QL}"
            fi
        done
        if [ "$all_stable_ql" -eq 1 ] && [ -n "$COMPONENTS_FOR_TREND" ]; then # If all processed components were stable
             : # No summary message needed if all are stable, individual lines are enough.
        fi
    fi
    echo "" # Add a newline for spacing
}

# diagnose_processing_latency
# Diagnoses processing latency for specified components over a given time range.
# - Fetches average, max, 95th percentile, and standard deviation of 'processing_latency_seconds'.
# - Displays time-series latency data.
# - Analyzes average latency per component, identifies spikes, and checks for trends.
# Implicitly uses global variables: COMPONENT, TIME_RANGE, WORKSPACE_ID.
diagnose_processing_latency() {
    log "Diagnosing processing latency..."
    
    # Build KQL filter part for component if not 'all'.
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # KQL query for processing latency metrics.
    # - MetricName: 'processing_latency_seconds'
    # - Summarizes various latency stats (avg, max, p95, stdev).
    # - Bins data into 5-minute intervals.
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'processing_latency_seconds'
    ${COMPONENT_FILTER}
    | summarize 
        AvgLatency = avg(MetricValue),
        MaxLatency = max(MetricValue),
        P95Latency = percentile(MetricValue, 95),
        StdDevLatency = stdev(MetricValue)
        by bin(TimeGenerated, 5m), Component
    | order by TimeGenerated asc
    "
    
    # Execute Azure CLI query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    AZ_EXIT_STATUS=$? # Capture exit status

    # Standard error handling for Azure CLI call
    if [ ${AZ_EXIT_STATUS} -ne 0 ]; then
        warn "Failed to retrieve data for processing latency. Azure CLI exited with status ${AZ_EXIT_STATUS}."
        if [[ -n "$RESULT" ]]; then warn "Azure CLI output: $RESULT"; fi
        return
    fi

    if ! echo "$RESULT" | jq . > /dev/null 2>&1; then
        warn "No data returned or invalid JSON format for processing latency. Raw output: $RESULT"
        return
    fi
    
    echo -e "\nProcessing Latency (seconds, Time Range: ${TIME_RANGE}):"
    echo "----------------------------------------------------"
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then
        echo "  No processing latency data to display for this period."
    else
        # jq formats each record; sub replaces 'T' with space and removes milliseconds/timezone from TimeGenerated for readability.
        # Fallbacks (// "N/A" or // 0) handle potentially null fields in the JSON.
        echo "${RESULT}" | jq -r '.[] | "  \(.TimeGenerated | sub("T";" ") | sub("\\..*Z";"Z")) | Component: \(.Component // "N/A") | Avg: \(.AvgLatency // 0)s, Max: \(.MaxLatency // 0)s, P95: \(.P95Latency // 0)s, StdDev: \(.StdDevLatency // 0)s"'
    fi
    
    # Skip pattern analysis if no data
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then
        log "Skipping latency pattern analysis due to no/empty data."
        echo "" 
        return
    fi

    log "Analyzing latency patterns..."
    
    # Calculate average latency per component using jq.
    # group_by(.Component) groups data, then map calculates average of AvgLatency for each group.
    AVG_BY_COMPONENT=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map({Component: (.[0].Component // "N/A"), AvgLatency: (map(.AvgLatency // 0) | add / length)}) | .[] | select(.AvgLatency != null)')
    
    if [ -n "${AVG_BY_COMPONENT}" ]; then
        echo "  Average Latency by Component:"
        echo "${AVG_BY_COMPONENT}" | jq -r '"    \(.Component): \(.AvgLatency)s"'
    else
        echo "  Could not calculate average latency by component (no valid data points)."
    fi
    
    # Identify latency spikes: MaxLatency > 3 * AvgLatency.
    # jq filters records meeting this condition and formats the output.
    LATENCY_SPIKES=$(echo "${RESULT}" | jq -r '.[] | select(.MaxLatency != null and .AvgLatency != null and .AvgLatency > 0 and .MaxLatency > (.AvgLatency * 3)) | "    \(@(.TimeGenerated)[0:19])Z | \(.Component // "N/A"): Spike from \(.AvgLatency)s to \(.MaxLatency)s"')
    
    if [ -n "${LATENCY_SPIKES}" ]; then
        echo "  Latency Spikes Detected (MaxLatency > 3 * AvgLatency):"
        echo "${LATENCY_SPIKES}"
    else
        echo "  No significant latency spikes detected."
    fi
    
    log "Checking for latency trends..."
    
    # Extract first and last valid AvgLatency records for trend comparison.
    FIRST_RECORDS=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map({Component: (.[0].Component // "N/A"), FirstAvg: (.[0].AvgLatency // null)}) | .[] | select(.FirstAvg != null)')
    LAST_RECORDS=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map({Component: (.[0].Component // "N/A"), LastAvg: (.[-1].AvgLatency // null)}) | .[] | select(.LastAvg != null)')
    
    echo "  Latency Trends (comparing first and last 5-min avg in range):"
    # Get unique component names that have trend data.
    COMPONENTS_FOR_TREND=$(echo "${FIRST_RECORDS}" | jq -r '.Component' | sort -u)

    if [ -z "$COMPONENTS_FOR_TREND" ]; then
        echo "  Not enough distinct data points or components to analyze latency trends."
    else
        all_stable=1 # Flag to track if all components have stable trends.
        for component_name_trend in ${COMPONENTS_FOR_TREND}; do
            FIRST=$(echo "${FIRST_RECORDS}" | jq -r --arg comp "$component_name_trend" 'select(.Component == $comp) | .FirstAvg')
            LAST=$(echo "${LAST_RECORDS}" | jq -r --arg comp "$component_name_trend" 'select(.Component == $comp) | .LastAvg')
            
            # Ensure values are numeric before bc comparison.
            if ! [[ "$FIRST" =~ ^[0-9.]+$ ]] || ! [[ "$LAST" =~ ^[0-9.]+$ ]]; then
                warn "  Could not determine numeric start/end latency for trend analysis of component ${component_name_trend}. First: '${FIRST}', Last: '${LAST}'"
                continue
            fi
            
            # Trend logic: Increasing if last > 1.2 * first; Decreasing if first > 1.2 * last.
            if (( $(echo "${FIRST} > 0 && ${LAST} > ${FIRST} * 1.2" | bc -l) )); then
                warn "  Increasing latency trend for ${component_name_trend}: ${FIRST}s -> ${LAST}s"
                all_stable=0
            elif (( $(echo "${LAST} > 0 && ${FIRST} > ${LAST} * 1.2" | bc -l) )); then
                success "  Decreasing latency trend for ${component_name_trend}: ${FIRST}s -> ${LAST}s"
                all_stable=0
            else
                echo "  Stable latency for ${component_name_trend}: ${FIRST}s -> ${LAST}s"
            fi
        done
        if [ "$all_stable" -eq 1 ] && [ -n "$COMPONENTS_FOR_TREND" ]; then
             : # No specific message if all are stable; individual lines suffice.
        fi
    fi
    echo "" 
}

# diagnose_throughput
# Diagnoses event processing throughput for specified components.
# - Fetches 'logs_processed_count' (renamed to 'events processed' in output for generic term).
# - Displays time-series throughput data (total and avg/min).
# - Analyzes average throughput per component, identifies significant drops, and checks for trends.
# Implicitly uses global variables: COMPONENT, TIME_RANGE, WORKSPACE_ID.
diagnose_throughput() {
    log "Diagnosing throughput..."
    
    # Build KQL filter part for component if not 'all'.
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # KQL query for throughput metrics ('logs_processed_count').
    # - Summarizes total and average logs processed per 5-minute interval.
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'logs_processed_count' # Using 'logs_processed_count' as a proxy for throughput
    ${COMPONENT_FILTER}
    | summarize 
        TotalLogs = sum(MetricValue),        # Total events in the 5-min bin
        AvgLogsPerMin = avg(MetricValue)     # Average events per minute (if MetricValue is per-minute)
                                             # Note: If MetricValue is total per 5-min, AvgLogsPerMin would be TotalLogs/5.
                                             # Assuming MetricValue itself is a rate or can be averaged meaningfully here.
        by bin(TimeGenerated, 5m), Component
    | order by TimeGenerated asc
    "
    
    # Execute Azure CLI query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    AZ_EXIT_STATUS=$? # Capture exit status

    # Standard error handling
    if [ ${AZ_EXIT_STATUS} -ne 0 ]; then
        warn "Failed to retrieve data for throughput analysis. Azure CLI exited with status ${AZ_EXIT_STATUS}."
        if [[ -n "$RESULT" ]]; then warn "Azure CLI output: $RESULT"; fi
        return
    fi

    if ! echo "$RESULT" | jq . > /dev/null 2>&1; then
        warn "No data returned or invalid JSON format for throughput analysis. Raw output: $RESULT"
        return
    fi
    
    echo -e "\nThroughput (events processed, Time Range: ${TIME_RANGE}):" 
    echo "-------------------------------------------------------"
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then
        echo "  No throughput data to display for this period."
    else
        # jq formats each record. TotalLogs is converted to human-readable using numfmt (via placeholder).
        echo "${RESULT}" | jq -r '.[] | "  \(.TimeGenerated | sub("T";" ") | sub("\\..*Z";"Z")) | Component: \(.Component // "N/A") | Total: \(.TotalLogs // 0 | tonumber | আয় numfmt --to=si 2>/dev/null // tostring) events | Avg/min: \(.AvgLogsPerMin // 0) events/min"' | sed 's/आय/`/; s/` /`/'
    fi

    # Skip pattern analysis if no data
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then
        log "Skipping throughput pattern analysis due to no/empty data."
        echo ""
        return
    fi

    log "Analyzing throughput patterns..."
    
    # Calculate average throughput per component.
    AVG_BY_COMPONENT=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map({Component: (.[0].Component // "N/A"), AvgThroughput: (map(.AvgLogsPerMin // 0) | add / length)}) | .[] | select(.AvgThroughput != null)')
    
    if [ -n "${AVG_BY_COMPONENT}" ]; then
        echo "  Average Throughput by Component (events/min):"
        echo "${AVG_BY_COMPONENT}" | jq -r '"    \(.Component): \(.AvgThroughput)"'
    else
        echo "  Could not calculate average throughput by component."
    fi
    
    # Identify significant throughput drops (current interval < 50% of previous).
    # jq groups by component, sorts by time, then iterates through items to compare with previous.
    THROUGHPUT_DROPS=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map(sort_by(.TimeGenerated)) | .[] | . as $items | range(1; length) as $i | select($items[$i].AvgLogsPerMin != null and $items[$i-1].AvgLogsPerMin != null and $items[$i-1].AvgLogsPerMin > 0 and $items[$i].AvgLogsPerMin < $items[$i-1].AvgLogsPerMin * 0.5) | "    \($items[$i].TimeGenerated | sub("T";" ") | sub("\\..*Z";"Z")) | \($items[$i].Component // "N/A"): Drop from \($items[$i-1].AvgLogsPerMin) to \($items[$i].AvgLogsPerMin) events/min"')
    
    if [ -n "${THROUGHPUT_DROPS}" ]; then
        echo "  Throughput Drops Detected (events/min dropped by >50% between intervals):"
        echo "${THROUGHPUT_DROPS}"
    else
        echo "  No significant throughput drops detected."
    fi
    
    log "Checking for throughput trends..."
    
    # Extract first and last valid AvgLogsPerMin records for trend comparison.
    FIRST_RECORDS=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map({Component: (.[0].Component // "N/A"), FirstAvg: (.[0].AvgLogsPerMin // null)}) | .[] | select(.FirstAvg != null)')
    LAST_RECORDS=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map({Component: (.[0].Component // "N/A"), LastAvg: (.[-1].AvgLogsPerMin // null)}) | .[] | select(.LastAvg != null)')
    
    echo "  Throughput Trends (comparing first and last 5-min avg in range):"
    COMPONENTS_FOR_TREND=$(echo "${FIRST_RECORDS}" | jq -r '.Component' | sort -u) # Unique components for trend.

    if [ -z "$COMPONENTS_FOR_TREND" ]; then
        echo "  Not enough distinct data points or components to analyze throughput trends."
    else
        all_stable=1 # Flag for overall trend stability.
        for component_name_trend in ${COMPONENTS_FOR_TREND}; do 
            FIRST=$(echo "${FIRST_RECORDS}" | jq -r --arg comp "$component_name_trend" 'select(.Component == $comp) | .FirstAvg')
            LAST=$(echo "${LAST_RECORDS}" | jq -r --arg comp "$component_name_trend" 'select(.Component == $comp) | .LastAvg')

            # Ensure values are numeric before bc comparison.
            if ! [[ "$FIRST" =~ ^[0-9.]+$ ]] || ! [[ "$LAST" =~ ^[0-9.]+$ ]]; then
                warn "  Could not determine numeric start/end throughput for trend analysis of component ${component_name_trend}. First: '${FIRST}', Last: '${LAST}'"
                continue
            fi

            # Trend logic: Increasing if last > 1.2 * first; Decreasing if last < 0.8 * first.
            if (( $(echo "${FIRST} > 0 && ${LAST} > ${FIRST} * 1.2" | bc -l) )); then
                success "  Increasing throughput trend for ${component_name_trend}: ${FIRST} -> ${LAST} events/min" # Changed logs/min to events/min
                all_stable=0
            elif (( $(echo "${LAST} >= 0 && ${FIRST} > 0 && ${LAST} < ${FIRST} * 0.8" | bc -l) )); then # Allow LAST to be 0.
                warn "  Decreasing throughput trend for ${component_name_trend}: ${FIRST} -> ${LAST} events/min" # Changed logs/min to events/min
                all_stable=0
            else
                echo "  Stable throughput for ${component_name_trend}: ${FIRST} -> ${LAST} events/min" # Changed logs/min to events/min
            fi
        done
         if [ "$all_stable" -eq 1 ] && [ -n "$COMPONENTS_FOR_TREND" ]; then
             : # No summary message if all stable.
        fi
    fi
    echo "" # Add a newline for spacing.
}

# diagnose_error_rates
# Diagnoses error rates for components by comparing 'error_count' to 'logs_processed_count'.
# - Displays time-series error rate data.
# - Analyzes average error rates, identifies spikes, and lists top error types from LogEvents.
# Implicitly uses global variables: COMPONENT, TIME_RANGE, WORKSPACE_ID.
diagnose_error_rates() {
    log "Diagnosing error rates..."
    
    # Build KQL filter part for component if not 'all'.
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # KQL query for error rates.
    # - Fetches 'error_count' and 'logs_processed_count' metrics.
    # - Summarizes these counts over 5-minute intervals.
    # - Calculates ErrorRate = ErrorCount / ProcessedCount, handling potential division by zero.
    # - Projects relevant columns for output.
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName in ('error_count', 'logs_processed_count')
    ${COMPONENT_FILTER}
    | summarize 
        ErrorCount = sumif(MetricValue, MetricName == 'error_count'),
        ProcessedCount = sumif(MetricValue, MetricName == 'logs_processed_count')
        by bin(TimeGenerated, 5m), Component
    | extend 
        ErrorRate = iff(ProcessedCount > 0, todouble(ErrorCount) / ProcessedCount, 0.0) # Ensure floating point for rate
    | project
        TimeGenerated,
        Component,
        ErrorCount,
        ProcessedCount,
        ErrorRate
    | order by TimeGenerated asc
    "
    
    # Execute Azure CLI query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    AZ_EXIT_STATUS=$? # Capture exit status

    # Standard error handling
    if [ ${AZ_EXIT_STATUS} -ne 0 ]; then
        warn "Failed to retrieve data for error rate analysis. Azure CLI exited with status ${AZ_EXIT_STATUS}."
        if [[ -n "$RESULT" ]]; then warn "Azure CLI output: $RESULT"; fi
        return
    fi

    if ! echo "$RESULT" | jq . > /dev/null 2>&1; then
        warn "No data returned or invalid JSON format for error rate analysis. Raw output: $RESULT"
        return
    fi
    
    echo -e "\nError Rates (Time Range: ${TIME_RANGE}):"
    echo "-----------------------------------"
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then
        echo "  No error rate data to display for this period."
    else
        # jq formats each record. ErrorCount and ProcessedCount use numfmt via placeholder.
        echo "${RESULT}" | jq -r '.[] | "  \(.TimeGenerated | sub("T";" ") | sub("\\..*Z";"Z")) | Component: \(.Component // "N/A") | Errors: \(.ErrorCount // 0 | tonumber | আয় numfmt --to=si 2>/dev/null // tostring) | Processed: \(.ProcessedCount // 0 | tonumber | আয় numfmt --to=si 2>/dev/null // tostring) | Rate: \(.ErrorRate // 0)"' | sed 's/आय/`/; s/` /`/'
    fi

    # Skip pattern analysis if no data
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then
        log "Skipping error pattern analysis due to no/empty data."
    else
        log "Analyzing error patterns..."
        
        # Calculate average error rate per component.
        AVG_BY_COMPONENT=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map({Component: (.[0].Component // "N/A"), AvgErrorRate: (map(.ErrorRate // 0) | add / length)}) | .[] | select(.AvgErrorRate != null)')
        
        if [ -n "${AVG_BY_COMPONENT}" ]; then
            echo "  Average Error Rate by Component:"
            echo "${AVG_BY_COMPONENT}" | jq -r '"    \(.Component): \(.AvgErrorRate * 100)%"'
        else
            echo "  Could not calculate average error rates by component."
        fi
        
        # Identify error spikes (ErrorRate > 10%).
        ERROR_SPIKES=$(echo "${RESULT}" | jq -r '.[] | select(.ErrorRate != null and .ErrorRate > 0.1) | "    \(@(.TimeGenerated)[0:19])Z | \(.Component // "N/A"): Error rate \(.ErrorRate * 100)%"')
        
        if [ -n "${ERROR_SPIKES}" ]; then
            echo "  Error Spikes Detected (Rate > 10%):"
            echo "${ERROR_SPIKES}"
        else
            echo "  No significant error spikes detected."
        fi
    fi
    
    # Get error details from LogEvents table
    log "Getting error details..."
    
    # KQL query for top error types from LogEvents.
    # - Filters for Level == 'Error'.
    # - Summarizes count by ErrorType and Component.
    # - Orders by count descending and limits to top 10.
    ERROR_DETAILS_QUERY="
    let timeRange = ${TIME_RANGE};
    LogEvents
    | where TimeGenerated > ago(timeRange)
    | where Level == 'Error'
    ${COMPONENT_FILTER}
    | summarize 
        ErrorCount = count()
        by ErrorType, Component
    | order by ErrorCount desc
    | limit 10
    "
    
    # Execute Azure CLI query for error details
    ERROR_DETAILS_RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${ERROR_DETAILS_QUERY}" \
        --output json)
    AZ_EXIT_STATUS_DETAILS=$? # Capture exit status

    # Standard error handling for this second query
    if [ ${AZ_EXIT_STATUS_DETAILS} -ne 0 ]; then
        warn "Failed to retrieve error details. Azure CLI exited with status ${AZ_EXIT_STATUS_DETAILS}."
        if [[ -n "$ERROR_DETAILS_RESULT" ]]; then warn "Azure CLI output: $ERROR_DETAILS_RESULT"; fi
    elif ! echo "$ERROR_DETAILS_RESULT" | jq . > /dev/null 2>&1; then
        warn "No data returned or invalid JSON format for error details. Raw output: $ERROR_DETAILS_RESULT"
    elif [[ -z "$ERROR_DETAILS_RESULT" || "$ERROR_DETAILS_RESULT" == "null" || "$ERROR_DETAILS_RESULT" == "[]" ]]; then
        echo "  No specific error type details found in LogEvents for this period."
    else
        echo "  Top Error Types from LogEvents (limit 10):"
        # jq formats each error type. ErrorCount uses numfmt via placeholder.
        echo "${ERROR_DETAILS_RESULT}" | jq -r '.[] | "    Component: \(.Component // "N/A") | Type: \(.ErrorType // "N/A") | Count: \(.ErrorCount // 0 | tonumber | আয় numfmt --to=si 2>/dev/null // tostring)"' | sed 's/आय/`/; s/` /`/'
    fi
    echo "" # Add a newline for spacing.
}

# diagnose_resource_utilization
# Diagnoses CPU, memory, and disk I/O utilization for components.
# - Fetches time-series data for 'cpu_percent', 'memory_percent', 'disk_io_percent'.
# - Displays raw utilization metrics.
# - Analyzes average utilization per component and identifies potential constraints based on thresholds.
# Implicitly uses global variables: COMPONENT, TIME_RANGE, WORKSPACE_ID.
diagnose_resource_utilization() {
    log "Diagnosing resource utilization..."
    
    # Build KQL filter part for component if not 'all'.
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # KQL query for resource utilization metrics.
    # - Fetches 'cpu_percent', 'memory_percent', 'disk_io_percent'.
    # - Summarizes avg, max, and p95 values for specified metrics.
    # - Bins data into 5-minute intervals.
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName in ('cpu_percent', 'memory_percent', 'disk_io_percent')
    ${COMPONENT_FILTER}
    | summarize 
        AvgValue = avg(MetricValue),
        MaxValue = max(MetricValue),
        P95Value = percentile(MetricValue, 95)
        by bin(TimeGenerated, 5m), MetricName, Component
    | order by TimeGenerated asc, Component asc, MetricName asc
    "
    
    # Execute Azure CLI query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    AZ_EXIT_STATUS=$? # Capture exit status

    # Standard error handling
    if [ ${AZ_EXIT_STATUS} -ne 0 ]; then
        warn "Failed to retrieve data for resource utilization analysis. Azure CLI exited with status ${AZ_EXIT_STATUS}."
        if [[ -n "$RESULT" ]]; then warn "Azure CLI output: $RESULT"; fi
        return
    fi

    if ! echo "$RESULT" | jq . > /dev/null 2>&1; then
        warn "No data returned or invalid JSON format for resource utilization analysis. Raw output: $RESULT"
        return
    fi
    
    echo -e "\nResource Utilization (Time Range: ${TIME_RANGE}):"
    echo "--------------------------------------------"
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then
        echo "  No resource utilization data to display for this period."
    else
        # jq formats each record.
        echo "${RESULT}" | jq -r '.[] | "  \(.TimeGenerated | sub("T";" ") | sub("\\..*Z";"Z")) | Component: \(.Component // "N/A") | Metric: \(.MetricName // "N/A") | Avg: \(.AvgValue // 0)%, Max: \(.MaxValue // 0)%, P95: \(.P95Value // 0)%"'
    fi

    # Skip constraint analysis if no data
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then
        log "Skipping resource constraint analysis due to no/empty data."
        echo ""
        return
    fi
    
    log "Analyzing resource constraints..."
    
    # Calculate average utilization per component and metric.
    AVG_BY_COMPONENT=$(echo "${RESULT}" | jq -r 'group_by(.Component, .MetricName) | map({Component: (.[0].Component // "N/A"), MetricName: (.[0].MetricName // "N/A"), AvgValue: (map(.AvgValue // 0) | add / length), MaxValue: (map(.MaxValue // 0) | max)}) | .[] | select(.AvgValue != null)')
    
    if [ -n "${AVG_BY_COMPONENT}" ]; then
        echo "  Average Resource Utilization by Component:"
        echo "${AVG_BY_COMPONENT}" | jq -r '"    \(.Component) | \(.MetricName): Avg: \(.AvgValue)%, Max: \(.MaxValue)%"'
    else
        echo "  Could not calculate average resource utilization by component."
    fi
    
    # Identify specific resource constraints based on thresholds.
    CPU_CONSTRAINTS=$(echo "${AVG_BY_COMPONENT}" | jq -r 'select(.MetricName == "cpu_percent" and .AvgValue > 70) | "    - \(.Component): \(.AvgValue)% average CPU usage"')
    MEMORY_CONSTRAINTS=$(echo "${AVG_BY_COMPONENT}" | jq -r 'select(.MetricName == "memory_percent" and .AvgValue > 80) | "    - \(.Component): \(.AvgValue)% average memory usage"')
    DISK_CONSTRAINTS=$(echo "${AVG_BY_COMPONENT}" | jq -r 'select(.MetricName == "disk_io_percent" and .AvgValue > 60) | "    - \(.Component): \(.AvgValue)% average disk I/O usage"')
    
    echo "  Identified Resource Constraints:"
    constraint_found=0 # Flag to track if any constraint is found
    if [ -n "${CPU_CONSTRAINTS}" ]; then
        echo "  High CPU Usage (Avg > 70%):"
        echo "${CPU_CONSTRAINTS}"
        constraint_found=1
    fi
    
    if [ -n "${MEMORY_CONSTRAINTS}" ]; then
        echo "  High Memory Usage (Avg > 80%):"
        echo "${MEMORY_CONSTRAINTS}"
        constraint_found=1
    fi
    
    if [ -n "${DISK_CONSTRAINTS}" ]; then
        echo "  High Disk I/O Usage (Avg > 60%):"
        echo "${DISK_CONSTRAINTS}"
        constraint_found=1
    fi
    
    if [ ${constraint_found} -eq 0 ]; then
        echo "    No significant resource constraints detected (CPU Avg <= 70%, Memory Avg <= 80%, Disk I/O Avg <= 60%)."
    fi
    echo "" # Add a newline for spacing.
}

# generate_recommendations
# Generates performance optimization recommendations based on the analyzed metrics from previous functions.
# This function re-queries summarized data for some metrics to ensure recommendations are based on consistent views.
# Implicitly uses global variables: COMPONENT, TIME_RANGE, WORKSPACE_ID, WARN_THRESHOLD_QUEUE_LENGTH, ENV.
# Also uses `component_issues_summary` associative array to build a holistic summary.
generate_recommendations() {
    log "Generating performance recommendations..."
    
    echo -e "\nPerformance Recommendations:"
    echo "--------------------------------"
    
    # Associative array to store issues found per component for a holistic summary at the end.
    declare -A component_issues_summary 

    # Recommendation 1: High CPU Usage
    # KQL query for components with average CPU usage > 70%.
    CPU_QUERY=" # Renamed to avoid conflict with other QUERY variables in the script.
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'cpu_percent'
    | summarize AvgCPU = avg(MetricValue) by Component
    | where AvgCPU > 70 # Threshold for high CPU
    "
    
    CPU_RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${CPU_QUERY}" \
        --output json)
    AZ_EXIT_STATUS_CPU=$?

    echo "1. High CPU Usage (Average > 70%):"
    if [ ${AZ_EXIT_STATUS_CPU} -ne 0 ]; then
        warn "  Rec: Failed to get CPU data. CLI Error ${AZ_EXIT_STATUS_CPU}. Output: ${CPU_RESULT}"
    elif ! echo "$CPU_RESULT" | jq . > /dev/null 2>&1; then
        warn "  Rec: Invalid JSON for CPU data. Output: ${CPU_RESULT}"
    elif [[ -n "$CPU_RESULT" && "$CPU_RESULT" != "null" && "$CPU_RESULT" != "[]" ]] && [ "$(echo "$CPU_RESULT" | jq 'length')" -gt 0 ]; then
        echo "${CPU_RESULT}" | jq -r '.[] | 
            "   - Component: \(.Component // "N/A")\n" +
            "     Reason: Average CPU usage is \(.AvgCPU // 0)%.\n" +
            "     Action: If this correlates with high latency or error rates for \(.Component // "N/A"), consider scaling CPU resources or optimizing CPU-intensive operations." '
        # Populate summary array
        while IFS= read -r comp_name; do component_issues_summary["$comp_name,cpu"]="High CPU" ; done < <(echo "$CPU_RESULT" | jq -r '.[].Component // "N/A"')
    else
        echo "  No components found with average CPU usage > 70%."
    fi
    echo "" 
    
    # Recommendation 2: High Memory Usage
    # KQL query for components with average memory usage > 80%.
    MEMORY_QUERY=" # Renamed.
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'memory_percent'
    | summarize AvgMemory = avg(MetricValue) by Component
    | where AvgMemory > 80 # Using 80% to align with resource utilization diagnostic
    "
    
    MEMORY_RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${MEMORY_QUERY}" \
        --output json)
    AZ_EXIT_STATUS_MEM=$?

    echo "2. High Memory Usage (Average > 80%):"
    if [ ${AZ_EXIT_STATUS_MEM} -ne 0 ]; then
        warn "  Rec: Failed to get Memory data. CLI Error ${AZ_EXIT_STATUS_MEM}. Output: ${MEMORY_RESULT}"
    elif ! echo "$MEMORY_RESULT" | jq . > /dev/null 2>&1; then
        warn "  Rec: Invalid JSON for Memory data. Output: ${MEMORY_RESULT}"
    elif [[ -n "$MEMORY_RESULT" && "$MEMORY_RESULT" != "null" && "$MEMORY_RESULT" != "[]" ]] && [ "$(echo "$MEMORY_RESULT" | jq 'length')" -gt 0 ]; then
        echo "${MEMORY_RESULT}" | jq -r '.[] | 
            "   - Component: \(.Component // "N/A")\n" +
            "     Reason: Average memory usage is \(.AvgMemory // 0)%.\n" +
            "     Action: Investigate for memory leaks (e.g., using `./scripts/analyze_memory.sh '${ENV}' '\(.Component // "N/A")' '${TIME_RANGE}'`). If no leaks, consider increasing allocation or optimizing memory footprint." '
        while IFS= read -r comp_name; do component_issues_summary["$comp_name,memory"]="High Memory" ; done < <(echo "$MEMORY_RESULT" | jq -r '.[].Component // "N/A"')
    else
        echo "  No components found with average Memory usage > 80%."
    fi
    echo ""
    
    # Recommendation 3: High Processing Latency
    # KQL query for components with average processing latency > 30 seconds.
    LATENCY_QUERY=" # Renamed.
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'processing_latency_seconds'
    | summarize AvgLatency = avg(MetricValue) by Component
    | where AvgLatency > 30 # Threshold for high latency
    "
    
    LATENCY_RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${LATENCY_QUERY}" \
        --output json)
    AZ_EXIT_STATUS_LATENCY=$?
    
    echo "3. High Processing Latency (Average > 30s):"
    if [ ${AZ_EXIT_STATUS_LATENCY} -ne 0 ]; then
        warn "  Rec: Failed to get Latency data. CLI Error ${AZ_EXIT_STATUS_LATENCY}. Output: ${LATENCY_RESULT}"
    elif ! echo "$LATENCY_RESULT" | jq . > /dev/null 2>&1; then
        warn "  Rec: Invalid JSON for Latency data. Output: ${LATENCY_RESULT}"
    elif [[ -n "$LATENCY_RESULT" && "$LATENCY_RESULT" != "null" && "$LATENCY_RESULT" != "[]" ]] && [ "$(echo "$LATENCY_RESULT" | jq 'length')" -gt 0 ]; then
        echo "${LATENCY_RESULT}" | jq -r '.[] | 
            "   - Component: \(.Component // "N/A")\n" +
            "     Reason: Average processing latency is \(.AvgLatency // 0)s.\n" +
            "     Action: Profile \(.Component // "N/A") to identify bottlenecks. Check its resource utilization, error logs (see '\''Top Error Types'\'' under Error Rates section), and dependencies." '
        while IFS= read -r comp_name; do component_issues_summary["$comp_name,latency"]="High Latency" ; done < <(echo "$LATENCY_RESULT" | jq -r '.[].Component // "N/A"')
    else
        echo "  No components found with average processing latency > 30s."
    fi
    echo ""
    
    # Recommendation 4: Batch Size Optimization
    # KQL query to find optimal batch size based on 'batch_processing_rate'.
    BATCH_QUERY=" # Renamed.
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'batch_processing_rate'
    | summarize AvgRate = avg(MetricValue) by Component, BatchSize
    | order by Component asc, AvgRate desc
    "
    
    BATCH_RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${BATCH_QUERY}" \
        --output json)
    AZ_EXIT_STATUS_BATCH=$?

    echo "4. Batch Size Optimization:"
    if [ ${AZ_EXIT_STATUS_BATCH} -ne 0 ]; then
        warn "  Rec: Failed to get Batch Size data. CLI Error ${AZ_EXIT_STATUS_BATCH}. Output: ${BATCH_RESULT}"
    elif ! echo "$BATCH_RESULT" | jq . > /dev/null 2>&1; then
        warn "  Rec: Invalid JSON for Batch Size data. Output: ${BATCH_RESULT}"
    elif [[ -n "$BATCH_RESULT" && "$BATCH_RESULT" != "null" && "$BATCH_RESULT" != "[]" ]] && [ "$(echo "$BATCH_RESULT" | jq 'length')" -gt 0 ]; then
        # This jq command finds the batch size with the maximum average rate for each component.
        echo "${BATCH_RESULT}" | jq -r 'group_by(.Component) | map({Component: (.[0].Component // "N/A"), OptimalBatch: max_by(.AvgRate) | {BatchSize: (.BatchSize // "N/A"), MaxRate: (.AvgRate // 0)}}) | .[] |
            "   - Component: \(.Component)\n" +
            "     Reason: Observed varying processing rates; an optimal batch size can improve throughput.\n" +
            "     Action: Based on observed metrics, a batch size around \(.OptimalBatch.BatchSize) for \(.Component) achieved the max observed processing rate of \(.OptimalBatch.MaxRate) items/sec. Review current configuration if significantly different." '
    else
        echo "  No data available for batch size optimization recommendations."
    fi
    echo ""
    
    # Recommendation 5: High Error Rates
    # KQL query for components with error rate > 1%.
    ERROR_QUERY=" # Renamed.
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName in ('error_count', 'logs_processed_count')
    | summarize 
        ErrorCount = sumif(MetricValue, MetricName == 'error_count'),
        ProcessedCount = sumif(MetricValue, MetricName == 'logs_processed_count')
        by Component
    | extend 
        ErrorRate = iff(ProcessedCount > 0, todouble(ErrorCount) / ProcessedCount, 0.0) # Ensure floating point division for ErrorRate
    | where ErrorRate > 0.01 # Threshold for high error rate (1%)
    "
    
    ERROR_RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${ERROR_QUERY}" \
        --output json)
    AZ_EXIT_STATUS_ERROR=$?
    
    echo "5. High Error Rates (Rate > 1%):"
    if [ ${AZ_EXIT_STATUS_ERROR} -ne 0 ]; then
        warn "  Rec: Failed to get Error Rate data. CLI Error ${AZ_EXIT_STATUS_ERROR}. Output: ${ERROR_RESULT}"
    elif ! echo "$ERROR_RESULT" | jq . > /dev/null 2>&1; then
        warn "  Rec: Invalid JSON for Error Rate data. Output: ${ERROR_RESULT}"
    elif [[ -n "$ERROR_RESULT" && "$ERROR_RESULT" != "null" && "$ERROR_RESULT" != "[]" ]] && [ "$(echo "$ERROR_RESULT" | jq 'length')" -gt 0 ]; then
        echo "${ERROR_RESULT}" | jq -r '.[] | 
            "   - Component: \(.Component // "N/A")\n" +
            "     Reason: Error rate is \(.ErrorRate * 100)% (\(.ErrorCount // 0) errors / \(.ProcessedCount // 0) processed).\n" +
            "     Action: Prioritize investigating the '\''Top Error Types'\'' reported for \(.Component // "N/A") in the '\''Error Rates'\'' diagnostic section." '
        while IFS= read -r comp_name; do component_issues_summary["$comp_name,errors"]="High Errors" ; done < <(echo "$ERROR_RESULT" | jq -r '.[].Component // "N/A"')
    else
        echo "  No components found with error rates > 1%."
    fi
    echo "" 

    # Recommendation 6: High Queue Length
    # KQL query for components with P95 or Average Queue Length > WARN_THRESHOLD_QUEUE_LENGTH.
    QL_QUERY=" # Renamed.
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'queue_length'
    ${COMPONENT_FILTER} # Reuses the global COMPONENT_FILTER for component scoping
    | summarize AvgQL = avg(MetricValue), MaxQL = max(MetricValue), P95QL = percentile(MetricValue, 95) by Component
    | where P95QL > ${WARN_THRESHOLD_QUEUE_LENGTH} or AvgQL > ${WARN_THRESHOLD_QUEUE_LENGTH} 
    "
    QL_RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QL_QUERY}" \
        --output json)
    AZ_EXIT_STATUS_QL=$?

    echo "6. High Queue Length (P95 or Avg > ${WARN_THRESHOLD_QUEUE_LENGTH}):"
    if [ ${AZ_EXIT_STATUS_QL} -ne 0 ]; then
        warn "  Rec: Failed to get Queue Length data. CLI Error ${AZ_EXIT_STATUS_QL}. Output: ${QL_RESULT}"
    elif ! echo "$QL_RESULT" | jq . > /dev/null 2>&1; then
        warn "  Rec: Invalid JSON for Queue Length data. Output: ${QL_RESULT}"
    elif [[ -n "$QL_RESULT" && "$QL_RESULT" != "null" && "$QL_RESULT" != "[]" ]] && [ "$(echo "$QL_RESULT" | jq 'length')" -gt 0 ]; then
        echo "${QL_RESULT}" | jq -r '.[] |
            "   - Component: \(.Component // "N/A")\n" +
            "     Reason: High queue length detected. Avg: \(.AvgQL // 0), Max: \(.MaxQL // 0), P95: \(.P95QL // 0).\n" +
            "     Action: Investigate consumers of queues for \(.Component // "N/A") for bottlenecks (they may not be processing items fast enough). Also check producers if enqueue rate is unexpectedly high. Consider scaling consumers or optimizing processing logic." '
        while IFS= read -r comp_name; do component_issues_summary["$comp_name,queue"]="High QueueLength" ; done < <(echo "$QL_RESULT" | jq -r '.[].Component // "N/A"')
    else
        echo "  No components found with P95 or Average Queue Length > ${WARN_THRESHOLD_QUEUE_LENGTH}."
    fi
    echo ""

    # Holistic Summary: Provides a per-component summary of all identified potential issues.
    echo -e "\nOverall Potential Bottleneck Summary:"
    echo "-------------------------------------"
    summary_found=0
    # Iterate through unique components that had any issue flagged.
    components_with_issues=$(for key in "${!component_issues_summary[@]}"; do echo "${key%,*}" ; done | sort -u)

    if [ -z "$components_with_issues" ]; then
        echo "  No specific performance bottlenecks identified across multiple categories for any single component based on current thresholds."
    else
        for comp in $components_with_issues; do
            issues_list="" # String to accumulate issues for the current component.
            # Check for each type of issue and append to issues_list.
            [ -n "${component_issues_summary[$comp,cpu]}" ] && issues_list+="${component_issues_summary[$comp,cpu]}; "
            [ -n "${component_issues_summary[$comp,memory]}" ] && issues_list+="${component_issues_summary[$comp,memory]}; "
            [ -n "${component_issues_summary[$comp,latency]}" ] && issues_list+="${component_issues_summary[$comp,latency]}; "
            [ -n "${component_issues_summary[$comp,errors]}" ] && issues_list+="${component_issues_summary[$comp,errors]}; "
            [ -n "${component_issues_summary[$comp,queue]}" ] && issues_list+="${component_issues_summary[$comp,queue]}; "
            
            if [ -n "$issues_list" ]; then
                issues_list=${issues_list%; } # Remove trailing semicolon and space.
                echo "  - Component ${comp}: Potential issues related to - ${issues_list}."
                summary_found=1
            fi
        done
        # This check should ideally not be needed if components_with_issues is properly populated.
        if [ $summary_found -eq 0 ]; then 
            echo "  No specific performance bottlenecks identified across multiple categories for any single component based on current thresholds."
        fi
    fi
    echo "" # Add a newline for spacing.
}

# main
# Main function to orchestrate the script's operations:
# 1. Logs start of analysis, including environment, component, and time range.
# 2. Calls functions to analyze various performance aspects.
# 3. Calls function to generate recommendations based on the analysis.
# 4. Logs completion of analysis.
# Implicitly uses global variables: ENV, COMPONENT, TIME_RANGE (for logging).
main() {
    log "Starting performance diagnostics for environment: ${ENV}, component: ${COMPONENT}, time range: ${TIME_RANGE}"
    
    diagnose_processing_latency
    diagnose_throughput
    diagnose_queue_length 
    diagnose_error_rates
    diagnose_resource_utilization
    generate_recommendations # This function re-queries data, which is acceptable for its summarization purpose.
    
    log "Performance diagnostics completed for environment: ${ENV}"
}

# Execute main function
main