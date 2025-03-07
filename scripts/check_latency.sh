#!/bin/bash
# scripts/check_latency.sh

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

# Check processing latency
check_processing_latency() {
    log "Checking processing latency for the last ${TIME_RANGE}..."
    
    # Query metrics from Azure Monitor
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'processing_latency_seconds'
    | summarize 
        AvgLatency = avg(MetricValue),
        MaxLatency = max(MetricValue),
        P95Latency = percentile(MetricValue, 95)
        by bin(TimeGenerated, 5m), Component
    | order by TimeGenerated desc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Processing Latency (seconds):"
    echo "----------------------------"
    echo "${RESULT}" | jq -r '.[] | "\(.TimeGenerated) | \(.Component): Avg=\(.AvgLatency), Max=\(.MaxLatency), P95=\(.P95Latency)"' | head -n 20
    
    # Check for high latency
    MAX_LATENCY=$(echo "${RESULT}" | jq -r '[.[].MaxLatency] | max')
    if (( $(echo "${MAX_LATENCY} > 300" | bc -l) )); then
        warn "High maximum latency detected: ${MAX_LATENCY}s (threshold: 300s)"
    fi
    
    AVG_LATENCY=$(echo "${RESULT}" | jq -r '[.[].AvgLatency] | max')
    if (( $(echo "${AVG_LATENCY} > 60" | bc -l) )); then
        warn "High average latency detected: ${AVG_LATENCY}s (threshold: 60s)"
    fi
}

# Check component-specific latency
check_component_latency() {
    log "Checking component-specific latency..."
    
    # Query metrics from Azure Monitor
    QUERY="
    let timeRange = ${TIME_RANGE};
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'processing_latency_seconds'
    | summarize 
        AvgLatency = avg(MetricValue)
        by Component
    | order by AvgLatency desc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Component Latency Breakdown:"
    echo "---------------------------"
    echo "${RESULT}" | jq -r '.[] | "\(.Component): \(.AvgLatency)s"'
    
    # Identify slowest component
    SLOWEST_COMPONENT=$(echo "${RESULT}" | jq -r 'first | "\(.Component): \(.AvgLatency)s"')
    echo -e "\nSlowest component: ${SLOWEST_COMPONENT}"
}

# Check end-to-end latency
check_e2e_latency() {
    log "Checking end-to-end latency..."
    
    # Query logs from Azure Monitor
    QUERY="
    let timeRange = ${TIME_RANGE};
    LogEvents
    | where TimeGenerated > ago(timeRange)
    | where EventType == 'LogProcessed'
    | extend 
        IngestionTime = todatetime(tostring(Properties.ingestion_time)),
        ProcessingTime = todatetime(tostring(Properties.processing_time))
    | extend 
        E2ELatency = datetime_diff('second', ProcessingTime, IngestionTime)
    | summarize 
        AvgE2ELatency = avg(E2ELatency),
        MaxE2ELatency = max(E2ELatency),
        P95E2ELatency = percentile(E2ELatency, 95)
        by bin(TimeGenerated, 5m)
    | order by TimeGenerated desc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "End-to-End Latency (seconds):"
    echo "----------------------------"
    echo "${RESULT}" | jq -r '.[] | "\(.TimeGenerated) | Avg=\(.AvgE2ELatency), Max=\(.MaxE2ELatency), P95=\(.P95E2ELatency)"' | head -n 10
}

# Main function
main() {
    log "Starting latency check for environment: ${ENV}"
    
    # Check processing latency
    check_processing_latency
    
    # Check component-specific latency
    check_component_latency
    
    # Check end-to-end latency
    check_e2e_latency
    
    log "Latency check completed"
}

# Execute main function
main