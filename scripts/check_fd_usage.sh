#!/bin/bash
# scripts/check_fd_usage.sh

set -e

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )" # Absolute path to the script's directory
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")" # Project root directory, assuming script is in a 'scripts' subdirectory

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
    echo "Analyzes file descriptor usage using Azure Monitor data."
    echo "Usage: ./check_fd_usage.sh [environment] [component] [time_range]"
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

# check_fd_usage
# Queries and displays average, maximum, and 95th percentile file descriptor usage
# for components based on Azure Monitor logs.
# Implicitly uses global variables: COMPONENT, TIME_RANGE, WORKSPACE_ID.
check_fd_usage() {
    log "Checking file descriptor usage..."
    
    # Build KQL filter part for component if not 'all'.
    # This string will be injected into the KQL query.
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # Kusto Query Language (KQL) query to get FD metrics.
    # - Summarizes average, max, and 95th percentile of 'file_descriptors' metric.
    # - Groups by Component.
    # - Orders by max FD descending.
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'file_descriptors'
    ${COMPONENT_FILTER}
    | summarize 
        AvgFD = avg(MetricValue),
        MaxFD = max(MetricValue),
        P95FD = percentile(MetricValue, 95)
        by Component
    | order by MaxFD desc
    "
    
    # Execute Azure CLI query to fetch metrics from Azure Monitor Log Analytics
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    AZ_EXIT_STATUS=$? # Capture exit status of the az command

    # Check for az command execution failure
    if [ ${AZ_EXIT_STATUS} -ne 0 ]; then
        warn "Failed to retrieve data for FD usage check. Azure CLI exited with status ${AZ_EXIT_STATUS}."
        if [[ -n "$RESULT" ]]; then warn "Azure CLI output: $RESULT"; fi # Show az output if any
        return
    fi

    # Validate if RESULT is valid JSON by piping to 'jq .' and suppressing output.
    # Errors from jq (e.g., if RESULT is not JSON) are redirected to /dev/null.
    if ! echo "$RESULT" | jq . > /dev/null 2>&1; then
        warn "No data returned or invalid JSON format for FD usage check. Raw output: $RESULT"
        return
    fi
    
    # Parse and display results
    echo -e "\nFile Descriptor Usage (Time Range: ${TIME_RANGE}):"
    echo "---------------------------------------------"
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then # Check if result is empty or null JSON array
        echo "No data to display for FD usage."
    else
        # Use jq to format the output: iterate over each JSON object in the array and print formatted string
        echo "${RESULT}" | jq -r '.[] | "Component: \(.Component) | Average FD: \(.AvgFD) | Maximum FD: \(.MaxFD) | 95th Percentile FD: \(.P95FD)"'
        
        # Check for components with P95 FD usage greater than 1000
        # jq filters for P95FD > 1000 and creates a warning string.
        HIGH_FD_WARNINGS=$(echo "${RESULT}" | jq -r '.[] | select(.P95FD > 1000) | "Component \(.Component) has high P95 FD: \(.P95FD)"')
        if [ -n "${HIGH_FD_WARNINGS}" ]; then
            warn "High file descriptor usage detected (P95 > 1000):"
            echo -e "${YELLOW}${HIGH_FD_WARNINGS}${NC}" # Keep warning color for the output
        fi
    fi
    echo "" # Add a newline for spacing
}

