#!/bin/bash
# scripts/analyze_memory.sh

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

# Analyze memory usage
analyze_memory_usage() {
    log "Analyzing memory usage..."
    
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
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Memory Usage Analysis:"
    echo "---------------------"
    echo "${RESULT}" | jq -r '.[] | "\(.Component) | Avg: \(.AvgMemory)%, Max: \(.MaxMemory)%, P95: \(.P95Memory)%, StdDev: \(.StdDevMemory)% (\(.MemoryStability))"'
    
    # Check for high memory usage
    HIGH_MEMORY=$(echo "${RESULT}" | jq -r '.[] | select(.P95Memory > 80) | "\(.Component): \(.P95Memory)%"')
    if [ -n "${HIGH_MEMORY}" ]; then
        warn "High memory usage detected:"
        echo "${HIGH_MEMORY}"
    fi
    
    # Check for volatile memory usage
    VOLATILE_MEMORY=$(echo "${RESULT}" | jq -r '.[] | select(.MemoryStability == "Volatile") | "\(.Component): StdDev \(.StdDevMemory)%"')
    if [ -n "${VOLATILE_MEMORY}" ]; then
        warn "Volatile memory usage detected:"
        echo "${VOLATILE_MEMORY}"
    fi
}

# Analyze memory allocation
analyze_memory_allocation() {
    log "Analyzing memory allocation..."
    
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
    | where MetricName in ('memory_allocated_bytes', 'memory_used_bytes')
    ${COMPONENT_FILTER}
    | summarize 
        AvgValue = avg(MetricValue)
        by Component, MetricName
    | extend MetricName = iff(MetricName == 'memory_allocated_bytes', 'Allocated', 'Used')
    | order by Component asc, MetricName asc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Memory Allocation (bytes):"
    echo "-------------------------"
    
    # Group by component
    COMPONENTS=$(echo "${RESULT}" | jq -r '.[].Component' | sort | uniq)
    
    for component in ${COMPONENTS}; do
        echo -e "\nComponent: ${component}"
        
        # Get allocated memory
        ALLOCATED=$(echo "${RESULT}" | jq -r --arg component "$component" --arg metric "Allocated" \
            '.[] | select(.Component == $component and .MetricName == $metric) | .AvgValue')
        
        # Get used memory
        USED=$(echo "${RESULT}" | jq -r --arg component "$component" --arg metric "Used" \
            '.[] | select(.Component == $component and .MetricName == $metric) | .AvgValue')
        
        # Calculate utilization
        if [ -n "${ALLOCATED}" ] && [ -n "${USED}" ] && [ "${ALLOCATED}" != "null" ] && [ "${USED}" != "null" ]; then
            UTILIZATION=$(echo "scale=2; ${USED} / ${ALLOCATED} * 100" | bc)
            
            # Convert to human-readable format
            ALLOCATED_HR=$(numfmt --to=iec --suffix=B ${ALLOCATED})
            USED_HR=$(numfmt --to=iec --suffix=B ${USED})
            
            echo "Allocated: ${ALLOCATED_HR}"
            echo "Used: ${USED_HR}"
            echo "Utilization: ${UTILIZATION}%"
            
            # Check for inefficient allocation
            if (( $(echo "${UTILIZATION} < 50" | bc -l) )); then
                warn "Inefficient memory allocation detected (${UTILIZATION}% utilization)"
            fi
        else
            echo "Incomplete memory metrics available"
        fi
    done
}

