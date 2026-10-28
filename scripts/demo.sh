#!/usr/bin/env bash
# End-to-end demo against the kind stack from `make kind-install`:
# register -> deploy v1 -> infer -> self-heal -> upgrade v2 -> rollback -> delete.
set -euo pipefail

NS=${NS:-default}
NAME=${NAME:-sentiment}
API=http://localhost:8000
RUNTIME=http://localhost:8080
KERNEXYSCTL=${KERNEXYSCTL:-kernexysctl}
export KERNEXYS_API_URL=$API

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
pause() { [[ -n "${NO_PAUSE:-}" ]] || read -rp "    [enter] " _; }

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT

forward() { # forward <ns> <target> <local-port> [remote-port]; returns once it answers
  kubectl -n "$1" port-forward "$2" "$3:${4:-$3}" >/dev/null 2>&1 &
  pids+=($!)
  for _ in $(seq 30); do curl -s "localhost:$3/health/live" >/dev/null && return; sleep 1; done
  echo "port-forward to $2 never became ready" >&2; exit 1
}

infer() { # infer <text>
  curl -sS -X POST "$RUNTIME/v1/infer" -H 'content-type: application/json' \
    -d "{\"text\":\"$1\"}"
  echo
}

wait_version() { # wait until the runtime service answers with <version>
  kubectl -n "$NS" rollout status "deployment/$NAME" --timeout=120s
  # pods were replaced, so re-open the runtime forward against the new ones
  [[ -n "${runtime_pid:-}" ]] && kill "$runtime_pid" 2>/dev/null || true
  forward "$NS" "svc/$NAME" 8080 80
  runtime_pid=${pids[-1]}
  for _ in $(seq 30); do
    infer "probe" | grep -q "\"version\":\"$1\"" && return
    sleep 1
  done
  echo "runtime never served $1" >&2; exit 1
}

step "Control API health (liveness + DB/CRD readiness)"
forward kernexys-system svc/kernexys-api 8000
curl -sS "$API/health/ready"; echo
pause

step "Register model 'sentiment' with immutable versions v1 and v2 in PostgreSQL"
curl -sS -X PUT "$API/v1/models/$NAME" -H 'content-type: application/json' \
  -d '{"description":"Deterministic reference sentiment classifier"}'; echo
for v in v1 v2; do
  curl -sS -X PUT "$API/v1/models/$NAME/versions/$v" -H 'content-type: application/json' \
    -d "{\"runtime_image\":\"kernexys/model-runtime:$v\"}"; echo
done
pause

step "Deploy v1 via kernexysctl (API writes only the ModelDeployment CR)"
"$KERNEXYSCTL" deploy "$NAME" --namespace "$NS" --model "$NAME" --version v1 --replicas 2 \
  --request cpu=50m --request memory=64Mi
wait_version v1
kubectl -n "$NS" get modeldeployment,deployment,service,pods
pause

step "Inference against v1"
infer "I love this product, it is great"
infer "This is terrible and I hate it"
pause

step "Self-healing: delete the Deployment out from under the controller"
kubectl -n "$NS" delete deployment "$NAME"
for _ in $(seq 30); do kubectl -n "$NS" get deployment "$NAME" >/dev/null 2>&1 && break; sleep 1; done
kubectl -n "$NS" get deployment "$NAME"
wait_version v1
pause

step "Upgrade to v2 (same command, new version)"
"$KERNEXYSCTL" deploy "$NAME" --namespace "$NS" --model "$NAME" --version v2 --replicas 2 \
  --request cpu=50m --request memory=64Mi
wait_version v2
infer "I love this product, it is great"
pause

step "Roll back to v1"
"$KERNEXYSCTL" rollback "$NAME" --namespace "$NS" --version v1
wait_version v1
"$KERNEXYSCTL" status "$NAME" --namespace "$NS"
pause

step "Delete: Kubernetes GC removes the controller-owned Deployment and Service"
"$KERNEXYSCTL" delete "$NAME" --namespace "$NS"
kubectl -n "$NS" wait --for=delete "deployment/$NAME" "service/$NAME" --timeout=60s
echo "done."
