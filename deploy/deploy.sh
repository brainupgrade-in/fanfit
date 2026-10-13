#!/usr/bin/env bash
# Build FanFit for arm64, import it straight into Spark's k3s containerd (no registry), and deploy.
#
#   deploy/deploy.sh                      build + import + apply (no public hostname)
#   APP_HOST=<host> deploy/deploy.sh      also apply the Ingress for that host
#   deploy/deploy.sh --status             what is running
#
# Secrets come from ./.env (only the keys listed below) into Secret fanfit-env.
set -euo pipefail
cd "$(dirname "$0")/.."
CTX=${KCTX:-spark-k3s}
SPARK=${SPARK_HOST:-192.168.1.21}
NS=fanfit
k() { kubectl --context "$CTX" "$@"; }

if [[ "${1:-}" == "--status" ]]; then
  k -n "$NS" get deploy,pods,svc,ingress,pvc -o wide; exit 0
fi

TAG=$(git rev-parse --short HEAD)$(git diff --quiet && git diff --cached --quiet || echo "-dirty")
IMG="fanfit:$TAG"

# Build natively on Spark (arm64). Only these files are sent: never .env or other secrets.
echo "• building $IMG on $SPARK (native arm64)"
tar --exclude=__pycache__ -cf - Dockerfile .dockerignore pyproject.toml uv.lock fanfit fixtures \
  | ssh "$SPARK" "docker build -q -t $IMG -" >/dev/null
echo "• importing into k3s containerd"
ssh "$SPARK" "docker save $IMG | sudo k3s ctr images import - >/dev/null"

echo "• applying secret fanfit-env from .env"
k apply -f deploy/k8s/fanfit.yaml --dry-run=client >/dev/null
k get ns "$NS" >/dev/null 2>&1 || k create ns "$NS" >/dev/null
k -n "$NS" create secret generic fanfit-env \
  --from-env-file=<(grep -E '^(LLM_BASE_URL|LLM_API_KEY|LLM_MODEL|QLOO_API_KEY|QLOO_MODE|RATE_PER_IP_HOUR|RATE_GLOBAL_DAY)=.+' .env) \
  --dry-run=client -o yaml | k apply -f - >/dev/null

echo "• applying manifests"
rendered=$(sed "s|IMAGE_PLACEHOLDER|docker.io/library/$IMG|" deploy/k8s/fanfit.yaml)
if [[ -n "${APP_HOST:-}" ]]; then
  [[ "$APP_HOST" == agenticai* ]] || { echo "APP_HOST must start with 'agenticai' (zone page rules)"; exit 1; }
  rendered=$(sed "s|APP_HOST_PLACEHOLDER|$APP_HOST|" <<<"$rendered")
else
  rendered=$(awk 'BEGIN{RS="---\n"; ORS="---\n"} !/kind: Ingress/' <<<"$rendered")
fi
k apply -f - <<<"$rendered" >/dev/null
k -n "$NS" rollout restart deploy/fanfit >/dev/null
k -n "$NS" rollout status deploy/fanfit --timeout=180s
echo "✓ deployed $IMG${APP_HOST:+ at https://$APP_HOST}"