# Analyze memory leaks
analyze_memory_leaks() {
    log "Analyzing potential memory leaks..."
    
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
    | where MetricName == 'memory_used_bytes'
    ${COMPONENT_FILTER}
    | summarize 
        AvgMemory = avg(MetricValue)
        by bin(TimeGenerated, interval), Component
    | order by Component asc, TimeGenerated asc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Memory Usage Trend (24h):"
    echo "-----------------------"
    
    # Group by component
    COMPONENTS=$(echo "${RESULT}" | jq -r '.[].Component' | sort | uniq)
    
    for component in ${COMPONENTS}; do
        echo -e "\nComponent: ${component}"
        
        # Get memory trend
        MEMORY_TREND=$(echo "${RESULT}" | jq -r --arg component "$component" \
            '[.[] | select(.Component == $component) | {time: .TimeGenerated, memory: .AvgMemory}]')
        
        # Display trend
        echo "${MEMORY_TREND}" | jq -r '.[] | "\(.time): \(.memory | tostring | .[0:10]) bytes"'
        
        # Check for consistent increase (potential leak)
        TREND_COUNT=$(echo "${MEMORY_TREND}" | jq 'length')
        if [ "${TREND_COUNT}" -gt 3 ]; then
            # Check if memory consistently increases
            INCREASES=0
            PREVIOUS=""
            
            for value in $(echo "${MEMORY_TREND}" | jq -r '.[].memory'); do
                if [ -n "${PREVIOUS}" ] && (( $(echo "${value} > ${PREVIOUS}" | bc -l) )); then
                    INCREASES=$((INCREASES + 1))
                fi
                PREVIOUS="${value}"
            done
            
            # If memory increased in at least 80% of intervals, flag as potential leak
            THRESHOLD=$(echo "scale=0; ${TREND_COUNT} * 0.8" | bc | cut -d. -f1)
            if [ "${INCREASES}" -ge "${THRESHOLD}" ]; then
                warn "Potential memory leak detected in ${component} (consistent increase over ${INCREASES}/${TREND_COUNT} intervals)"
            fi
        fi
    done
}

# Analyze garbage collection
analyze_garbage_collection() {
    log "Analyzing garbage collection..."
    
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
    | where MetricName in ('gc_count', 'gc_duration_ms')
    ${COMPONENT_FILTER}
    | summarize 
        AvgValue = avg(MetricValue),
        MaxValue = max(MetricValue),
        TotalValue = sum(MetricValue)
        by Component, MetricName, GCType
    | order by Component asc, GCType asc, MetricName asc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Garbage Collection Analysis:"
    echo "---------------------------"
    
    # Check if GC metrics are available
    GC_COUNT=$(echo "${RESULT}" | jq 'length')
    
    if [ "${GC_COUNT}" -gt 0 ]; then
        # Group by component
        COMPONENTS=$(echo "${RESULT}" | jq -r '.[].Component' | sort | uniq)
        
        for component in ${COMPONENTS}; do
            echo -e "\nComponent: ${component}"
            
            # Get GC types
            GC_TYPES=$(echo "${RESULT}" | jq -r --arg component "$component" \
                '.[] | select(.Component == $component) | .GCType' | sort | uniq)
            
            for gc_type in ${GC_TYPES}; do
                echo "GC Type: ${gc_type}"
                
                # Get GC count
                GC_COUNT=$(echo "${RESULT}" | jq -r --arg component "$component" --arg gc_type "$gc_type" --arg metric "gc_count" \
                    '.[] | select(.Component == $component and .GCType == $gc_type and .MetricName == $metric) | .TotalValue')
                
                # Get GC duration
                GC_DURATION=$(echo "${RESULT}" | jq -r --arg component "$component" --arg gc_type "$gc_type" --arg metric "gc_duration_ms" \
                    '.[] | select(.Component == $component and .GCType == $gc_type and .MetricName == $metric) | .AvgValue')
                
                if [ -n "${GC_COUNT}" ] && [ -n "${GC_DURATION}" ] && [ "${GC_COUNT}" != "null" ] && [ "${GC_DURATION}" != "null" ]; then
                    echo "  Count: ${GC_COUNT}"
                    echo "  Avg Duration: ${GC_DURATION}ms"
                    
                    # Check for frequent GC
                    if (( $(echo "${GC_COUNT} > 100" | bc -l) )); then
                        warn "Frequent garbage collection detected in ${component} (${GC_COUNT} collections)"
                    fi
                    
                    # Check for long GC pauses
                    if (( $(echo "${GC_DURATION} > 200" | bc -l) )); then
                        warn "Long garbage collection pauses detected in ${component} (${GC_DURATION}ms average)"
                    fi
                else
                    echo "  Incomplete GC metrics available"
                fi
            done
        done
    else
        echo "No garbage collection metrics available"
    fi
}

