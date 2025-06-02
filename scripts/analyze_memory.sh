#!/bin/bash
# scripts/analyze_memory.sh

set -e

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )" # Absolute path to the script's directory
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")" # Project root directory, assuming script is in 'scripts' subdirectory

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Functions

# log <message>
# Prints a green log message with a timestamp.
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%dT%H:%M:%S%z')] $1${NC}"
}

# warn <message>
# Prints a yellow warning message with a timestamp to stdout.
warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%dT%H:%M:%S%z')] WARNING: $1${NC}"
}

# error <message>
# Prints a red error message to stderr with a timestamp and exits the script with status 1.
error() {
    echo -e "${RED}[$(date +'%Y-%m-%dT%H:%M:%S%z')] ERROR: $1${NC}" >&2
    exit 1 
}

# display_usage
# Prints the script's usage instructions, parameters, default values, and options.
display_usage() {
    echo "Analyzes memory usage, allocation, leaks, and GC behavior using Azure Monitor data."
    echo "Usage: ./analyze_memory.sh [environment] [component] [time_range]"
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
for cmd in az jq bc numfmt; do # Added numfmt
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

# analyze_memory_usage
# Queries and displays overall memory usage percentage (Avg, Max, P95, StdDev) and stability
# for components based on Azure Monitor logs.
# Implicitly uses global variables: COMPONENT, TIME_RANGE, WORKSPACE_ID.
analyze_memory_usage() {
    log "Analyzing memory usage..."
    
    # Build KQL filter part for component if not 'all'.
    # This string will be injected into the KQL query.
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # KQL query to get 'memory_percent' metrics.
    # - Summarizes average, max, 95th percentile, and standard deviation of memory usage.
    # - Extends with a 'MemoryStability' category based on standard deviation.
    #   StdDev < 5: Stable
    #   StdDev < 15: Moderate
    #   StdDev >= 15: Volatile
    # - Orders by average memory usage descending.
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'memory_percent'
    ${COMPONENT_FILTER}
    | summarize 
        AvgMemory = avg(MetricValue),
        MaxMemory = max(MetricValue),
        P95Memory = percentile(MetricValue, 95),
        StdDevMemory = stdev(MetricValue)
        by Component
    | extend 
        MemoryStability = iff(StdDevMemory < 5, 'Stable', iff(StdDevMemory < 15, 'Moderate', 'Volatile'))
    | order by AvgMemory desc
    "
    
    # Execute Azure CLI query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    AZ_EXIT_STATUS=$? # Capture exit status of the az command

    # Check for az command execution failure
    if [ ${AZ_EXIT_STATUS} -ne 0 ]; then
        warn "Failed to retrieve data for memory usage analysis. Azure CLI exited with status ${AZ_EXIT_STATUS}."
        if [[ -n "$RESULT" ]]; then warn "Azure CLI output: $RESULT"; fi # Show az output if any
        return
    fi

    # Validate if RESULT is valid JSON
    if ! echo "$RESULT" | jq . > /dev/null 2>&1; then
        warn "No data returned or invalid JSON format for memory usage analysis. Raw output: $RESULT"
        return
    fi
    
    # Parse and display results
    echo -e "\nMemory Usage Analysis (Time Range: ${TIME_RANGE}):"
    echo "---------------------------------------------"
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then # Check if result is empty or null JSON array
        echo "No data to display for memory usage analysis."
    else
        # Use jq to format the output for each component
        echo "${RESULT}" | jq -r '.[] | "Component: \(.Component) | Avg: \(.AvgMemory)%, Max: \(.MaxMemory)%, P95: \(.P95Memory)%, StdDev: \(.StdDevMemory)% (\(.MemoryStability))"'
        
        # Check for components with P95 Memory > 80%
        HIGH_MEMORY=$(echo "${RESULT}" | jq -r '.[] | select(.P95Memory > 80) | "  - Component \(.Component) has high P95 Memory: \(.P95Memory)%"')
        if [ -n "${HIGH_MEMORY}" ]; then
            warn "High memory usage detected (P95 > 80%):"
            echo -e "${YELLOW}${HIGH_MEMORY}${NC}" # Print warning in yellow
        fi
        
        # Check for components with Volatile memory stability (StdDev >= 15%)
        VOLATILE_MEMORY=$(echo "${RESULT}" | jq -r '.[] | select(.MemoryStability == "Volatile") | "  - Component \(.Component) has volatile memory: StdDev \(.StdDevMemory)%"')
        if [ -n "${VOLATILE_MEMORY}" ]; then
            warn "Volatile memory usage detected (StdDev > 15%):"
            echo -e "${YELLOW}${VOLATILE_MEMORY}${NC}" # Print warning in yellow
        fi
    fi
    echo "" # Add a newline for spacing
}

# analyze_memory_allocation
# Queries and displays memory allocation (allocated vs. used bytes) and heap utilization
# for components based on Azure Monitor logs. Uses numfmt for human-readable byte counts.
# Implicitly uses global variables: COMPONENT, TIME_RANGE, WORKSPACE_ID.
analyze_memory_allocation() {
    log "Analyzing memory allocation..."
    
    # Build KQL filter part for component if not 'all'.
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # KQL query to get 'memory_allocated_bytes' and 'memory_used_bytes' metrics.
    # - Summarizes average value by Component and MetricName.
    # - Extends MetricName to 'Allocated' or 'Used' for clarity.
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName in ('memory_allocated_bytes', 'memory_used_bytes')
    ${COMPONENT_FILTER}
    | summarize 
        AvgValue = avg(MetricValue)
        by Component, MetricName
    | extend MetricName = iff(MetricName == 'memory_allocated_bytes', 'Allocated', 'Used')
    | order by Component asc, MetricName asc
    "
    
    # Execute Azure CLI query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    AZ_EXIT_STATUS=$? # Capture exit status

    if [ ${AZ_EXIT_STATUS} -ne 0 ]; then
        warn "Failed to retrieve data for memory allocation analysis. Azure CLI exited with status ${AZ_EXIT_STATUS}."
        if [[ -n "$RESULT" ]]; then warn "Azure CLI output: $RESULT"; fi
        return
    fi

    if ! echo "$RESULT" | jq . > /dev/null 2>&1; then
        warn "No data returned or invalid JSON format for memory allocation analysis. Raw output: $RESULT"
        return
    fi
    
    # Parse and display results
    echo -e "\nMemory Allocation (Average Bytes, Time Range: ${TIME_RANGE}):"
    echo "----------------------------------------------------------"
    
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then
        echo "No data to display for memory allocation."
    else
        # Get unique component names
        COMPONENTS=$(echo "${RESULT}" | jq -r '.[].Component' | sort | uniq)
        
        for component_name in ${COMPONENTS}; do # Loop through each component
            echo -e "\nComponent: ${component_name}"
            
            # Extract average allocated bytes for the current component
            ALLOCATED_BYTES=$(echo "${RESULT}" | jq -r --arg comp "$component_name" --arg metric_name "Allocated" \
                '.[] | select(.Component == $comp and .MetricName == $metric_name) | .AvgValue')
            
            # Extract average used bytes for the current component
            USED_BYTES=$(echo "${RESULT}" | jq -r --arg comp "$component_name" --arg metric_name "Used" \
                '.[] | select(.Component == $comp and .MetricName == $metric_name) | .AvgValue')
            
            # Calculate and display utilization if data is valid and allocated bytes > 0
            if [ -n "${ALLOCATED_BYTES}" ] && [ -n "${USED_BYTES}" ] && \
               [ "${ALLOCATED_BYTES}" != "null" ] && [ "${USED_BYTES}" != "null" ] && \
               [ "$(echo "${ALLOCATED_BYTES} > 0" | bc -l)" -eq 1 ]; then # Check if allocated > 0 to avoid division by zero
                
                # Calculate heap utilization percentage using bc
                UTILIZATION=$(echo "scale=2; ${USED_BYTES} / ${ALLOCATED_BYTES} * 100" | bc)
                
                # Convert byte values to human-readable format (KB, MB, GB) using numfmt
                # Fallback to raw value with 'B' suffix if numfmt fails (e.g., non-numeric input)
                ALLOCATED_HR=$(numfmt --to=iec --suffix=B "${ALLOCATED_BYTES}" 2>/dev/null || echo "${ALLOCATED_BYTES}B")
                USED_HR=$(numfmt --to=iec --suffix=B "${USED_BYTES}" 2>/dev/null || echo "${USED_BYTES}B")
                
                echo "  Allocated: ${ALLOCATED_HR}"
                echo "  Used: ${USED_HR}"
                echo "  Heap Utilization: ${UTILIZATION}%"
                
                # Warn if heap utilization is less than 50%
                if (( $(echo "${UTILIZATION} < 50" | bc -l) )); then
                    warn "Component ${component_name} may have inefficient memory allocation (${UTILIZATION}% heap utilization)."
                fi
            else
                echo "  Incomplete or zero allocated memory metrics available for ${component_name}."
            fi
        done
    fi
    echo "" # Add a newline for spacing
}

# analyze_memory_leaks
# Queries and displays memory usage trends over 24 hours (1-hour intervals) to identify
# potential memory leaks (consistently increasing memory usage).
# Implicitly uses global variables: COMPONENT, WORKSPACE_ID.
analyze_memory_leaks() {
    log "Analyzing potential memory leaks..."
    
    # Build KQL filter part for component if not 'all'.
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # KQL query to get average 'memory_used_bytes' binned by 1 hour over a 24 hour time range.
    QUERY="
    let timeRange = 24h;
    let interval = 1h;
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'memory_used_bytes'
    ${COMPONENT_FILTER}
    | summarize 
        AvgMemory = avg(MetricValue)
        by bin(TimeGenerated, interval), Component
    | order by Component asc, TimeGenerated asc
    "
    
    # Execute Azure CLI query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    AZ_EXIT_STATUS=$? # Capture exit status

    if [ ${AZ_EXIT_STATUS} -ne 0 ]; then
        warn "Failed to retrieve data for memory leak analysis. Azure CLI exited with status ${AZ_EXIT_STATUS}."
        if [[ -n "$RESULT" ]]; then warn "Azure CLI output: $RESULT"; fi
        return
    fi

    if ! echo "$RESULT" | jq . > /dev/null 2>&1; then
        warn "No data returned or invalid JSON format for memory leak analysis. Raw output: $RESULT"
        return
    fi
    
    # Parse and display results
    echo -e "\nMemory Usage Trend (Average Bytes over last 24h, 1h interval):"
    echo "----------------------------------------------------------------"
    
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then
        echo "No data to display for memory leak analysis."
    else
        COMPONENTS=$(echo "${RESULT}" | jq -r '.[].Component' | sort | uniq)
        
        for component_name in ${COMPONENTS}; do # Loop through each component
            echo -e "\nComponent: ${component_name}"
            
            # Extract and format memory trend data for the current component.
            # jq creates an array of objects {time, memory}.
            MEMORY_TREND=$(echo "${RESULT}" | jq -r --arg comp "$component_name" \
                '[.[] | select(.Component == $comp) | {time: .TimeGenerated, memory: .AvgMemory}]')
            
            if [[ -z "$MEMORY_TREND" || "$MEMORY_TREND" == "null" || "$MEMORY_TREND" == "[]" ]]; then
                echo "  No memory trend data available for ${component_name}."
                continue # Skip to next component
            fi
            
            # Display trend data.
            # .memory is converted to number, then processed by numfmt (via placeholder आय and sed for backticks),
            # or fallback to string + "B" if numfmt fails.
            echo "${MEMORY_TREND}" | jq -r '.[] | .time[0:19] + "Z | Avg Used Memory: " + (.memory | tonumber | আয় numfmt --to=iec --suffix=B 2>/dev/null // tostring+"B")'  | sed 's/आय/`/; s/` /`/'
            
            # Check for consistent increase if there are enough data points.
            TREND_COUNT=$(echo "${MEMORY_TREND}" | jq 'length')
            if [ "${TREND_COUNT}" -gt 3 ]; then
                INCREASES=0      # Counter for increases.
                PREVIOUS_MEMORY="" # Stores previous memory value.
                
                # Iterate over memory values in the trend.
                for current_memory in $(echo "${MEMORY_TREND}" | jq -r '.[].memory'); do
                    if [ -n "${PREVIOUS_MEMORY}" ] && [ "${current_memory}" != "null" ] && [ "${PREVIOUS_MEMORY}" != "null" ] && \
                       (( $(echo "${current_memory} > ${PREVIOUS_MEMORY}" | bc -l) )); then
                        INCREASES=$((INCREASES + 1))
                    fi
                    PREVIOUS_MEMORY="${current_memory}"
                done
                
                # Calculate 80% threshold for number of increases.
                THRESHOLD=$(echo "scale=0; ${TREND_COUNT} * 0.8 / 1" | bc) # Integer part.
                if [ "${INCREASES}" -ge "${THRESHOLD}" ] && [ "${THRESHOLD}" -gt 0 ]; then # If increases meet or exceed threshold.
                    warn "Potential memory leak detected in ${component_name} (used memory consistently increased over ${INCREASES}/${TREND_COUNT} intervals of 1h)."
                fi
            fi
        done
    fi
    echo "" # Add a newline for spacing
}

# analyze_garbage_collection
# Queries and displays garbage collection metrics (count and duration) by GC type
# for components based on Azure Monitor logs.
# Implicitly uses global variables: COMPONENT, TIME_RANGE, WORKSPACE_ID.
analyze_garbage_collection() {
    log "Analyzing garbage collection..."
    
    # Build KQL filter part for component if not 'all'.
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # KQL query for 'gc_count' and 'gc_duration_ms' metrics.
    # - Summarizes average, max, and total values by Component, MetricName, and GCType.
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName in ('gc_count', 'gc_duration_ms')
    ${COMPONENT_FILTER}
    | summarize 
        AvgValue = avg(MetricValue),
        MaxValue = max(MetricValue),
        TotalValue = sum(MetricValue)
        by Component, MetricName, GCType
    | order by Component asc, GCType asc, MetricName asc
    "
    
    # Execute Azure CLI query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    AZ_EXIT_STATUS=$? # Capture exit status

    if [ ${AZ_EXIT_STATUS} -ne 0 ]; then
        warn "Failed to retrieve data for garbage collection analysis. Azure CLI exited with status ${AZ_EXIT_STATUS}."
        if [[ -n "$RESULT" ]]; then warn "Azure CLI output: $RESULT"; fi
        return
    fi

    if ! echo "$RESULT" | jq . > /dev/null 2>&1; then
        warn "No data returned or invalid JSON format for garbage collection analysis. Raw output: $RESULT"
        return
    fi
    
    # Parse and display results
    echo -e "\nGarbage Collection Analysis (Time Range: ${TIME_RANGE}):"
    echo "---------------------------------------------------"
    
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then
        echo "No garbage collection metrics available for this period."
        return
    fi
    
    # Check if the result contains any data points.
    METRIC_COUNT=$(echo "${RESULT}" | jq 'length') 
    
    if [ "${METRIC_COUNT}" -gt 0 ]; then
        COMPONENTS=$(echo "${RESULT}" | jq -r '.[].Component' | sort | uniq)
        
        for component_name in ${COMPONENTS}; do # Loop through each component
            echo -e "\nComponent: ${component_name}"
            
            # Get unique GC types reported for the component
            GC_TYPES=$(echo "${RESULT}" | jq -r --arg comp "$component_name" \
                '.[] | select(.Component == $comp) | .GCType' | sort | uniq)
            
            if [[ -z "$GC_TYPES" ]]; then
                echo "  No specific GC types found for ${component_name}."
                continue # Skip to next component if no GC types
            fi

            for gc_type in ${GC_TYPES}; do # Loop through each GC type
                echo "  GC Type: ${gc_type}"
                
                # Extract total GC count for the current component and GC type
                GC_TOTAL_COUNT_VAL=$(echo "${RESULT}" | jq -r --arg comp "$component_name" --arg gc "$gc_type" --arg metric_name "gc_count" \
                    '.[] | select(.Component == $comp and .GCType == $gc and .MetricName == $metric_name) | .TotalValue')
                
                # Extract average GC duration for the current component and GC type
                GC_AVG_DURATION_VAL=$(echo "${RESULT}" | jq -r --arg comp "$component_name" --arg gc "$gc_type" --arg metric_name "gc_duration_ms" \
                    '.[] | select(.Component == $comp and .GCType == $gc and .MetricName == $metric_name) | .AvgValue')
                
                if [ -n "${GC_TOTAL_COUNT_VAL}" ] && [ -n "${GC_AVG_DURATION_VAL}" ] && \
                   [ "${GC_TOTAL_COUNT_VAL}" != "null" ] && [ "${GC_AVG_DURATION_VAL}" != "null" ]; then
                    # Format count and duration as integers for display
                    GC_TOTAL_COUNT_INT=$(printf "%.0f" "${GC_TOTAL_COUNT_VAL}")
                    GC_AVG_DURATION_INT=$(printf "%.0f" "${GC_AVG_DURATION_VAL}")

                    echo "    Total Collections: ${GC_TOTAL_COUNT_INT}"
                    echo "    Average Duration: ${GC_AVG_DURATION_INT}ms"
                    
                    # Define a dynamic threshold for frequent GC based on the time range.
                    local count_threshold=100 # Default for shorter time ranges (e.g., 1h)
                    if [[ "$TIME_RANGE" == "24h" ]]; then count_threshold=1000; fi; # Higher threshold for 24h
                    
                    if (( $(echo "${GC_TOTAL_COUNT_VAL} > $count_threshold" | bc -l) )); then
                        warn "Component ${component_name} (GC Type: ${gc_type}) shows frequent garbage collection: ${GC_TOTAL_COUNT_INT} collections in ${TIME_RANGE}."
                    fi
                    
                    if (( $(echo "${GC_AVG_DURATION_VAL} > 200" | bc -l) )); then # Threshold for long GC pauses
                        warn "Component ${component_name} (GC Type: ${gc_type}) shows long garbage collection pauses: ${GC_AVG_DURATION_INT}ms average."
                    fi
                else
                    echo "    Incomplete GC count or duration metrics available for GC Type ${gc_type}."
                fi
            done
        done
    else
        echo "No garbage collection metrics data points found." # This case should ideally be caught by the earlier check of RESULT.
    fi
    echo "" # Add a newline for spacing
}

# generate_recommendations
# Generates memory optimization recommendations based on analyzed metrics.
# It re-queries some summarized data to ensure recommendations are based on consistent timeframes.
# Implicitly uses global variables: COMPONENT, TIME_RANGE, WORKSPACE_ID.
generate_recommendations() {
    log "Generating memory optimization recommendations..."
    
    echo -e "\nMemory Optimization Recommendations:" # Added newline for better separation
    echo "----------------------------------"
    
    # Build KQL filter part for component if not 'all'.
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # KQL query to fetch summary metrics for recommendations.
    # Fetches average 'memory_percent', 'memory_allocated_bytes', 'memory_used_bytes'.
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName in ('memory_percent', 'memory_allocated_bytes', 'memory_used_bytes')
    ${COMPONENT_FILTER}
    | summarize 
        AvgValue = avg(MetricValue),
        MaxValue = max(MetricValue)
        by Component, MetricName
    | order by Component asc, MetricName asc
    "
    
    # Execute query
    RESULT_REC=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json) # Renamed to avoid conflict
    AZ_EXIT_STATUS_REC=$?

    if [ ${AZ_EXIT_STATUS_REC} -ne 0 ]; then
        warn "Failed to retrieve main metrics for recommendations. Azure CLI exited with status ${AZ_EXIT_STATUS_REC}."
        if [[ -n "$RESULT_REC" ]]; then warn "Azure CLI output: $RESULT_REC"; fi
        return
    fi

    if ! echo "$RESULT_REC" | jq . > /dev/null 2>&1; then
        warn "No data returned or invalid JSON format for main recommendation metrics. Raw output: $RESULT_REC"
        return
    fi

    if [[ -z "$RESULT_REC" || "$RESULT_REC" == "null" || "$RESULT_REC" == "[]" ]]; then
        echo "No main metrics data to generate recommendations."
        return
    fi
    
    # Get unique component names from the recommendation metrics query result.
    COMPONENTS=$(echo "$RESULT_REC" | jq -r '.[].Component' | sort | uniq)
    
    for component_name in ${COMPONENTS}; do # Loop through each component
        echo -e "\nRecommendations for Component: ${component_name}"
        echo "---------------------------------------"
        REC_COUNT=0 # Initialize recommendation counter for the component.

        # Extract average memory percentage.
        MEM_PERCENT_AVG=$(echo "$RESULT_REC" | jq -r --arg comp "$component_name" --arg metric_name "memory_percent" \
            '.[] | select(.Component == $comp and .MetricName == $metric_name) | .AvgValue')
        
        # Extract average allocated memory in bytes.
        MEM_ALLOCATED_AVG_BYTES=$(echo "$RESULT_REC" | jq -r --arg comp "$component_name" --arg metric_name "memory_allocated_bytes" \
            '.[] | select(.Component == $comp and .MetricName == $metric_name) | .AvgValue')
            
        # Extract average used memory in bytes.
        MEM_USED_AVG_BYTES=$(echo "$RESULT_REC" | jq -r --arg comp "$component_name" --arg metric_name "memory_used_bytes" \
            '.[] | select(.Component == $comp and .MetricName == $metric_name) | .AvgValue')

        # Recommendation 1: Overall Memory Usage Percentage
        if [ -n "${MEM_PERCENT_AVG}" ] && [ "${MEM_PERCENT_AVG}" != "null" ]; then
            REC_COUNT=$((REC_COUNT + 1))
            MEM_PERCENT_AVG_INT=$(printf "%.0f" "${MEM_PERCENT_AVG}") # Format as integer for display.
            echo "${REC_COUNT}. Overall Memory Usage (memory_percent):"
            if (( $(echo "${MEM_PERCENT_AVG} > 85" | bc -l) )); then # High usage
                echo "   - Reason: High average memory usage detected (${MEM_PERCENT_AVG_INT}%)."
                echo "   - Action: Investigate memory-intensive processes or code paths. Consider increasing memory limits/requests if usage is legitimate."
            elif (( $(echo "${MEM_PERCENT_AVG} < 40" | bc -l) )); then # Low usage
                echo "   - Reason: Low average memory usage detected (${MEM_PERCENT_AVG_INT}%)."
                echo "   - Action: Consider reducing memory limits/requests to improve resource efficiency if consistently low."
            else # Normal usage
                echo "   - Observation: Memory usage (${MEM_PERCENT_AVG_INT}%) appears to be within acceptable limits (40-85%)."
            fi
        fi
        
        # Recommendation 2: Heap Utilization (from allocated and used bytes)
        if [ -n "${MEM_ALLOCATED_AVG_BYTES}" ] && [ -n "${MEM_USED_AVG_BYTES}" ] && \
           [ "${MEM_ALLOCATED_AVG_BYTES}" != "null" ] && [ "${MEM_USED_AVG_BYTES}" != "null" ] && \
           [ "$(echo "${MEM_ALLOCATED_AVG_BYTES} > 0" | bc -l)" -eq 1 ]; then # Ensure allocated is > 0
            
            # Calculate heap utilization.
            UTILIZATION_REC=$(echo "scale=2; ${MEM_USED_AVG_BYTES} / ${MEM_ALLOCATED_AVG_BYTES} * 100" | bc)
            UTILIZATION_REC_INT=$(printf "%.0f" "${UTILIZATION_REC}") # Format as integer.
            # Convert bytes to human-readable for the message.
            ALLOCATED_HR=$(numfmt --to=iec --suffix=B "${MEM_ALLOCATED_AVG_BYTES}" 2>/dev/null || echo "${MEM_ALLOCATED_AVG_BYTES}B")
            USED_HR=$(numfmt --to=iec --suffix=B "${MEM_USED_AVG_BYTES}" 2>/dev/null || echo "${MEM_USED_AVG_BYTES}B")

            REC_COUNT=$((REC_COUNT + 1))
            echo "${REC_COUNT}. Heap Utilization (Used vs. Allocated Bytes):"
            if (( $(echo "${UTILIZATION_REC} < 50" | bc -l) )); then # Low utilization
                echo "   - Reason: Low heap utilization detected (${UTILIZATION_REC_INT}%). Used: ${USED_HR}, Allocated: ${ALLOCATED_HR}."
                echo "   - Action: Review JVM heap settings (e.g., -Xms, -Xmx if applicable) or application's memory request vs. limit. This might indicate over-allocation or opportunity for optimization."
            else # Normal utilization
                echo "   - Observation: Heap utilization (${UTILIZATION_REC_INT}%) appears reasonable (Used: ${USED_HR}, Allocated: ${ALLOCATED_HR})."
            fi
        fi
        
        # Recommendation 3: Garbage Collection Pauses.
        # This involves a specific KQL query for GC duration for the current component.
        GC_QUERY_REC="
        let timeRange = ${TIME_RANGE};
        Metrics
        | where TimeGenerated > ago(timeRange)
        | where MetricName == 'gc_duration_ms'
        | where Component == '${component_name}' # Changed from global component to component_name
        | summarize AvgDuration = avg(MetricValue) by GCType
        "
        
        GC_RESULT_REC=$(az monitor log-analytics query \
            --workspace "${WORKSPACE_ID}" \
            --analytics-query "${GC_QUERY_REC}" \
            --output json)
        AZ_EXIT_STATUS_GC_REC=$?

        if [ ${AZ_EXIT_STATUS_GC_REC} -ne 0 ]; then
            warn "Failed to retrieve GC metrics for recommendations (component: ${component_name}). Azure CLI exited with status ${AZ_EXIT_STATUS_GC_REC}."
        elif ! echo "$GC_RESULT_REC" | jq . > /dev/null 2>&1; then
            warn "No data or invalid JSON for GC recommendation metrics (component: ${component_name}). Raw: $GC_RESULT_REC"
        elif [[ -n "$GC_RESULT_REC" && "$GC_RESULT_REC" != "null" && "$GC_RESULT_REC" != "[]" ]]; then
            LONG_GC_PAUSES=$(echo "$GC_RESULT_REC" | jq -r '[.[] | select(.AvgDuration > 200) | .GCType] | unique | join(", ")') # Get unique GC types with long pauses
            
            # Extract unique GC types with average duration > 200ms.
            LONG_GC_PAUSES=$(echo "$GC_RESULT_REC" | jq -r '[.[] | select(.AvgDuration > 200) | .GCType] | unique | join(", ")')
            
            if [ -n "${LONG_GC_PAUSES}" ]; then
                REC_COUNT=$((REC_COUNT + 1))
                echo "${REC_COUNT}. Garbage Collection Pauses:"
                echo "   - Reason: Long average GC pauses (>200ms) detected for GC type(s): ${LONG_GC_PAUSES}."
                echo "   - Action: Profile GC behavior (e.g., using JDK tools like jstat, VisualVM, or APM). Investigate object allocation patterns and rates. Consider tuning GC parameters (e.g., different GC algorithm, heap regions, young/old generation sizing) if appropriate for the workload."
            else
                # Only print this observation if no other recommendations have been made for this component.
                if [ ${REC_COUNT} -eq 0 ]; 
                then
                    REC_COUNT=$((REC_COUNT + 1)) # Increment REC_COUNT to show this as a numbered item.
                    echo "${REC_COUNT}. Garbage Collection Pauses:"
                    echo "   - Observation: Average GC pause durations appear to be within acceptable limits (<200ms)."
                fi
            fi
        fi

        # If no recommendations were triggered for the component.
        if [ ${REC_COUNT} -eq 0 ]; then
            echo "No specific memory optimization recommendations for ${component_name} at this time based on available data."
        fi
    done
    echo "" # Add a newline for spacing
}

# main
# Main function to orchestrate the script's operations:
# 1. Logs start of analysis, including environment, component, and time range.
# 2. Calls functions to analyze various memory aspects (usage, allocation, leaks, GC).
# 3. Calls function to generate recommendations based on the analysis.
# 4. Logs completion of analysis.
# Implicitly uses global variables: ENV, COMPONENT, TIME_RANGE (for logging).
main() {
    log "Starting memory analysis for environment: ${ENV}, component: ${COMPONENT}, time range: ${TIME_RANGE}"
    
    analyze_memory_usage
    analyze_memory_allocation
    analyze_memory_leaks
    analyze_garbage_collection
    generate_recommendations
    
    log "Memory analysis completed for environment: ${ENV}"
}

# Execute main function
main