# check_fd_limits
# Queries and displays the latest file descriptor usage, configured limits, and utilization percentage
# for components based on Azure Monitor logs.
# Implicitly uses global variables: COMPONENT, TIME_RANGE, WORKSPACE_ID.
check_fd_limits() {
    log "Checking file descriptor limits..."
    
    # Build KQL filter part for component if not 'all'.
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # KQL query to get FD usage ('file_descriptors') and FD limits ('file_descriptor_limit').
    # - Summarizes average value by 5-minute intervals, component, and metric name.
    # - Orders by time descending to get latest values first.
    # - Limits to 1000 records to manage data volume (results are processed to find the latest per component).
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName in ('file_descriptors', 'file_descriptor_limit')
    ${COMPONENT_FILTER}
    | summarize 
        AvgValue = avg(MetricValue)
        by bin(TimeGenerated, 5m), Component, MetricName
    | order by TimeGenerated desc, Component asc
    | limit 1000
    "
    
    # Execute Azure CLI query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    AZ_EXIT_STATUS=$? # Capture exit status

    if [ ${AZ_EXIT_STATUS} -ne 0 ]; then
        warn "Failed to retrieve data for FD limits check. Azure CLI exited with status ${AZ_EXIT_STATUS}."
        if [[ -n "$RESULT" ]]; then warn "Azure CLI output: $RESULT"; fi
        return
    fi

    if ! echo "$RESULT" | jq . > /dev/null 2>&1; then
        warn "No data returned or invalid JSON format for FD limits check. Raw output: $RESULT"
        return
    fi
    
    # Parse and display results
    echo -e "\nFile Descriptor Limits & Utilization (Latest values in Time Range: ${TIME_RANGE}):"
    echo "--------------------------------------------------------------------------"
    
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then
        echo "No data to display for FD limits."
    else
        # Get unique component names from the results
        COMPONENTS=$(echo "${RESULT}" | jq -r '.[].Component' | sort | uniq)
        
        for component_name in ${COMPONENTS}; do # Loop through each component
            echo -e "\nComponent: ${component_name}"
            
            # Extract the latest timestamp for the current component's metrics from the sorted results.
            # jq selects entries for the current component, extracts TimeGenerated, sorts, and takes the last (latest).
            LATEST_TIME=$(echo "${RESULT}" | jq -r --arg component_arg "$component_name" \
                '.[] | select(.Component == $component_arg) | .TimeGenerated' | sort | tail -n 1)
            
            # Extract FD usage for the component at the latest timestamp.
            # jq filters by component, timestamp, and metric name.
            FD_USAGE=$(echo "${RESULT}" | jq -r --arg component_arg "$component_name" --arg time_arg "${LATEST_TIME}" --arg metric_arg "file_descriptors" \
                '.[] | select(.Component == $component_arg and .TimeGenerated == $time_arg and .MetricName == $metric_arg) | .AvgValue')
            
            # Extract FD limit for the component at the latest timestamp.
            FD_LIMIT=$(echo "${RESULT}" | jq -r --arg component_arg "$component_name" --arg time_arg "${LATEST_TIME}" --arg metric_arg "file_descriptor_limit" \
                '.[] | select(.Component == $component_arg and .TimeGenerated == $time_arg and .MetricName == $metric_arg) | .AvgValue')
            
            if [ -n "${FD_USAGE}" ] && [ -n "${FD_LIMIT}" ] && [ "${FD_USAGE}" != "null" ] && [ "${FD_LIMIT}" != "null" ]; then
                # Calculate utilization percentage using bc for floating point arithmetic (scale=2 for two decimal places).
                UTILIZATION=$(echo "scale=2; ${FD_USAGE} / ${FD_LIMIT} * 100" | bc)
                
                echo "  Current Average FD Usage: ${FD_USAGE}"
                echo "  Configured FD Limit: ${FD_LIMIT}"
                echo "  Utilization: ${UTILIZATION}%"
                
                # Check if utilization is over 80%. bc -l enables floating point comparison.
                if (( $(echo "${UTILIZATION} > 80" | bc -l) )); then 
                    warn "Component ${component_name} has high file descriptor utilization: ${UTILIZATION}%"
                fi
            else
                echo "  Incomplete file descriptor metrics (usage or limit) available for ${component_name} at ${LATEST_TIME}"
            fi
        done
    fi
    echo "" # Add a newline for spacing
}

