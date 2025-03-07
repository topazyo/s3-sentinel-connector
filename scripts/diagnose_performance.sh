#!/bin/bash
# scripts/diagnose_performance.sh

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

success() {
    echo -e "${GREEN}✓ $1${NC}"
}

failure() {
    echo -e "${RED}✗ $1${NC}"
}

# Diagnose processing latency
diagnose_processing_latency() {
    log "Diagnosing processing latency..."
    
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
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Processing Latency (seconds):"
    echo "----------------------------"
    echo "${RESULT}" | jq -r '.[] | "\(.TimeGenerated) | \(.Component) | Avg: \(.AvgLatency), Max: \(.MaxLatency), P95: \(.P95Latency), StdDev: \(.StdDevLatency)"'
    
    # Analyze latency patterns
    log "Analyzing latency patterns..."
    
    # Calculate average latency by component
    AVG_BY_COMPONENT=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map({Component: .[0].Component, AvgLatency: (map(.AvgLatency) | add / length)}) | .[]')
    
    echo "Average Latency by Component:"
    echo "${AVG_BY_COMPONENT}" | jq -r '"\(.Component): \(.AvgLatency)s"'
    
    # Identify latency spikes
    LATENCY_SPIKES=$(echo "${RESULT}" | jq -r '.[] | select(.MaxLatency > (.AvgLatency * 3)) | "\(.TimeGenerated) | \(.Component): Spike from \(.AvgLatency)s to \(.MaxLatency)s"')
    
    if [ -n "${LATENCY_SPIKES}" ]; then
        echo "Latency Spikes Detected:"
        echo "${LATENCY_SPIKES}"
    else
        echo "No significant latency spikes detected"
    fi
    
    # Check for latency trends
    log "Checking for latency trends..."
    
    # This would require more complex analysis, simplified for the script
    FIRST_RECORDS=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map({Component: .[0].Component, FirstAvg: .[0].AvgLatency}) | .[]')
    LAST_RECORDS=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map({Component: .[0].Component, LastAvg: .[-1].AvgLatency}) | .[]')
    
    echo "Latency Trends:"
    for component in $(echo "${FIRST_RECORDS}" | jq -r '.Component'); do
        FIRST=$(echo "${FIRST_RECORDS}" | jq -r "select(.Component == \"${component}\") | .FirstAvg")
        LAST=$(echo "${LAST_RECORDS}" | jq -r "select(.Component == \"${component}\") | .LastAvg")
        
        if (( $(echo "${LAST} > ${FIRST} * 1.2" | bc -l) )); then
            warn "Increasing latency trend for ${component}: ${FIRST}s -> ${LAST}s"
        elif (( $(echo "${LAST} < ${FIRST} * 0.8" | bc -l) )); then
            success "Decreasing latency trend for ${component}: ${FIRST}s -> ${LAST}s"
        else
            echo "Stable latency for ${component}: ${FIRST}s -> ${LAST}s"
        fi
    done
}

# Diagnose throughput
diagnose_throughput() {
    log "Diagnosing throughput..."
    
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
    | where MetricName == 'logs_processed_count'
    ${COMPONENT_FILTER}
    | summarize 
        TotalLogs = sum(MetricValue),
        AvgLogsPerMin = avg(MetricValue)
        by bin(TimeGenerated, 5m), Component
    | order by TimeGenerated asc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Throughput (logs processed):"
    echo "--------------------------"
    echo "${RESULT}" | jq -r '.[] | "\(.TimeGenerated) | \(.Component) | Total: \(.TotalLogs), Avg/min: \(.AvgLogsPerMin)"'
    
    # Analyze throughput patterns
    log "Analyzing throughput patterns..."
    
    # Calculate average throughput by component
    AVG_BY_COMPONENT=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map({Component: .[0].Component, AvgThroughput: (map(.AvgLogsPerMin) | add / length)}) | .[]')
    
    echo "Average Throughput by Component (logs/min):"
    echo "${AVG_BY_COMPONENT}" | jq -r '"\(.Component): \(.AvgThroughput)"'
    
    # Identify throughput drops
    THROUGHPUT_DROPS=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map(sort_by(.TimeGenerated)) | .[] | . as $items | range(1; length) as $i | select($items[$i].AvgLogsPerMin < $items[$i-1].AvgLogsPerMin * 0.5) | "\($items[$i].TimeGenerated) | \($items[$i].Component): Drop from \($items[$i-1].AvgLogsPerMin) to \($items[$i].AvgLogsPerMin) logs/min"')
    
    if [ -n "${THROUGHPUT_DROPS}" ]; then
        echo "Throughput Drops Detected:"
        echo "${THROUGHPUT_DROPS}"
    else
        echo "No significant throughput drops detected"
    fi
    
    # Check for throughput trends
    log "Checking for throughput trends..."
    
    FIRST_RECORDS=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map({Component: .[0].Component, FirstAvg: .[0].AvgLogsPerMin}) | .[]')
    LAST_RECORDS=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map({Component: .[0].Component, LastAvg: .[-1].AvgLogsPerMin}) | .[]')
    
    echo "Throughput Trends:"
    for component in $(echo "${FIRST_RECORDS}" | jq -r '.Component'); do
        FIRST=$(echo "${FIRST_RECORDS}" | jq -r "select(.Component == \"${component}\") | .FirstAvg")
        LAST=$(echo "${LAST_RECORDS}" | jq -r "select(.Component == \"${component}\") | .LastAvg")
        
        if (( $(echo "${LAST} > ${FIRST} * 1.2" | bc -l) )); then
            success "Increasing throughput trend for ${component}: ${FIRST} -> ${LAST} logs/min"
        elif (( $(echo "${LAST} < ${FIRST} * 0.8" | bc -l) )); then
            warn "Decreasing throughput trend for ${component}: ${FIRST} -> ${LAST} logs/min"
        else
            echo "Stable throughput for ${component}: ${FIRST} -> ${LAST} logs/min"
        fi
    done
}

