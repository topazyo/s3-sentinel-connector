#!/bin/bash
set -euo pipefail

ENVIRONMENT=${1:-dev}
NAMESPACE="s3-sentinel-${ENVIRONMENT}"
DEPLOYMENT_NAME="s3-sentinel-connector"

log() {
  echo "[$(date +'%Y-%m-%dT%H:%M:%S%z')] $1"
}

log "Running smoke tests for environment: ${ENVIRONMENT}"

kubectl get namespace "${NAMESPACE}" >/dev/null
kubectl get deployment "${DEPLOYMENT_NAME}" -n "${NAMESPACE}" >/dev/null
kubectl rollout status deployment/"${DEPLOYMENT_NAME}" -n "${NAMESPACE}" --timeout=180s >/dev/null

READY_REPLICAS=$(kubectl get deployment "${DEPLOYMENT_NAME}" -n "${NAMESPACE}" -o jsonpath='{.status.readyReplicas}')
if [[ -z "${READY_REPLICAS}" || "${READY_REPLICAS}" == "0" ]]; then
  echo "No ready replicas for ${DEPLOYMENT_NAME} in ${NAMESPACE}" >&2
  exit 1
fi

log "Smoke tests passed: ${READY_REPLICAS} ready replica(s)."