# analyze_fd_trends
# Queries and displays file descriptor usage trends over the last 24 hours (1-hour intervals)
# and warns if a potential leak (consistent increase) is detected.
# Implicitly uses global variables: COMPONENT, WORKSPACE_ID.
analyze_fd_trends() {
    log "Analyzing file descriptor trends..."
    
    # Build KQL filter part for component if not 'all'.
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # KQL query to get average FD usage binned by 1 hour over a 24 hour time range.
    # - `let timeRange = 24h` and `let interval = 1h` define variables within KQL.
    # - `bin(TimeGenerated, interval)` groups data into 1-hour buckets.
    QUERY="
    let timeRange = 24h;
    let interval = 1h;
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'file_descriptors'
    ${COMPONENT_FILTER}
    | summarize 
        AvgFD = avg(MetricValue)
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
        warn "Failed to retrieve data for FD trends analysis. Azure CLI exited with status ${AZ_EXIT_STATUS}."
        if [[ -n "$RESULT" ]]; then warn "Azure CLI output: $RESULT"; fi
        return
    fi

    if ! echo "$RESULT" | jq . > /dev/null 2>&1; then
        warn "No data returned or invalid JSON format for FD trends analysis. Raw output: $RESULT"
        return
    fi
    
    # Parse and display results
    echo -e "\nFile Descriptor Trends (Average Usage over last 24h, 1h interval):"
    echo "-----------------------------------------------------------------"
    
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then
        echo "No data to display for FD trends."
    else
        COMPONENTS=$(echo "${RESULT}" | jq -r '.[].Component' | sort | uniq)
        
        for component_name in ${COMPONENTS}; do # Loop through each component
            echo -e "\nComponent: ${component_name}"
            
            # Extract and format FD trend data for the current component into a JSON array of objects {time, fd}.
            # jq filters by component and transforms the data.
            FD_TREND=$(echo "${RESULT}" | jq -r --arg component_arg "$component_name" \
                '[.[] | select(.Component == $component_arg) | {time: .TimeGenerated, fd: .AvgFD}]')
            
            if [[ -z "$FD_TREND" || "$FD_TREND" == "null" || "$FD_TREND" == "[]" ]]; then
                echo "  No trend data for component ${component_name}."
                continue # Skip to next component
            fi

            # Display the trend data, formatted by jq.
            echo "${FD_TREND}" | jq -r '.[] | "  Time: \(.time) | Average FD: \(.fd)"'
            
            # Check for consistent increase (potential leak) if there are more than 3 data points.
            TREND_COUNT=$(echo "${FD_TREND}" | jq 'length') # Get number of data points in the trend.
            if [ "${TREND_COUNT}" -gt 3 ]; then
                INCREASES=0      # Counter for number of times FD usage increased consecutively.
                PREVIOUS_FD=""   # Stores the FD value from the previous interval.
                
                # Iterate over average FD values in the trend.
                for current_fd_value in $(echo "${FD_TREND}" | jq -r '.[].fd'); do
                    # Check for increase if PREVIOUS_FD is not empty and values are valid numbers.
                    if [ -n "${PREVIOUS_FD}" ] && [ "${current_fd_value}" != "null" ] && [ "${PREVIOUS_FD}" != "null" ] && (( $(echo "${current_fd_value} > ${PREVIOUS_FD}" | bc -l) )); then
                        INCREASES=$((INCREASES + 1))
                    fi
                    PREVIOUS_FD="${current_fd_value}"
                done
                
                # If FD usage increased in at least 80% of the intervals, flag as potential leak.
                # Calculate 80% threshold (integer part using bc with scale=0 and division by 1).
                THRESHOLD=$(echo "scale=0; ${TREND_COUNT} * 0.8 / 1" | bc) 
                if [ "${INCREASES}" -ge "${THRESHOLD}" ] && [ "${THRESHOLD}" -gt 0 ]; then # Ensure threshold is meaningful (e.g., not 0).
                    warn "Potential file descriptor leak detected in ${component_name} (FD count consistently increased over ${INCREASES}/${TREND_COUNT} intervals of 1h)"
                fi
            fi
        done
    fi
    echo "" # Add a newline for spacing
}