# Diagnose error rates
diagnose_error_rates() {
    log "Diagnosing error rates..."
    
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
    | where MetricName in ('error_count', 'logs_processed_count')
    ${COMPONENT_FILTER}
    | summarize 
        ErrorCount = sumif(MetricValue, MetricName == 'error_count'),
        ProcessedCount = sumif(MetricValue, MetricName == 'logs_processed_count')
        by bin(TimeGenerated, 5m), Component
    | extend 
        ErrorRate = iff(ProcessedCount > 0, ErrorCount / ProcessedCount, 0)
    | project
        TimeGenerated,
        Component,
        ErrorCount,
        ProcessedCount,
        ErrorRate
    | order by TimeGenerated asc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Error Rates:"
    echo "-----------"
    echo "${RESULT}" | jq -r '.[] | "\(.TimeGenerated) | \(.Component) | Errors: \(.ErrorCount), Processed: \(.ProcessedCount), Rate: \(.ErrorRate)"'
    
    # Analyze error patterns
    log "Analyzing error patterns..."
    
    # Calculate average error rate by component
    AVG_BY_COMPONENT=$(echo "${RESULT}" | jq -r 'group_by(.Component) | map({Component: .[0].Component, AvgErrorRate: (map(.ErrorRate) | add / length)}) | .[]')
    
    echo "Average Error Rate by Component:"
    echo "${AVG_BY_COMPONENT}" | jq -r '"\(.Component): \(.AvgErrorRate * 100)%"'
    
    # Identify error spikes
    ERROR_SPIKES=$(echo "${RESULT}" | jq -r '.[] | select(.ErrorRate > 0.1) | "\(.TimeGenerated) | \(.Component): Error rate \(.ErrorRate * 100)%"')
    
    if [ -n "${ERROR_SPIKES}" ]; then
        echo "Error Spikes Detected:"
        echo "${ERROR_SPIKES}"
    else
        echo "No significant error spikes detected"
    fi
    
    # Get error details
    log "Getting error details..."
    
    # Query error logs
    QUERY="
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
    
    # Execute query
    ERROR_DETAILS=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    echo "Top Error Types:"
    echo "${ERROR_DETAILS}" | jq -r '.[] | "\(.Component) | \(.ErrorType): \(.ErrorCount) occurrences"'
}

# Diagnose resource utilization
diagnose_resource_utilization() {
    log "Diagnosing resource utilization..."
    
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
    | where MetricName in ('cpu_percent', 'memory_percent', 'disk_io_percent')
    ${COMPONENT_FILTER}
    | summarize 
        AvgValue = avg(MetricValue),
        MaxValue = max(MetricValue),
        P95Value = percentile(MetricValue, 95)
        by bin(TimeGenerated, 5m), MetricName, Component
    | order by TimeGenerated asc, Component asc, MetricName asc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Resource Utilization:"
    echo "-------------------"
    echo "${RESULT}" | jq -r '.[] | "\(.TimeGenerated) | \(.Component) | \(.MetricName): Avg: \(.AvgValue)%, Max: \(.MaxValue)%, P95: \(.P95Value)%"'
    
    # Analyze resource constraints
    log "Analyzing resource constraints..."
    
    # Calculate average utilization by component and metric
    AVG_BY_COMPONENT=$(echo "${RESULT}" | jq -r 'group_by(.Component, .MetricName) | map({Component: .[0].Component, MetricName: .[0].MetricName, AvgValue: (map(.AvgValue) | add / length), MaxValue: (map(.MaxValue) | max)}) | .[]')
    
    echo "Average Resource Utilization by Component:"
    echo "${AVG_BY_COMPONENT}" | jq -r '"\(.Component) | \(.MetricName): Avg: \(.AvgValue)%, Max: \(.MaxValue)%"'
    
    # Identify resource constraints
    CPU_CONSTRAINTS=$(echo "${AVG_BY_COMPONENT}" | jq -r 'select(.MetricName == "cpu_percent" and .AvgValue > 70) | "\(.Component): \(.AvgValue)% average CPU usage"')
    MEMORY_CONSTRAINTS=$(echo "${AVG_BY_COMPONENT}" | jq -r 'select(.MetricName == "memory_percent" and .AvgValue > 80) | "\(.Component): \(.AvgValue)% average memory usage"')
    DISK_CONSTRAINTS=$(echo "${AVG_BY_COMPONENT}" | jq -r 'select(.MetricName == "disk_io_percent" and .AvgValue > 60) | "\(.Component): \(.AvgValue)% average disk I/O usage"')
    
    echo "Resource Constraints:"
    if [ -n "${CPU_CONSTRAINTS}" ]; then
        echo "CPU Constraints:"
        echo "${CPU_CONSTRAINTS}"
    fi
    
    if [ -n "${MEMORY_CONSTRAINTS}" ]; then
        echo "Memory Constraints:"
        echo "${MEMORY_CONSTRAINTS}"
    fi
    
    if [ -n "${DISK_CONSTRAINTS}" ]; then
        echo "Disk I/O Constraints:"
        echo "${DISK_CONSTRAINTS}"
    fi
    
    if [ -z "${CPU_CONSTRAINTS}" ] && [ -z "${MEMORY_CONSTRAINTS}" ] && [ -z "${DISK_CONSTRAINTS}" ]; then
        echo "No significant resource constraints detected"
    fi
}

