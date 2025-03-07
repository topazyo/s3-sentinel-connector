#!/bin/bash
# scripts/check_fd_usage.sh

set -e

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV=${1:-"prod"}
COMPONENT=${2:-"all"}
TIME_RANGE=${3:-"1h"}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Load environment variables
source "${SCRIPT_DIR}/env/${ENV}.env"

# Functions
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%dT%H:%M:%S%z')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%dT%H:%M:%S%z')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%dT%H:%M:%S%z')] ERROR: $1${NC}" >&2
}

# Check file descriptor usage
check_fd_usage() {
    log "Checking file descriptor usage..."
    
    # Build component filter
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # Query metrics from Azure Monitor
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
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "File Descriptor Usage:"
    echo "---------------------"
    echo "${RESULT}" | jq -r '.[] | "\(.Component) | Avg: \(.AvgFD), Max: \(.MaxFD), P95: \(.P95FD)"'
    
    # Check for high FD usage
    HIGH_FD=$(echo "${RESULT}" | jq -r '.[] | select(.P95FD > 1000) | "\(.Component): \(.P95FD)"')
    if [ -n "${HIGH_FD}" ]; then
        warn "High file descriptor usage detected:"
        echo "${HIGH_FD}"
    fi
}

# Check file descriptor limits
check_fd_limits() {
    log "Checking file descriptor limits..."
    
    # Build component filter
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # Query metrics from Azure Monitor
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
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "File Descriptor Limits:"
    echo "----------------------"
    
    # Group by component
    COMPONENTS=$(echo "${RESULT}" | jq -r '.[].Component' | sort | uniq)
    
    for component in ${COMPONENTS}; do
        echo -e "\nComponent: ${component}"
        
        # Get latest metrics
        LATEST_TIME=$(echo "${RESULT}" | jq -r --arg component "$component" \
            '.[] | select(.Component == $component) | .TimeGenerated' | sort | tail -n 1)
        
        # Get FD usage
        FD_USAGE=$(echo "${RESULT}" | jq -r --arg component "$component" --arg time "${LATEST_TIME}" --arg metric "file_descriptors" \
            '.[] | select(.Component == $component and .TimeGenerated == $time and .MetricName == $metric) | .AvgValue')
        
        # Get FD limit
        FD_LIMIT=$(echo "${RESULT}" | jq -r --arg component "$component" --arg time "${LATEST_TIME}" --arg metric "file_descriptor_limit" \
            '.[] | select(.Component == $component and .TimeGenerated == $time and .MetricName == $metric) | .AvgValue')
        
        if [ -n "${FD_USAGE}" ] && [ -n "${FD_LIMIT}" ] && [ "${FD_USAGE}" != "null" ] && [ "${FD_LIMIT}" != "null" ]; then
            # Calculate utilization
            UTILIZATION=$(echo "scale=2; ${FD_USAGE} / ${FD_LIMIT} * 100" | bc)
            
            echo "Current Usage: ${FD_USAGE}"
            echo "Limit: ${FD_LIMIT}"
            echo "Utilization: ${UTILIZATION}%"
            
            # Check for high utilization
            if (( $(echo "${UTILIZATION} > 80" | bc -l) )); then
                warn "High file descriptor utilization detected (${UTILIZATION}%)"
            fi
        else
            echo "Incomplete file descriptor metrics available"
        fi
    done
}