# Generate recommendations
generate_recommendations() {
    log "Generating memory optimization recommendations..."
    
    echo "Memory Optimization Recommendations:"
    echo "----------------------------------"
    
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
    | where MetricName in ('memory_percent', 'memory_allocated_bytes', 'memory_used_bytes')
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
        # Get memory percent
        MEM_PERCENT=$(echo "${RESULT}" | jq -r --arg component "$component" --arg metric "memory_percent" \
            '.[] | select(.Component == $component and .MetricName == $metric) | .AvgValue')
        
        # Get allocated memory
        MEM_ALLOCATED=$(echo "${RESULT}" | jq -r --arg component "$component" --arg metric "memory_allocated_bytes" \
            '.[] | select(.Component == $component and .MetricName == $metric) | .AvgValue')
        
        # Get used memory
        MEM_USED=$(echo "${RESULT}" | jq -r --arg component "$component" --arg metric "memory_used_bytes" \
            '.[] | select(.Component == $component and .MetricName == $metric) | .AvgValue')
        
        # Generate recommendations
        echo -e "\nComponent: ${component}"
        
        if [ -n "${MEM_PERCENT}" ] && [ "${MEM_PERCENT}" != "null" ]; then
            if (( $(echo "${MEM_PERCENT} > 85" | bc -l) )); then
                echo "1. Increase memory allocation (current usage: ${MEM_PERCENT}%)"
            elif (( $(echo "${MEM_PERCENT} < 40" | bc -l) )); then
                echo "1. Consider reducing memory allocation (current usage: ${MEM_PERCENT}%)"
            else
                echo "1. Memory allocation is appropriate (current usage: ${MEM_PERCENT}%)"
            fi
        fi
        
        if [ -n "${MEM_ALLOCATED}" ] && [ -n "${MEM_USED}" ] && [ "${MEM_ALLOCATED}" != "null" ] && [ "${MEM_USED}" != "null" ]; then
            UTILIZATION=$(echo "scale=2; ${MEM_USED} / ${MEM_ALLOCATED} * 100" | bc)
            
            if (( $(echo "${UTILIZATION} < 50" | bc -l) )); then
                echo "2. Memory is over-allocated (${UTILIZATION}% utilization)"
            fi
        fi
        
        # Check for GC metrics
        GC_QUERY="
        let timeRange = ${TIME_RANGE};
        Metrics
        | where TimeGenerated > ago(timeRange)
        | where MetricName == 'gc_duration_ms'
        | where Component == '${component}'
        | summarize AvgDuration = avg(MetricValue) by GCType
        "
        
        GC_RESULT=$(az monitor log-analytics query \
            --workspace "${WORKSPACE_ID}" \
            --analytics-query "${GC_QUERY}" \
            --output json)
        
        GC_COUNT=$(echo "${GC_RESULT}" | jq 'length')
        
        if [ "${GC_COUNT}" -gt 0 ]; then
            LONG_GC=$(echo "${GC_RESULT}" | jq -r '.[] | select(.AvgDuration > 200) | .GCType')
            
            if [ -n "${LONG_GC}" ]; then
                echo "3. Optimize garbage collection (long pauses detected in ${LONG_GC})"
            fi
        fi
    done
}

# Main function
main() {
    log "Starting memory analysis for environment: ${ENV}"
    
    # Analyze memory usage
    analyze_memory_usage
    
    # Analyze memory allocation
    analyze_memory_allocation
    
    # Analyze memory leaks
    analyze_memory_leaks
    
    # Analyze garbage collection
    analyze_garbage_collection
    
    # Generate recommendations
    generate_recommendations
    
    log "Memory analysis completed"
}

# Execute main function
main