# Generate recommendations
generate_recommendations() {
    log "Generating performance recommendations..."
    
    echo "Performance Recommendations:"
    echo "--------------------------"
    
    # Check for high CPU usage
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'cpu_percent'
    | summarize AvgCPU = avg(MetricValue) by Component
    | where AvgCPU > 70
    "
    
    CPU_RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    if [ "$(echo "${CPU_RESULT}" | jq 'length')" -gt 0 ]; then
        echo "1. Consider scaling up CPU resources for the following components:"
        echo "${CPU_RESULT}" | jq -r '.[] | "   - \(.Component): \(.AvgCPU)% average CPU usage"'
    fi
    
    # Check for memory constraints
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'memory_percent'
    | summarize AvgMemory = avg(MetricValue) by Component
    | where AvgMemory > 70
    "
    
    MEMORY_RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    if [ "$(echo "${MEMORY_RESULT}" | jq 'length')" -gt 0 ]; then
        echo "2. Consider increasing memory allocation for the following components:"
        echo "${MEMORY_RESULT}" | jq -r '.[] | "   - \(.Component): \(.AvgMemory)% average memory usage"'
    fi
    
    # Check for high latency
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'processing_latency_seconds'
    | summarize AvgLatency = avg(MetricValue) by Component
    | where AvgLatency > 30
    "
    
    LATENCY_RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    if [ "$(echo "${LATENCY_RESULT}" | jq 'length')" -gt 0 ]; then
        echo "3. Optimize processing latency for the following components:"
        echo "${LATENCY_RESULT}" | jq -r '.[] | "   - \(.Component): \(.AvgLatency)s average latency"'
    fi
    
    # Check for batch size optimization
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'batch_processing_rate'
    | summarize AvgRate = avg(MetricValue) by Component, BatchSize
    | order by Component asc, AvgRate desc
    "
    
    BATCH_RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    if [ "$(echo "${BATCH_RESULT}" | jq 'length')" -gt 0 ]; then
        echo "4. Batch size optimization recommendations:"
        echo "${BATCH_RESULT}" | jq -r 'group_by(.Component) | map({Component: .[0].Component, OptimalBatchSize: max_by(.AvgRate).BatchSize, MaxRate: max_by(.AvgRate).AvgRate}) | .[] | "   - \(.Component): Optimal batch size = \(.OptimalBatchSize) (processing rate: \(.MaxRate) items/sec)"'
    fi
    
    # Check for error rates
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName in ('error_count', 'logs_processed_count')
    | summarize 
        ErrorCount = sumif(MetricValue, MetricName == 'error_count'),
        ProcessedCount = sumif(MetricValue, MetricName == 'logs_processed_count')
        by Component
    | extend 
        ErrorRate = iff(ProcessedCount > 0, ErrorCount / ProcessedCount, 0)
    | where ErrorRate > 0.01
    "
    
    ERROR_RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    if [ "$(echo "${ERROR_RESULT}" | jq 'length')" -gt 0 ]; then
        echo "5. Address high error rates in the following components:"
        echo "${ERROR_RESULT}" | jq -r '.[] | "   - \(.Component): \(.ErrorRate * 100)% error rate (\(.ErrorCount) errors out of \(.ProcessedCount) processed)"'
    fi
}

# Main function
main() {
    log "Starting performance diagnostics for environment: ${ENV}"
    
    # Diagnose processing latency
    diagnose_processing_latency
    
    # Diagnose throughput
    diagnose_throughput
    
    # Diagnose error rates
    diagnose_error_rates
    
    # Diagnose resource utilization
    diagnose_resource_utilization
    
    # Generate recommendations
    generate_recommendations
    
    log "Performance diagnostics completed"
}

# Execute main function
main