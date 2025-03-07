#!/bin/bash
# scripts/check_resources.sh

set -e

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV=${1:-"prod"}
COMPONENT=${2:-"all"}

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

# Check CPU usage
check_cpu_usage() {
    log "Checking CPU usage..."
    
    # Build component filter
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # Query metrics from Azure Monitor
    QUERY="
    let timeRange = 1h;
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'cpu_percent'
    ${COMPONENT_FILTER}
    | summarize 
        AvgCPU = avg(MetricValue),
        MaxCPU = max(MetricValue),
        P95CPU = percentile(MetricValue, 95)
        by Component
    | order by AvgCPU desc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "CPU Usage (%):"
    echo "-------------"
    echo "${RESULT}" | jq -r '.[] | "\(.Component) | Avg: \(.AvgCPU)%, Max: \(.MaxCPU)%, P95: \(.P95CPU)%"'
    
    # Check for high CPU usage
    HIGH_CPU=$(echo "${RESULT}" | jq -r '.[] | select(.P95CPU > 80) | "\(.Component): \(.P95CPU)%"')
    if [ -n "${HIGH_CPU}" ]; then
        warn "High CPU usage detected:"
        echo "${HIGH_CPU}"
    fi
}

# Check memory usage
check_memory_usage() {
    log "Checking memory usage..."
    
    # Build component filter
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # Query metrics from Azure Monitor
    QUERY="
    let timeRange = 1h;
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'memory_percent'
    ${COMPONENT_FILTER}
    | summarize 
        AvgMemory = avg(MetricValue),
        MaxMemory = max(MetricValue),
        P95Memory = percentile(MetricValue, 95)
        by Component
    | order by AvgMemory desc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Memory Usage (%):"
    echo "---------------"
    echo "${RESULT}" | jq -r '.[] | "\(.Component) | Avg: \(.AvgMemory)%, Max: \(.MaxMemory)%, P95: \(.P95Memory)%"'
    
    # Check for high memory usage
    HIGH_MEMORY=$(echo "${RESULT}" | jq -r '.[] | select(.P95Memory > 80) | "\(.Component): \(.P95Memory)%"')
    if [ -n "${HIGH_MEMORY}" ]; then
        warn "High memory usage detected:"
        echo "${HIGH_MEMORY}"
    fi
}

# Check disk usage
check_disk_usage() {
    log "Checking disk usage..."
    
    # Build component filter
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # Query metrics from Azure Monitor
    QUERY="
    let timeRange = 1h;
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName == 'disk_percent'
    ${COMPONENT_FILTER}
    | summarize 
        AvgDisk = avg(MetricValue),
        MaxDisk = max(MetricValue)
        by Component, DiskName
    | order by MaxDisk desc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Disk Usage (%):"
    echo "-------------"
    echo "${RESULT}" | jq -r '.[] | "\(.Component) | \(.DiskName) | Avg: \(.AvgDisk)%, Max: \(.MaxDisk)%"'
    
    # Check for high disk usage
    HIGH_DISK=$(echo "${RESULT}" | jq -r '.[] | select(.MaxDisk > 85) | "\(.Component) - \(.DiskName): \(.MaxDisk)%"')
    if [ -n "${HIGH_DISK}" ]; then
        warn "High disk usage detected:"
        echo "${HIGH_DISK}"
    fi
}

