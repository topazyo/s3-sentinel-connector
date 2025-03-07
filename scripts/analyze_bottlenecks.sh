#!/bin/bash
# scripts/analyze_bottlenecks.sh

set -e

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV=${1:-"prod"}
TIME_RANGE=${2:-"1h"}

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

# Analyze component performance
analyze_component_performance() {
    log "Analyzing component performance..."
    
    # Query metrics from Azure Monitor
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName in ('processing_latency_seconds', 'queue_length', 'error_rate')
    | summarize 
        AvgValue = avg(MetricValue),
        MaxValue = max(MetricValue)
        by MetricName, Component
    | order by Component asc, MetricName asc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Component Performance Analysis:"
    echo "------------------------------"
    echo "${RESULT}" | jq -r '.[] | "\(.Component) | \(.MetricName): Avg=\(.AvgValue), Max=\(.MaxValue)"'
    
    # Identify potential bottlenecks
    echo -e "\nPotential Bottlenecks:"
    echo "---------------------"
    
    # Check for high latency components
    HIGH_LATENCY=$(echo "${RESULT}" | jq -r '.[] | select(.MetricName == "processing_latency_seconds" and .AvgValue > 30) | "\(.Component): \(.AvgValue)s"')
    if [ -n "${HIGH_LATENCY}" ]; then
        echo "High Latency Components:"
        echo "${HIGH_LATENCY}"
    fi
    
    # Check for components with long queues
    LONG_QUEUES=$(echo "${RESULT}" | jq -r '.[] | select(.MetricName == "queue_length" and .AvgValue > 1000) | "\(.Component): \(.AvgValue) items"')
    if [ -n "${LONG_QUEUES}" ]; then
        echo -e "\nComponents with Long Queues:"
        echo "${LONG_QUEUES}"
    fi
    
    # Check for components with high error rates
    HIGH_ERROR_RATES=$(echo "${RESULT}" | jq -r '.[] | select(.MetricName == "error_rate" and .AvgValue > 0.01) | "\(.Component): \(.AvgValue*100)%"')
    if [ -n "${HIGH_ERROR_RATES}" ]; then
        echo -e "\nComponents with High Error Rates:"
        echo "${HIGH_ERROR_RATES}"
    fi
}

# Analyze resource utilization
analyze_resource_utilization() {
    log "Analyzing resource utilization..."
    
    # Query metrics from Azure Monitor
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName in ('cpu_percent', 'memory_percent', 'disk_io_percent')
    | summarize 
        AvgValue = avg(MetricValue),
        MaxValue = max(MetricValue),
        P95Value = percentile(MetricValue, 95)
        by MetricName, Component
    | order by Component asc, MetricName asc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Resource Utilization Analysis:"
    echo "-----------------------------"
    echo "${RESULT}" | jq -r '.[] | "\(.Component) | \(.MetricName): Avg=\(.AvgValue)%, Max=\(.MaxValue)%, P95=\(.P95Value)%"'
    
    # Identify resource constraints
    echo -e "\nPotential Resource Constraints:"
    echo "------------------------------"
    
    # Check for CPU constraints
    HIGH_CPU=$(echo "${RESULT}" | jq -r '.[] | select(.MetricName == "cpu_percent" and .P95Value > 80) | "\(.Component): \(.P95Value)%"')
    if [ -n "${HIGH_CPU}" ]; then
        echo "High CPU Utilization:"
        echo "${HIGH_CPU}"
    fi
    
    # Check for memory constraints
    HIGH_MEMORY=$(echo "${RESULT}" | jq -r '.[] | select(.MetricName == "memory_percent" and .P95Value > 80) | "\(.Component): \(.P95Value)%"')
    if [ -n "${HIGH_MEMORY}" ]; then
        echo -e "\nHigh Memory Utilization:"
        echo "${HIGH_MEMORY}"
    fi
    
    # Check for disk I/O constraints
    HIGH_DISK_IO=$(echo "${RESULT}" | jq -r '.[] | select(.MetricName == "disk_io_percent" and .P95Value > 70) | "\(.Component): \(.P95Value)%"')
    if [ -n "${HIGH_DISK_IO}" ]; then
        echo -e "\nHigh Disk I/O Utilization:"
        echo "${HIGH_DISK_IO}"
    fi
}

# Analyze network performance
analyze_network_performance() {
    log "Analyzing network performance..."
    
    # Query metrics from Azure Monitor
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName in ('network_latency_ms', 'network_throughput_bytes', 'connection_errors')
    | summarize 
        AvgValue = avg(MetricValue),
        MaxValue = max(MetricValue)
        by MetricName, Component, Endpoint
    | order by Component asc, Endpoint asc, MetricName asc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Network Performance Analysis:"
    echo "----------------------------"
    echo "${RESULT}" | jq -r '.[] | "\(.Component) -> \(.Endpoint) | \(.MetricName): Avg=\(.AvgValue), Max=\(.MaxValue)"'
    
    # Identify network issues
    echo -e "\nPotential Network Issues:"
    echo "-------------------------"
    
    # Check for high network latency
    HIGH_LATENCY=$(echo "${RESULT}" | jq -r '.[] | select(.MetricName == "network_latency_ms" and .AvgValue > 200) | "\(.Component) -> \(.Endpoint): \(.AvgValue)ms"')
    if [ -n "${HIGH_LATENCY}" ]; then
        echo "High Network Latency:"
        echo "${HIGH_LATENCY}"
    fi
    
    # Check for connection errors
    CONNECTION_ERRORS=$(echo "${RESULT}" | jq -r '.[] | select(.MetricName == "connection_errors" and .AvgValue > 0) | "\(.Component) -> \(.Endpoint): \(.AvgValue) errors"')
    if [ -n "${CONNECTION_ERRORS}" ]; then
        echo -e "\nConnection Errors:"
        echo "${CONNECTION_ERRORS}"
    fi
}

# Generate recommendations
generate_recommendations() {
    log "Generating recommendations..."
    
    echo "Recommendations:"
    echo "---------------"
    
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
    
    echo "3. Batch size optimization recommendations:"
    echo "${BATCH_RESULT}" | jq -r 'group_by(.Component) | map({Component: .[0].Component, OptimalBatchSize: max_by(.AvgRate).BatchSize, MaxRate: max_by(.AvgRate).AvgRate}) | .[] | "   - \(.Component): Optimal batch size = \(.OptimalBatchSize) (processing rate: \(.MaxRate) items/sec)"'
}

# Main function
main() {
    log "Starting bottleneck analysis for environment: ${ENV}"
    
    # Analyze component performance
    analyze_component_performance
    
    # Analyze resource utilization
    analyze_resource_utilization
    
    # Analyze network performance
    analyze_network_performance
    
    # Generate recommendations
    generate_recommendations
    
    log "Bottleneck analysis completed"
}

# Execute main function
main