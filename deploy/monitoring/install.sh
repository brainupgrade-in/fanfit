#!/usr/bin/env bash
# Install/refresh FanFit uptime monitoring on the NUC observability stack. Remove after 2026-11-16 with --delete.
set -euo pipefail
cd "$(dirname "$0")"
CTX=${KCTX:-nuc-k3s}
if [[ "${1:-}" == "--delete" ]]; then
  kubectl --context "$CTX" delete -f fanfit-probe.yaml -f blackbox-exporter.yaml --ignore-not-found
  exit 0
fi
kubectl --context "$CTX" apply -f blackbox-exporter.yaml
kubectl --context "$CTX" -n observability rollout status deploy/blackbox-exporter --timeout=120s
kubectl --context "$CTX" apply -f fanfit-probe.yaml