# Analyze file descriptor trends
analyze_fd_trends() {
    log "Analyzing file descriptor trends..."
    
    # Build component filter
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # Query metrics from Azure Monitor
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
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "File Descriptor Trends (24h):"
    echo "----------------------------"
    
    # Group by component
    COMPONENTS=$(echo "${RESULT}" | jq -r '.[].Component' | sort | uniq)
    
    for component in ${COMPONENTS}; do
        echo -e "\nComponent: ${component}"
        
        # Get FD trend
        FD_TREND=$(echo "${RESULT}" | jq -r --arg component "$component" \
            '[.[] | select(.Component == $component) | {time: .TimeGenerated, fd: .AvgFD}]')
        
        # Display trend
        echo "${FD_TREND}" | jq -r '.[] | "\(.time): \(.fd)"'
        
        # Check for consistent increase (potential leak)
        TREND_COUNT=$(echo "${FD_TREND}" | jq 'length')
        if [ "${TREND_COUNT}" -gt 3 ]; then
            # Check if FD consistently increases
            INCREASES=0
            PREVIOUS=""
            
            for value in $(echo "${FD_TREND}" | jq -r '.[].fd'); do
                if [ -n "${PREVIOUS}" ] && (( $(echo "${value} > ${PREVIOUS}" | bc -l) )); then
                    INCREASES=$((INCREASES + 1))
                fi
                PREVIOUS="${value}"
            done
            
            # If FD increased in at least 80% of intervals, flag as potential leak
            THRESHOLD=$(echo "scale=0; ${TREND_COUNT} * 0.8" | bc | cut -d. -f1)
            if [ "${INCREASES}" -ge "${THRESHOLD}" ]; then
                warn "Potential file descriptor leak detected in ${component} (consistent increase over ${INCREASES}/${TREND_COUNT} intervals)"
            fi
        fi
    done
}

# Check connection-related file descriptors
check_connection_fds() {
    log "Checking connection-related file descriptors..."
    
    # Build component filter
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # Query metrics from Azure Monitor
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
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Connection-Related File Descriptors:"
    echo "----------------------------------"
    
    # Check if connection metrics are available
    CONN_COUNT=$(echo "${RESULT}" | jq 'length')
    
    if [ "${CONN_COUNT}" -gt 0 ]; then
        # Group by component
        COMPONENTS=$(echo "${RESULT}" | jq -r '.[].Component' | sort | uniq)
        
        for component in ${COMPONENTS}; do
            echo -e "\nComponent: ${component}"
            
            # Get TCP connections
            TCP_CONNECTIONS=$(echo "${RESULT}" | jq -r --arg component "$component" --arg metric "tcp_connections" \
                '.[] | select(.Component == $component and .MetricName == $metric) | "\(.ConnectionState): \(.AvgValue) (max: \(.MaxValue))"')
            
            if [ -n "${TCP_CONNECTIONS}" ]; then
                echo "TCP Connections:"
                echo "${TCP_CONNECTIONS}"
                
                # Check for high number of TIME_WAIT connections
                TIME_WAIT=$(echo "${RESULT}" | jq -r --arg component "$component" --arg metric "tcp_connections" --arg state "TIME_WAIT" \
                    '.[] | select(.Component == $component and .MetricName == $metric and .ConnectionState == $state) | .AvgValue')
                
                if [ -n "${TIME_WAIT}" ] && [ "${TIME_WAIT}" != "null" ] && (( $(echo "${TIME_WAIT} > 1000" | bc -l) )); then
                    warn "High number of TIME_WAIT connections detected (${TIME_WAIT})"
                    echo "  Consider adjusting tcp_tw_reuse and tcp_fin_timeout kernel parameters"
                fi
            fi
            
            # Get socket connections
            SOCKET_CONNECTIONS=$(echo "${RESULT}" | jq -r --arg component "$component" --arg metric "socket_connections" \
                '.[] | select(.Component == $component and .MetricName == $metric) | "\(.ConnectionState): \(.AvgValue) (max: \(.MaxValue))"')
            
            if [ -n "${SOCKET_CONNECTIONS}" ]; then
                echo -e "\nSocket Connections:"
                echo "${SOCKET_CONNECTIONS}"
            fi
        done
    else
        echo "No connection metrics available"
    fi
}

