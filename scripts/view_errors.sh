#!/bin/bash
# scripts/view_errors.sh

set -e

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV=${1:-"prod"}
TIME_RANGE=${2:-"1h"}
ERROR_TYPE=${3:-"all"}
LIMIT=${4:-50}

# Parse named arguments
for arg in "$@"; do
  case $arg in
    --env=*)
    ENV="${arg#*=}"
    shift
    ;;
    --last=*)
    TIME_RANGE="${arg#*=}"
    shift
    ;;
    --type=*)
    ERROR_TYPE="${arg#*=}"
    shift
    ;;
    --limit=*)
    LIMIT="${arg#*=}"
    shift
    ;;
  esac
done

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

# View recent errors
view_recent_errors() {
    log "Viewing recent errors for the last ${TIME_RANGE}..."
    
    # Build error type filter
    ERROR_FILTER=""
    if [ "${ERROR_TYPE}" != "all" ]; then
        ERROR_FILTER="| where ErrorType == '${ERROR_TYPE}'"
    fi
    
    # Query logs from Azure Monitor
    QUERY="
    let timeRange = ${TIME_RANGE};
    LogEvents
    | where TimeGenerated > ago(timeRange)
    | where Level == 'Error'
    ${ERROR_FILTER}
    | project 
        TimeGenerated,
        Component,
        ErrorType,
        ErrorMessage,
        CorrelationId,
        Properties
    | order by TimeGenerated desc
    | limit ${LIMIT}
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    ERROR_COUNT=$(echo "${RESULT}" | jq 'length')
    log "Found ${ERROR_COUNT} errors in the last ${TIME_RANGE}"
    
    echo "Recent Errors:"
    echo "--------------"
    echo "${RESULT}" | jq -r '.[] | "\(.TimeGenerated) | \(.Component) | \(.ErrorType): \(.ErrorMessage)"'
}

# View error distribution
view_error_distribution() {
    log "Analyzing error distribution..."
    
    # Query logs from Azure Monitor
    QUERY="
    let timeRange = ${TIME_RANGE};
    LogEvents
    | where TimeGenerated > ago(timeRange)
    | where Level == 'Error'
    | summarize 
        ErrorCount = count(),
        Examples = take_any(ErrorMessage, 1)
        by Component, ErrorType
    | order by ErrorCount desc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Error Distribution:"
    echo "------------------"
    echo "${RESULT}" | jq -r '.[] | "\(.Component) | \(.ErrorType): \(.ErrorCount) occurrences | Example: \(.Examples)"'
}

# View error trends
view_error_trends() {
    log "Analyzing error trends..."
    
    # Query logs from Azure Monitor
    QUERY="
    let timeRange = ${TIME_RANGE};
    LogEvents
    | where TimeGenerated > ago(timeRange)
    | where Level == 'Error'
    | summarize 
        ErrorCount = count()
        by bin(TimeGenerated, 5m), Component
    | order by TimeGenerated asc
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    echo "Error Trends (5-minute intervals):"
    echo "---------------------------------"
    
    # Group by component
    COMPONENTS=$(echo "${RESULT}" | jq -r '.[].Component' | sort | uniq)
    
    for component in ${COMPONENTS}; do
        echo -e "\nComponent: ${component}"
        echo "${RESULT}" | jq -r --arg component "$component" '.[] | select(.Component == $component) | "\(.TimeGenerated): \(.ErrorCount) errors"'
    done
}

# View correlated errors
view_correlated_errors() {
    log "Analyzing correlated errors..."
    
    # Query logs from Azure Monitor
    QUERY="
    let timeRange = ${TIME_RANGE};
    LogEvents
    | where TimeGenerated > ago(timeRange)
    | where Level == 'Error'
    | where isnotempty(CorrelationId)
    | summarize 
        ErrorCount = count(),
        Components = make_set(Component),
        ErrorTypes = make_set(ErrorType),
        ErrorMessages = make_set(ErrorMessage)
        by CorrelationId
    | where array_length(Components) > 1 or array_length(ErrorTypes) > 1
    | order by ErrorCount desc
    | limit 10
    "
    
    # Execute query
    RESULT=$(az monitor log-analytics query \
        --workspace "${WORKSPACE_ID}" \
        --analytics-query "${QUERY}" \
        --output json)
    
    # Parse and display results
    CORRELATED_COUNT=$(echo "${RESULT}" | jq 'length')
    
    if [ "${CORRELATED_COUNT}" -gt 0 ]; then
        echo "Correlated Errors (across components):"
        echo "------------------------------------"
        echo "${RESULT}" | jq -r '.[] | "CorrelationId: \(.CorrelationId)\nComponents: \(.Components | join(", "))\nError Types: \(.ErrorTypes | join(", "))\nError Messages: \(.ErrorMessages | join("\n  "))\nCount: \(.ErrorCount)\n"'
    else
        echo "No correlated errors found."
    fi
}

# Main function
main() {
    log "Starting error analysis for environment: ${ENV}"
    
    # View recent errors
    view_recent_errors
    
    # View error distribution
    view_error_distribution
    
    # View error trends
    view_error_trends
    
    # View correlated errors
    view_correlated_errors
    
    log "Error analysis completed"
}

# Execute main function
main