# check_connection_fds
# Queries and displays metrics for TCP and socket connections (e.g., by state like TIME_WAIT).
# Implicitly uses global variables: COMPONENT, TIME_RANGE, WORKSPACE_ID.
check_connection_fds() {
    log "Checking connection-related file descriptors..."
    
    # Build KQL filter part for component if not 'all'.
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # KQL query for TCP and socket connection metrics.
    # - Filters for 'tcp_connections' and 'socket_connections' metrics.
    # - Summarizes average and max values by Component, MetricName, and ConnectionState.
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName in ('tcp_connections', 'socket_connections')
    ${COMPONENT_FILTER}
    | summarize 
        AvgValue = avg(MetricValue),
        MaxValue = max(MetricValue)
        by Component, MetricName, ConnectionState
    | order by Component asc, MetricName asc, ConnectionState asc
    "
    
    # Execute Azure CLI query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    AZ_EXIT_STATUS=$? # Capture exit status

    if [ ${AZ_EXIT_STATUS} -ne 0 ]; then
        warn "Failed to retrieve data for connection-related FDs. Azure CLI exited with status ${AZ_EXIT_STATUS}."
        if [[ -n "$RESULT" ]]; then warn "Azure CLI output: $RESULT"; fi
        return
    fi

    if ! echo "$RESULT" | jq . > /dev/null 2>&1; then
        warn "No data returned or invalid JSON format for connection-related FDs. Raw output: $RESULT"
        return
    fi
    
    # Parse and display results
    echo -e "\nConnection-Related File Descriptors (Time Range: ${TIME_RANGE}):"
    echo "---------------------------------------------------------------"
    
    if [[ -z "$RESULT" || "$RESULT" == "null" || "$RESULT" == "[]" ]]; then
        echo "No connection metrics available."
        return
    fi
    
    # This check is somewhat redundant due to the one above, but ensures CONN_COUNT is set if needed later.
    CONN_COUNT=$(echo "${RESULT}" | jq 'length') 
    
    if [ "${CONN_COUNT}" -gt 0 ]; then
        COMPONENTS=$(echo "${RESULT}" | jq -r '.[].Component' | sort | uniq)
        
        for component_name in ${COMPONENTS}; do # Loop through each component
            echo -e "\nComponent: ${component_name}"
            
            # Extract TCP connection data for the component.
            # jq creates an array of objects, each containing state, average, and max values.
            TCP_CONNECTIONS_RAW=$(echo "${RESULT}" | jq -r --arg component_arg "$component_name" --arg metric_arg "tcp_connections" \
                '[.[] | select(.Component == $component_arg and .MetricName == $metric_arg) | {state: .ConnectionState, avg: .AvgValue, max: .MaxValue}]')
            
            if [ -n "${TCP_CONNECTIONS_RAW}" ] && [ "${TCP_CONNECTIONS_RAW}" != "[]" ]; then
                echo "  TCP Connections:"
                # Format and print TCP connection states, average, and max values.
                echo "${TCP_CONNECTIONS_RAW}" | jq -r '.[] | "    State: \(.state) | Average Connections: \(.avg) | Maximum Connections: \(.max)"'
                
                # Check for high number of TIME_WAIT connections.
                # Extracts the average value for TIME_WAIT state from the already filtered TCP_CONNECTIONS_RAW.
                TIME_WAIT_VALUE=$(echo "${TCP_CONNECTIONS_RAW}" | jq -r '.[] | select(.state == "TIME_WAIT") | .avg')
                
                if [ -n "${TIME_WAIT_VALUE}" ] && [ "${TIME_WAIT_VALUE}" != "null" ] && (( $(echo "${TIME_WAIT_VALUE} > 1000" | bc -l) )); then
                    warn "Component ${component_name} has a high number of TCP TIME_WAIT connections: ${TIME_WAIT_VALUE}"
                    echo -e "${YELLOW}  Consider adjusting tcp_tw_reuse and tcp_fin_timeout kernel parameters for ${component_name}.${NC}"
                fi
            else
                 echo "  No TCP connection data for ${component_name}."
            fi
            
            # Extract socket connection data for the component.
            SOCKET_CONNECTIONS_RAW=$(echo "${RESULT}" | jq -r --arg component_arg "$component_name" --arg metric_arg "socket_connections" \
                '[.[] | select(.Component == $component_arg and .MetricName == $metric_arg) | {state: .ConnectionState, avg: .AvgValue, max: .MaxValue}]')
            
            if [ -n "${SOCKET_CONNECTIONS_RAW}" ] && [ "${SOCKET_CONNECTIONS_RAW}" != "[]" ]; then
                echo -e "\n  Socket Connections:" # Added newline for separation from TCP section
                # Format and print socket connection states, average, and max values.
                echo "${SOCKET_CONNECTIONS_RAW}" | jq -r '.[] | "    State: \(.state) | Average Sockets: \(.avg) | Maximum Sockets: \(.max)"'
            else
                echo "  No Socket connection data for ${component_name}."
            fi
        done
    else
        echo "No connection metrics available." # This case should be covered by the initial check of RESULT
    fi
    echo "" # Add a newline for spacing
}