# Check network usage
check_network_usage() {
    log "Checking network usage..."
    
    # Build component filter
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # Query metrics from Azure Monitor
    QUERY="
    let timeRange = 1h;
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName in ('network_in_bytes', 'network_out_bytes')
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
    
    # Parse and display results
    echo "Network Usage:"
    echo "-------------"
    
    # Process network in
    NETWORK_IN=$(echo "${RESULT}" | jq -r '.[] | select(.MetricName == "network_in_bytes")')
    echo "Network In (bytes/sec):"
    echo "${NETWORK_IN}" | jq -r '.[] | "\(.Component) | Avg: \(.AvgValue), Max: \(.MaxValue)"'
    
    # Process network out
    NETWORK_OUT=$(echo "${RESULT}" | jq -r '.[] | select(.MetricName == "network_out_bytes")')
    echo -e "\nNetwork Out (bytes/sec):"
    echo "${NETWORK_OUT}" | jq -r '.[] | "\(.Component) | Avg: \(.AvgValue), Max: \(.MaxValue)"'
    
    # Check for high network usage
    HIGH_NETWORK=$(echo "${RESULT}" | jq -r '.[] | select(.MaxValue > 100000000) | "\(.Component) - \(.MetricName): \(.MaxValue) bytes/sec"')
    if [ -n "${HIGH_NETWORK}" ]; then
        warn "High network usage detected:"
        echo "${HIGH_NETWORK}"
    fi
}

# Check resource quotas
check_resource_quotas() {
    log "Checking resource quotas..."
    
    # Get AKS resource quotas
    if [ -n "${AKS_CLUSTER_NAME}" ] && [ -n "${RESOURCE_GROUP}" ]; then
        echo "AKS Resource Quotas:"
        echo "-------------------"
        
        # Get node resource usage
        az aks show \
            --resource-group "${RESOURCE_GROUP}" \
            --name "${AKS_CLUSTER_NAME}" \
            --query "agentPoolProfiles[].{Name:name, CurrentNodeCount:count, MaxNodeCount:maxCount, CPULimit:vmSize}" \
            --output table
            
        # Get pod resource usage
        NODES=$(az aks nodepool list \
            --resource-group "${RESOURCE_GROUP}" \
            --cluster-name "${AKS_CLUSTER_NAME}" \
            --query "[].name" \
            --output tsv)
            
        for node in ${NODES}; do
            echo -e "\nNode Pool: ${node}"
            kubectl top nodes | grep "${node}"
        done
    fi
    
    # Get Azure resource quotas
    echo -e "\nAzure Resource Quotas:"
    echo "---------------------"
    az vm list-usage --location "${LOCATION}" --output table
}

# Check resource trends
check_resource_trends() {
    log "Checking resource usage trends..."
    
    # Build component filter
    COMPONENT_FILTER=""
    if [ "${COMPONENT}" != "all" ]; then
        COMPONENT_FILTER="| where Component == '${COMPONENT}'"
    fi
    
    # Query metrics from Azure Monitor
    QUERY="
    let timeRange = 24h;
    Metrics
    | where TimeGenerated > ago(timeRange)
    | where MetricName in ('cpu_percent', 'memory_percent')
    ${COMPONENT_FILTER}
    | summarize 
        AvgValue = avg(MetricValue)
        by bin(TimeGenerated, 1h), Component, MetricName
    | order by TimeGenerated asc, Component asc, MetricName asc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Resource Usage Trends (24h):"
    echo "--------------------------"
    
    # Group by component and metric
    COMPONENTS=$(echo "${RESULT}" | jq -r '.[].Component' | sort | uniq)
    
    for component in ${COMPONENTS}; do
        echo -e "\nComponent: ${component}"
        
        # CPU trend
        echo "CPU Usage (%):"
        echo "${RESULT}" | jq -r --arg component "$component" --arg metric "cpu_percent" \
            '.[] | select(.Component == $component and .MetricName == $metric) | "\(.TimeGenerated): \(.AvgValue)%"'
        
        # Memory trend
        echo -e "\nMemory Usage (%):"
        echo "${RESULT}" | jq -r --arg component "$component" --arg metric "memory_percent" \
            '.[] | select(.Component == $component and .MetricName == $metric) | "\(.TimeGenerated): \(.AvgValue)%"'
    done
}

# Main function
main() {
    log "Starting resource check for environment: ${ENV}"
    
    # Check CPU usage
    check_cpu_usage
    
    # Check memory usage
    check_memory_usage
    
    # Check disk usage
    check_disk_usage
    
    # Check network usage
    check_network_usage
    
    # Check resource quotas
    check_resource_quotas
    
    # Check resource trends
    check_resource_trends
    
    log "Resource check completed"
}

# Execute main function
main