#!/usr/bin/env bash
set -euo pipefail

product=${1:?product is required}
case "$product" in
  kyverno|gatekeeper|kubewarden) ;;
  *) echo "unsupported product: $product" >&2; exit 2 ;;
esac
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
out_dir="$repo_root/experiments/ephemeral-api-coverage/results/2026-09-19-live-fixes/$product"
namespace=policy-gap-fixed
pod=baseline

rm -rf "$out_dir"
mkdir -p "$out_dir/requests" "$out_dir/responses" "$out_dir/evidence"
kubectl version -o json >"$out_dir/evidence/kubernetes-version.json"
kubectl get validatingwebhookconfigurations -o json >"$out_dir/evidence/validating-webhooks.json"
kubectl get validatingadmissionpolicies -o json >"$out_dir/evidence/validating-admission-policies.json" 2>/dev/null || true
kubectl get validatingpolicies.policies.kyverno.io -o json >"$out_dir/evidence/kyverno-validating-policies.json" 2>/dev/null || true
kubectl get constrainttemplates.templates.gatekeeper.sh -o json >"$out_dir/evidence/gatekeeper-constraint-templates.json" 2>/dev/null || true
kubectl get clusteradmissionpolicies.policies.kubewarden.io -o json >"$out_dir/evidence/kubewarden-policies.json" 2>/dev/null || true

cat <<'YAML' | kubectl apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: policy-gap-fixed
  labels:
    pod-security.kubernetes.io/enforce: privileged
    pod-security.kubernetes.io/audit: privileged
    pod-security.kubernetes.io/warn: privileged
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: experiment-runner
  namespace: policy-gap-fixed
automountServiceAccountToken: false
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: experiment-runner
  namespace: policy-gap-fixed
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["create", "get"]
- apiGroups: [""]
  resources: ["pods/ephemeralcontainers"]
  verbs: ["get", "patch", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: experiment-runner
  namespace: policy-gap-fixed
subjects:
- kind: ServiceAccount
  name: experiment-runner
  namespace: policy-gap-fixed
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
  namespace: policy-gap-fixed
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

token=$(kubectl create token experiment-runner -n "$namespace" --duration=1h)
server=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
ca_file=$(mktemp)
trap 'rm -f "$ca_file"' EXIT
kubectl config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d >"$ca_file"

normalize_headers() {
  local file=$1
  awk '{sub(/\r$/, ""); sub(/[ \t]+$/, ""); if ($0 == "") {pending = pending "\n"; next} printf "%s%s\n", pending, $0; pending = ""}' "$file" >"$file.tmp"
  mv "$file.tmp" "$file"
}

api_call() {
  local case_id=$1 method=$2 path=$3 content_type=$4 payload=$5 status
  cp "$payload" "$out_dir/requests/$case_id.json"
  status=$(curl --silent --show-error --cacert "$ca_file" --request "$method" \
    --header "Authorization: Bearer $token" --header "Content-Type: $content_type" \
    --dump-header "$out_dir/responses/$case_id.headers.txt" \
    --output "$out_dir/responses/$case_id.json" --write-out '%{http_code}' \
    --data-binary "@$payload" "$server$path")
  normalize_headers "$out_dir/responses/$case_id.headers.txt"
  printf '%s\n' "$status" >"$out_dir/responses/$case_id.status"
}

cat >"$out_dir/c1.json" <<'JSON'
{"apiVersion":"v1","kind":"Pod","metadata":{"name":"ordinary-privileged","namespace":"policy-gap-fixed"},"spec":{"automountServiceAccountToken":false,"restartPolicy":"Never","containers":[{"name":"main","image":"registry.k8s.io/pause:3.10","securityContext":{"privileged":true}}]}}
JSON
cat >"$out_dir/c2.json" <<'JSON'
{"spec":{"ephemeralContainers":[{"name":"debug-safe","image":"registry.k8s.io/pause:3.10","imagePullPolicy":"IfNotPresent","securityContext":{"privileged":false,"allowPrivilegeEscalation":false,"runAsNonRoot":true,"runAsUser":65532,"capabilities":{"drop":["ALL"]},"seccompProfile":{"type":"RuntimeDefault"}}}]}}
JSON
cat >"$out_dir/c3.json" <<'JSON'
{"spec":{"ephemeralContainers":[{"name":"debug-safe","image":"registry.k8s.io/pause:3.10","imagePullPolicy":"IfNotPresent","securityContext":{"privileged":false,"allowPrivilegeEscalation":false,"runAsNonRoot":true,"runAsUser":65532,"capabilities":{"drop":["ALL"]},"seccompProfile":{"type":"RuntimeDefault"}}},{"name":"debug-privileged","image":"registry.k8s.io/pause:3.10","imagePullPolicy":"IfNotPresent","securityContext":{"privileged":true}}]}}
JSON

api_call C1 POST "/api/v1/namespaces/$namespace/pods" application/json "$out_dir/c1.json"
api_call C2 PATCH "/api/v1/namespaces/$namespace/pods/$pod/ephemeralcontainers" application/strategic-merge-patch+json "$out_dir/c2.json"
for i in $(seq 1 90); do
  safe_state_now=$(kubectl get pod "$pod" -n "$namespace" -o json | jq -r '.status.ephemeralContainerStatuses[]? | select(.name=="debug-safe") | if .state.running then "Running" elif .state.terminated then "Terminated" elif .state.waiting then "Waiting:"+.state.waiting.reason else "Unknown" end')
  [ "$safe_state_now" = Running ] && break
  sleep 2
done
api_call C3 PATCH "/api/v1/namespaces/$namespace/pods/$pod/ephemeralcontainers" application/strategic-merge-patch+json "$out_dir/c3.json"

kubectl get pod "$pod" -n "$namespace" -o json >"$out_dir/evidence/baseline-after.json"
c1=$(cat "$out_dir/responses/C1.status")
c2=$(cat "$out_dir/responses/C2.status")
c3=$(cat "$out_dir/responses/C3.status")
safe_stored=$(jq '[.spec.ephemeralContainers[]? | select(.name=="debug-safe")] | length == 1' "$out_dir/evidence/baseline-after.json")
privileged_stored=$(jq '[.spec.ephemeralContainers[]? | select(.name=="debug-privileged")] | length > 0' "$out_dir/evidence/baseline-after.json")
safe_state=$(jq -r '.status.ephemeralContainerStatuses[]? | select(.name=="debug-safe") | if .state.running then "Running" elif .state.terminated then "Terminated" elif .state.waiting then "Waiting:"+.state.waiting.reason else "Unknown" end' "$out_dir/evidence/baseline-after.json")

jq -n --arg product "$product" --argjson c1 "$c1" --argjson c2 "$c2" --argjson c3 "$c3" \
  --argjson safeStored "$safe_stored" --argjson privilegedStored "$privileged_stored" --arg safeState "$safe_state" \
  '{product:$product,httpStatus:{ordinaryPrivilegedCreate:$c1,safeEphemeralUpdate:$c2,privilegedEphemeralUpdate:$c3},pod:{safeStored:$safeStored,safeState:$safeState,privilegedStored:$privilegedStored}}' \
  >"$out_dir/summary.json"

rm -f "$out_dir/c1.json" "$out_dir/c2.json" "$out_dir/c3.json"
find "$out_dir/evidence" -type f -size 0 -delete
cat "$out_dir/summary.json"