# Generate recommendations
generate_recommendations() {
    log "Generating file descriptor optimization recommendations..."
    
    echo "File Descriptor Optimization Recommendations:"
    echo "-------------------------------------------"
    
    # Build component filter
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # Query metrics from Azure Monitor
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
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Group by component
    COMPONENTS=$(echo "${RESULT}" | jq -r '.[].Component' | sort | uniq)
    
    for component in ${COMPONENTS}; do
        # Get FD usage
        FD_USAGE=$(echo "${RESULT}" | jq -r --arg component "$component" --arg metric "file_descriptors" \
            '.[] | select(.Component == $component and .MetricName == $metric) | .MaxValue')
        
        # Get FD limit
        FD_LIMIT=$(echo "${RESULT}" | jq -r --arg component "$component" --arg metric "file_descriptor_limit" \
            '.[] | select(.Component == $component and .MetricName == $metric) | .AvgValue')
        
        # Generate recommendations
        echo -e "\nComponent: ${component}"
        
        if [ -n "${FD_USAGE}" ] && [ -n "${FD_LIMIT}" ] && [ "${FD_USAGE}" != "null" ] && [ "${FD_LIMIT}" != "null" ]; then
            # Calculate utilization
            UTILIZATION=$(echo "scale=2; ${FD_USAGE} / ${FD_LIMIT} * 100" | bc)
            
            if (( $(echo "${UTILIZATION} > 70" | bc -l) )); then
                echo "1. Increase file descriptor limit (current utilization: ${UTILIZATION}%)"
                echo "   - For systemd services: LimitNOFILE=65536 in service file"
                echo "   - For container: --ulimit nofile=65536:65536"
            fi
        fi
        
        # Check for connection metrics
        CONN_QUERY="
        let timeRange = ${TIME_RANGE};
        Metrics
        | where TimeGenerated > ago(timeRange)
        | where MetricName == 'tcp_connections'
        | where Component == '${component}'
        | summarize AvgValue = avg(MetricValue) by ConnectionState
        "
        
        CONN_RESULT=$(az monitor log-analytics query \
            --workspace "${WORKSPACE_ID}" \
            --analytics-query "${CONN_QUERY}" \
            --output json)
        
        TIME_WAIT=$(echo "${CONN_RESULT}" | jq -r --arg state "TIME_WAIT" \
            '.[] | select(.ConnectionState == $state) | .AvgValue')
        
        if [ -n "${TIME_WAIT}" ] && [ "${TIME_WAIT}" != "null" ] && (( $(echo "${TIME_WAIT} > 1000" | bc -l) )); then
            echo "2. Optimize TCP connection handling:"
            echo "   - Enable tcp_tw_reuse: sysctl -w net.ipv4.tcp_tw_reuse=1"
            echo "   - Reduce tcp_fin_timeout: sysctl -w net.ipv4.tcp_fin_timeout=30"
        fi
        
        # Check for potential FD leaks
        FD_TREND_QUERY="
        let timeRange = 24h;
        let interval = 1h;
        Metrics
        | where TimeGenerated > ago(timeRange)
        | where MetricName == 'file_descriptors'
        | where Component == '${component}'
        | summarize 
            AvgFD = avg(MetricValue)
            by bin(TimeGenerated, interval)
        | order by TimeGenerated asc
        "
        
        FD_TREND_RESULT=$(az monitor log-analytics query \
            --workspace "${WORKSPACE_ID}" \
            --analytics-query "${FD_TREND_QUERY}" \
            --output json)
        
        FD_TREND_COUNT=$(echo "${FD_TREND_RESULT}" | jq 'length')
        
        if [ "${FD_TREND_COUNT}" -gt 3 ]; then
            # Check if FD consistently increases
            INCREASES=0
            PREVIOUS=""
            
            for value in $(echo "${FD_TREND_RESULT}" | jq -r '.[].AvgFD'); do
                if [ -n "${PREVIOUS}" ] && (( $(echo "${value} > ${PREVIOUS}" | bc -l) )); then
                    INCREASES=$((INCREASES + 1))
                fi
                PREVIOUS="${value}"
            done
            
            # If FD increased in at least 80% of intervals, flag as potential leak
            THRESHOLD=$(echo "scale=0; ${FD_TREND_COUNT} * 0.8" | bc | cut -d. -f1)
            if [ "${INCREASES}" -ge "${THRESHOLD}" ]; then
                echo "3. Investigate potential file descriptor leak:"
                echo "   - Check for unclosed file handles"
                echo "   - Verify connection pool configurations"
                echo "   - Monitor resource cleanup in error paths"
            fi
        fi
    done
}

# Main function
main() {
    log "Starting file descriptor analysis for environment: ${ENV}"
    
    # Check file descriptor usage
    check_fd_usage
    
    # Check file descriptor limits
    check_fd_limits
    
    # Analyze file descriptor trends
    analyze_fd_trends
    
    # Check connection-related file descriptors
    check_connection_fds
    
    # Generate recommendations
    generate_recommendations
    
    log "File descriptor analysis completed"
}

# Execute main function
main