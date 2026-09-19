#!/usr/bin/env bash
set -euo pipefail

product=${1:?product is required}
run_id=${2:-run-1}
case "$product" in
  kyverno|gatekeeper|kubewarden) ;;
  *) echo "unsupported product: $product" >&2; exit 2 ;;
esac
[[ "$run_id" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "invalid run id: $run_id" >&2; exit 2; }
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
result_root="$repo_root/experiments/ephemeral-api-coverage/results/2026-09-19-live-execution"
out_dir="$result_root/$product/$run_id"
namespace=policy-gap-live
pod=baseline

rm -rf "$out_dir"
mkdir -p "$out_dir/requests" "$out_dir/responses" "$out_dir/evidence"

kubectl version -o json >"$out_dir/evidence/kubernetes-version.json"
kubectl get nodes -o json >"$out_dir/evidence/nodes.json"
kubectl get validatingwebhookconfigurations -o json >"$out_dir/evidence/validating-webhooks.json"
kubectl get validatingadmissionpolicies -o json >"$out_dir/evidence/validating-admission-policies.json" 2>/dev/null || true
kubectl get validatingpolicies.policies.kyverno.io -o json >"$out_dir/evidence/kyverno-validating-policies.json" 2>/dev/null || true
kubectl get constrainttemplates.templates.gatekeeper.sh -o json >"$out_dir/evidence/gatekeeper-constraint-templates.json" 2>/dev/null || true
kubectl get clusteradmissionpolicies.policies.kubewarden.io -o json >"$out_dir/evidence/kubewarden-policies.json" 2>/dev/null || true

cat <<'YAML' | kubectl apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: policy-gap-live
  labels:
    pod-security.kubernetes.io/enforce: privileged
    pod-security.kubernetes.io/audit: privileged
    pod-security.kubernetes.io/warn: privileged
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: experiment-runner
  namespace: policy-gap-live
automountServiceAccountToken: false
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: experiment-runner
  namespace: policy-gap-live
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["create", "get", "list", "delete"]
- apiGroups: [""]
  resources: ["pods/ephemeralcontainers"]
  verbs: ["get", "patch", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: experiment-runner
  namespace: policy-gap-live
subjects:
- kind: ServiceAccount
  name: experiment-runner
  namespace: policy-gap-live
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: experiment-runner
YAML

cat <<'YAML' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: baseline
  namespace: policy-gap-live
spec:
  serviceAccountName: experiment-runner
  automountServiceAccountToken: false
  containers:
  - name: base
    image: registry.k8s.io/pause:3.10
    imagePullPolicy: IfNotPresent
    securityContext:
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
      privileged: false
      runAsNonRoot: true
      runAsUser: 65532
      seccompProfile:
        type: RuntimeDefault
YAML

kubectl wait --for=condition=Ready pod/$pod -n "$namespace" --timeout=180s
kubectl get pod "$pod" -n "$namespace" -o json >"$out_dir/evidence/baseline-before.json"

token=$(kubectl create token experiment-runner -n "$namespace" --duration=1h)
server=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
ca_file=$(mktemp)
trap 'rm -f "$ca_file"' EXIT
kubectl config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d >"$ca_file"

api_call() {
  local case_id=$1
  local method=$2
  local path=$3
  local content_type=$4
  local payload=$5
  local status
  cp "$payload" "$out_dir/requests/$case_id.json"
  status=$(curl --silent --show-error \
    --cacert "$ca_file" \
    --request "$method" \
    --header "Authorization: Bearer $token" \
    --header "Content-Type: $content_type" \
    --dump-header "$out_dir/responses/$case_id.headers.txt" \
    --output "$out_dir/responses/$case_id.json" \
    --write-out '%{http_code}' \
    --data-binary "@$payload" \
    "$server$path")
  printf '%s\n' "$status" >"$out_dir/responses/$case_id.status"
}

cat >"$out_dir/c1.json" <<'JSON'
{"apiVersion":"v1","kind":"Pod","metadata":{"name":"ordinary-privileged","namespace":"policy-gap-live"},"spec":{"automountServiceAccountToken":false,"restartPolicy":"Never","containers":[{"name":"main","image":"registry.k8s.io/pause:3.10","securityContext":{"privileged":true}}]}}
JSON

cat >"$out_dir/c2.json" <<'JSON'
{"spec":{"ephemeralContainers":[{"name":"debug-safe","image":"busybox:1.36.1","imagePullPolicy":"IfNotPresent","command":["sh","-c","echo LIVE_SAFE; id; grep '^CapEff:' /proc/self/status; sleep 600"],"securityContext":{"privileged":false,"allowPrivilegeEscalation":false,"runAsNonRoot":true,"runAsUser":65532,"capabilities":{"drop":["ALL"]},"seccompProfile":{"type":"RuntimeDefault"}}}]}}
JSON

cat >"$out_dir/c3.json" <<'JSON'
{"spec":{"ephemeralContainers":[{"name":"debug-safe","image":"busybox:1.36.1","imagePullPolicy":"IfNotPresent","command":["sh","-c","echo LIVE_SAFE; id; grep '^CapEff:' /proc/self/status; sleep 600"],"securityContext":{"privileged":false,"allowPrivilegeEscalation":false,"runAsNonRoot":true,"runAsUser":65532,"capabilities":{"drop":["ALL"]},"seccompProfile":{"type":"RuntimeDefault"}}},{"name":"debug-privileged","image":"busybox:1.36.1","imagePullPolicy":"IfNotPresent","command":["sh","-c","echo LIVE_PRIVILEGED; id; grep '^CapEff:' /proc/self/status; sleep 600"],"securityContext":{"privileged":true}}]}}
JSON

api_call C1 POST "/api/v1/namespaces/$namespace/pods" application/json "$out_dir/c1.json"
c1_status_now=$(cat "$out_dir/responses/C1.status")
if [ "$c1_status_now" -ge 200 ] && [ "$c1_status_now" -lt 300 ]; then
  kubectl delete pod ordinary-privileged -n "$namespace" --wait=false >/dev/null 2>&1 || true
fi
api_call C2 PATCH "/api/v1/namespaces/$namespace/pods/$pod/ephemeralcontainers" application/strategic-merge-patch+json "$out_dir/c2.json"

for i in $(seq 1 90); do
  state=$(kubectl get pod "$pod" -n "$namespace" -o json | jq -r '.status.ephemeralContainerStatuses[]? | select(.name=="debug-safe") | if .state.running then "Running" elif .state.terminated then "Terminated" elif .state.waiting then "Waiting:"+.state.waiting.reason else "Unknown" end')
  [ "$state" = Running ] && break
  sleep 2
done
printf '%s\n' "${state:-Missing}" >"$out_dir/evidence/safe-runtime-state.txt"
kubectl logs "$pod" -n "$namespace" -c debug-safe >"$out_dir/evidence/safe-container.log" 2>"$out_dir/evidence/safe-container.stderr" || true

api_call C3 PATCH "/api/v1/namespaces/$namespace/pods/$pod/ephemeralcontainers" application/strategic-merge-patch+json "$out_dir/c3.json"

for i in $(seq 1 90); do
  state=$(kubectl get pod "$pod" -n "$namespace" -o json | jq -r '.status.ephemeralContainerStatuses[]? | select(.name=="debug-privileged") | if .state.running then "Running" elif .state.terminated then "Terminated" elif .state.waiting then "Waiting:"+.state.waiting.reason else "Unknown" end')
  [ "$state" = Running ] && break
  sleep 2
done
printf '%s\n' "${state:-Missing}" >"$out_dir/evidence/privileged-runtime-state.txt"
kubectl logs "$pod" -n "$namespace" -c debug-privileged >"$out_dir/evidence/privileged-container.log" 2>"$out_dir/evidence/privileged-container.stderr" || true
kubectl exec "$pod" -n "$namespace" -c debug-privileged -- sh -c "id; grep '^CapEff:' /proc/self/status" >"$out_dir/evidence/privileged-exec.log" 2>"$out_dir/evidence/privileged-exec.stderr" || true
kubectl get pod "$pod" -n "$namespace" -o json >"$out_dir/evidence/baseline-after.json"
kubectl get events -n "$namespace" --sort-by=.metadata.creationTimestamp -o json >"$out_dir/evidence/events.json"

c1_status=$(cat "$out_dir/responses/C1.status")
c2_status=$(cat "$out_dir/responses/C2.status")
c3_status=$(cat "$out_dir/responses/C3.status")
safe_state=$(cat "$out_dir/evidence/safe-runtime-state.txt")
privileged_state=$(cat "$out_dir/evidence/privileged-runtime-state.txt")
safe_cap=$(awk '/^CapEff:/ {print $2; exit}' "$out_dir/evidence/safe-container.log")
privileged_cap=$(awk '/^CapEff:/ {print $2; exit}' "$out_dir/evidence/privileged-container.log")

jq -n \
  --arg product "$product" \
  --arg run "$run_id" \
  --argjson ordinaryPrivilegedHttp "$c1_status" \
  --argjson safeEphemeralHttp "$c2_status" \
  --argjson privilegedEphemeralHttp "$c3_status" \
  --arg safeState "$safe_state" \
  --arg privilegedState "$privileged_state" \
  --arg safeCapEff "$safe_cap" \
  --arg privilegedCapEff "$privileged_cap" \
  --arg podUID "$(jq -r .metadata.uid "$out_dir/evidence/baseline-after.json")" \
  --arg nodeName "$(jq -r .spec.nodeName "$out_dir/evidence/baseline-after.json")" \
  '{product:$product,run:$run,httpStatus:{ordinaryPrivilegedCreate:$ordinaryPrivilegedHttp,safeEphemeralUpdate:$safeEphemeralHttp,privilegedEphemeralUpdate:$privilegedEphemeralHttp},runtime:{safeEphemeral:$safeState,privilegedEphemeral:$privilegedState,safeCapEff:$safeCapEff,privilegedCapEff:$privilegedCapEff,podUID:$podUID,nodeName:$nodeName}}' \
  >"$out_dir/summary.json"

rm -f "$out_dir/c1.json" "$out_dir/c2.json" "$out_dir/c3.json"
find "$out_dir/evidence" -type f -size 0 -delete
cat "$out_dir/summary.json"