# generate_recommendations
# Generates optimization recommendations based on the collected FD and connection metrics.
# Implicitly uses global variables: COMPONENT, TIME_RANGE, WORKSPACE_ID.
generate_recommendations() {
    log "Generating file descriptor optimization recommendations..."
    
    echo -e "\nFile Descriptor Optimization Recommendations:"
    echo "-------------------------------------------"
    
    # Build KQL filter part for component if not 'all'.
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # KQL query for main FD usage ('file_descriptors') and FD limits ('file_descriptor_limit')
    # used as a basis for several recommendations.
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName in ('file_descriptors', 'file_descriptor_limit')
    ${COMPONENT_FILTER}
    | summarize 
        AvgValue = avg(MetricValue),
        MaxValue = max(MetricValue)
        by Component, MetricName
    | order by Component asc, MetricName asc
    "
    
    # Execute query
    RESULT_MAIN_METRICS=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    AZ_EXIT_STATUS_MAIN=$?

    if [ ${AZ_EXIT_STATUS_MAIN} -ne 0 ]; then
        warn "Failed to retrieve main metrics for recommendations. Azure CLI exited with status ${AZ_EXIT_STATUS_MAIN}."
        if [[ -n "$RESULT_MAIN_METRICS" ]]; then warn "Azure CLI output: $RESULT_MAIN_METRICS"; fi
        return
    fi

    if ! echo "$RESULT_MAIN_METRICS" | jq . > /dev/null 2>&1; then
        warn "No data returned or invalid JSON format for main recommendation metrics. Raw output: $RESULT_MAIN_METRICS"
        return
    fi

    if [[ -z "$RESULT_MAIN_METRICS" || "$RESULT_MAIN_METRICS" == "null" || "$RESULT_MAIN_METRICS" == "[]" ]]; then
        echo "No main metrics data to generate recommendations."
        return
    fi
    
    # Get unique component names from the main metrics results
    COMPONENTS_FOR_REC=$(echo "${RESULT_MAIN_METRICS}" | jq -r '.[].Component' | sort | uniq)
    
    if [ -z "$COMPONENTS_FOR_REC" ]; then
        echo "No components found from main metrics to generate recommendations for."
        return
    fi

    for component_name in ${COMPONENTS_FOR_REC}; do # Loop through each component for recommendations
        echo -e "\nRecommendations for Component: ${component_name}"
        echo "---------------------------------------"
        REC_COUNT=0 # Counter for recommendations for the current component

        # Extract Max FD usage for the component from the main metrics result (already fetched).
        # Used for utilization-based recommendation.
        FD_USAGE_REC=$(echo "${RESULT_MAIN_METRICS}" | jq -r --arg component_arg "$component_name" --arg metric_arg "file_descriptors" \
            '.[] | select(.Component == $component_arg and .MetricName == $metric_arg) | .MaxValue')
        
        # Extract Average FD limit for the component from the main metrics result.
        FD_LIMIT_REC=$(echo "${RESULT_MAIN_METRICS}" | jq -r --arg component_arg "$component_name" --arg metric_arg "file_descriptor_limit" \
            '.[] | select(.Component == $component_arg and .MetricName == $metric_arg) | .AvgValue')
        
        # Recommendation 1: Based on FD Utilization
        if [ -n "${FD_USAGE_REC}" ] && [ -n "${FD_LIMIT_REC}" ] && [ "${FD_USAGE_REC}" != "null" ] && [ "${FD_LIMIT_REC}" != "null" ]; then
            # Calculate utilization percentage.
            UTILIZATION_REC=$(echo "scale=2; ${FD_USAGE_REC} / ${FD_LIMIT_REC} * 100" | bc)
            # Format FD usage and limit as integers for display purposes using printf.
            FD_USAGE_REC_INT=$(printf "%.0f" "${FD_USAGE_REC}") 
            FD_LIMIT_REC_INT=$(printf "%.0f" "${FD_LIMIT_REC}")

            if (( $(echo "${UTILIZATION_REC} > 70" | bc -l) )); then # If utilization is over 70%
                REC_COUNT=$((REC_COUNT + 1))
                echo "${REC_COUNT}. Increase file descriptor limit."
                echo "   - Reason: High utilization detected (${UTILIZATION_REC}%). Max observed usage: ~${FD_USAGE_REC_INT}, Current limit: ~${FD_LIMIT_REC_INT}."
                echo "   - Action (example for systemd): Add/Modify 'LimitNOFILE=NEW_LIMIT' in the service file (e.g., NEW_LIMIT=65536)."
                echo "   - Action (example for containers): Use '--ulimit nofile=NEW_LIMIT:NEW_LIMIT' when starting the container."
            else
                echo "File descriptor utilization (${UTILIZATION_REC}%) is within acceptable limits (Max usage: ~${FD_USAGE_REC_INT}, Limit: ~${FD_LIMIT_REC_INT}). No change to limit recommended based on this."
            fi
        else
            warn "Could not determine FD usage or limit for ${component_name} from main metrics to generate utilization-based recommendation."
        fi
        
        # KQL Query for connection metrics (specifically TIME_WAIT state) for the current component.
        # This is a separate query per component within the loop.
        CONN_QUERY="
        let timeRange = ${TIME_RANGE};
        Metrics
        | where TimeGenerated > ago(timeRange)
        | where MetricName == 'tcp_connections'
        | where Component == '${component_name}'
        | summarize AvgValue = avg(MetricValue) by ConnectionState
        "
        
        CONN_RESULT=$(az monitor log-analytics query \
            --workspace "${WORKSPACE_ID}" \
            --analytics-query "${CONN_QUERY}" \
            --output json)
        AZ_EXIT_STATUS_CONN=$?

        if [ ${AZ_EXIT_STATUS_CONN} -ne 0 ]; then
            warn "Failed to retrieve connection metrics for recommendations (component: ${component_name}). Azure CLI exited with status ${AZ_EXIT_STATUS_CONN}."
            if [[ -n "$CONN_RESULT" ]]; then warn "Azure CLI output: $CONN_RESULT"; fi
        elif ! echo "$CONN_RESULT" | jq . > /dev/null 2>&1; then
            warn "No data returned or invalid JSON format for connection recommendation metrics (component: ${component_name}). Raw output: $CONN_RESULT"
        elif [[ -n "$CONN_RESULT" && "$CONN_RESULT" != "null" && "$CONN_RESULT" != "[]" ]]; then
            TIME_WAIT_VALUE_REC=$(echo "${CONN_RESULT}" | jq -r --arg state_arg "TIME_WAIT" \
                '.[] | select(.ConnectionState == $state_arg) | .AvgValue') # Renamed jq arg
            
            # Extract average TIME_WAIT connections from the result of CONN_QUERY.
            TIME_WAIT_VALUE_REC=$(echo "${CONN_RESULT}" | jq -r --arg state_arg "TIME_WAIT" \
                '.[] | select(.ConnectionState == $state_arg) | .AvgValue')
            
            if [ -n "${TIME_WAIT_VALUE_REC}" ] && [ "${TIME_WAIT_VALUE_REC}" != "null" ] && (( $(echo "${TIME_WAIT_VALUE_REC} > 1000" | bc -l) )); then # If avg TIME_WAIT > 1000
                REC_COUNT=$((REC_COUNT + 1))
                TIME_WAIT_VALUE_REC_INT=$(printf "%.0f" "${TIME_WAIT_VALUE_REC}") # Format as integer for display.
                echo "${REC_COUNT}. Optimize TCP connection handling."
                echo "   - Reason: High number of TCP TIME_WAIT connections detected (~${TIME_WAIT_VALUE_REC_INT})."
                echo "   - Action: Enable 'tcp_tw_reuse' (e.g., 'sudo sysctl -w net.ipv4.tcp_tw_reuse=1')."
                echo "   - Action: Consider reducing 'tcp_fin_timeout' (e.g., 'sudo sysctl -w net.ipv4.tcp_fin_timeout=30'). Make this change cautiously."
            else
                echo "TCP TIME_WAIT connections appear to be within acceptable limits for ${component_name}. No specific TCP optimization recommended based on this."
            fi
        else
            warn "No connection data found for ${component_name} to generate TCP-related recommendations."
        fi
        
        # KQL Query for FD trend analysis for the current component (24h, 1h interval).
        # This is another separate query per component.
        FD_TREND_QUERY="
        let timeRange = 24h;
        let interval = 1h;
        Metrics
        | where TimeGenerated > ago(timeRange)
        | where MetricName == 'file_descriptors'
        | where Component == '${component_name}'
        | summarize 
            AvgFD = avg(MetricValue)
            by bin(TimeGenerated, interval)
        | order by TimeGenerated asc
        "
        
        FD_TREND_RESULT=$(az monitor log-analytics query \
            --workspace "${WORKSPACE_ID}" \
            --analytics-query "${FD_TREND_QUERY}" \
            --output json)
        AZ_EXIT_STATUS_TREND=$?

        if [ ${AZ_EXIT_STATUS_TREND} -ne 0 ]; then
            warn "Failed to retrieve FD trend metrics for recommendations (component: ${component_name}). Azure CLI exited with status ${AZ_EXIT_STATUS_TREND}."
            if [[ -n "$FD_TREND_RESULT" ]]; then warn "Azure CLI output: $FD_TREND_RESULT"; fi
        elif ! echo "$FD_TREND_RESULT" | jq . > /dev/null 2>&1; then
            warn "No data returned or invalid JSON format for FD trend recommendation metrics (component: ${component_name}). Raw output: $FD_TREND_RESULT"
        elif [[ -n "$FD_TREND_RESULT" && "$FD_TREND_RESULT" != "null" && "$FD_TREND_RESULT" != "[]" ]]; then
            FD_TREND_COUNT_REC=$(echo "${FD_TREND_RESULT}" | jq 'length') # Renamed
            
            FD_TREND_COUNT_REC=$(echo "${FD_TREND_RESULT}" | jq 'length') # Number of data points in the trend.
            
            if [ "${FD_TREND_COUNT_REC}" -gt 3 ]; then # Only analyze if there are enough data points (more than 3 intervals).
                INCREASES_REC=0      # Counter for increases.
                PREVIOUS_FD_REC=""   # Previous FD value.
                
                # Iterate over average FD values to count consistent increases.
                for value_rec in $(echo "${FD_TREND_RESULT}" | jq -r '.[].AvgFD'); do
                    if [ -n "${PREVIOUS_FD_REC}" ] && [ "$value_rec" != "null" ] && [ "${PREVIOUS_FD_REC}" != "null" ] && (( $(echo "${value_rec} > ${PREVIOUS_FD_REC}" | bc -l) )); then
                        INCREASES_REC=$((INCREASES_REC + 1))
                    fi
                    PREVIOUS_FD_REC="${value_rec}"
                done
                
                # Calculate 80% threshold for number of increases.
                THRESHOLD_REC=$(echo "scale=0; ${FD_TREND_COUNT_REC} * 0.8 / 1" | bc) # Integer part.
                if [ "${INCREASES_REC}" -ge "${THRESHOLD_REC}" ] && [ "${THRESHOLD_REC}" -gt 0 ]; then # If increases meet or exceed threshold.
                    REC_COUNT=$((REC_COUNT + 1))
                    echo "${REC_COUNT}. Investigate potential file descriptor leak."
                    echo "   - Reason: FD count for ${component_name} showed a consistent increase over ${INCREASES_REC}/${FD_TREND_COUNT_REC} intervals (1h each)."
                    echo "   - Action: Profile the application to identify where file descriptors are being opened and not closed."
                    echo "   - Action: Check for resource leaks in loops, error handling paths, and connection/client library usage."
                    echo "   - Action: Verify connection pool configurations and ensure they are correctly releasing resources."
                else
                    echo "FD trend analysis does not indicate a consistent leak for ${component_name}. No specific leak investigation recommended based on this."
                fi
            else
                 echo "Not enough FD trend data (requires >3 1h intervals) to analyze for potential leaks in ${component_name}."
            fi
        else
            warn "No FD trend data found for ${component_name} to generate leak-related recommendations."
        fi

        # If no recommendations were made for the component after all checks.
        if [ ${REC_COUNT} -eq 0 ]; then
            echo "No specific optimization recommendations for ${component_name} at this time based on available data."
        fi
    done
    echo "" # Add a newline for spacing
}

# main
# Main function to orchestrate the script's operations:
# 1. Logs start of analysis, including environment, component, and time range.
# 2. Calls functions to check FD usage, limits, trends, and connection FDs.
# 3. Calls function to generate recommendations.
# 4. Logs completion of analysis.
# Implicitly uses global variables: ENV, COMPONENT, TIME_RANGE (used in log messages).
main() {
    log "Starting file descriptor analysis for environment: ${ENV}, component: ${COMPONENT}, time range: ${TIME_RANGE}"
    
    check_fd_usage
    check_fd_limits
    analyze_fd_trends
    check_connection_fds
    generate_recommendations
    
    log "File descriptor analysis completed for environment: ${ENV}"
}

# Execute main function
main