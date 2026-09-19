#!/usr/bin/env bash
set -euo pipefail

product=${1:?product is required}
family=${2:?family is required: escalation or capabilities}
run_id=${3:-run-1}

if [[ "$family" != "escalation" && "$family" != "capabilities" ]]; then
  echo "family must be escalation or capabilities" >&2
  exit 2
fi

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
out_dir="$repo_root/experiments/ephemeral-api-coverage/results/2026-09-19-policy-families/$product/$family/$run_id"
namespace=policy-family-test

rm -rf "$out_dir"
mkdir -p "$out_dir/requests" "$out_dir/responses" "$out_dir/evidence"

kubectl delete namespace "$namespace" --ignore-not-found --wait=true >/dev/null
cat <<'YAML' | kubectl apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: policy-family-test
  labels:
    pod-security.kubernetes.io/enforce: privileged
    pod-security.kubernetes.io/audit: privileged
    pod-security.kubernetes.io/warn: privileged
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: experiment-runner
  namespace: policy-family-test
automountServiceAccountToken: false
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: experiment-runner
  namespace: policy-family-test
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
  namespace: policy-family-test
subjects:
- kind: ServiceAccount
  name: experiment-runner
  namespace: policy-family-test
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
  namespace: policy-family-test
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
kubectl wait --for=condition=Ready pod/baseline -n "$namespace" --timeout=180s

token=$(kubectl create token experiment-runner -n "$namespace" --duration=1h)
server=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
kubectl config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d >"$out_dir/ca.crt"

normalize_headers() {
  local file=$1
  awk '{sub(/\r$/, ""); sub(/[ \t]+$/, ""); if ($0 == "") {pending = pending "\n"; next} printf "%s%s\n", pending, $0; pending = ""}' "$file" >"$file.tmp"
  mv "$file.tmp" "$file"
}

api_call() {
  local case_id=$1 method=$2 path=$3 content_type=$4 payload=$5
  local status
  status=$(curl --silent --show-error \
    --cacert "$out_dir/ca.crt" \
    --request "$method" \
    --header "Authorization: Bearer $token" \
    --header "Content-Type: $content_type" \
    --dump-header "$out_dir/responses/$case_id.headers.txt" \
    --output "$out_dir/responses/$case_id.json" \
    --write-out '%{http_code}' \
    --data-binary "@$payload" \
    "$server$path")
  normalize_headers "$out_dir/responses/$case_id.headers.txt"
  printf '%s\n' "$status" >"$out_dir/responses/$case_id.status"
}

if [[ "$family" == "escalation" ]]; then
  cat >"$out_dir/requests/ordinary-safe.json" <<'JSON'
{"apiVersion":"v1","kind":"Pod","metadata":{"name":"ordinary-safe","namespace":"policy-family-test"},"spec":{"automountServiceAccountToken":false,"restartPolicy":"Never","containers":[{"name":"safe","image":"registry.k8s.io/pause:3.10","securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}}}]}}
JSON
  cat >"$out_dir/requests/ordinary-violation.json" <<'JSON'
{"apiVersion":"v1","kind":"Pod","metadata":{"name":"ordinary-violation","namespace":"policy-family-test"},"spec":{"automountServiceAccountToken":false,"restartPolicy":"Never","containers":[{"name":"violation","image":"registry.k8s.io/pause:3.10","securityContext":{"allowPrivilegeEscalation":true,"capabilities":{"drop":["ALL"]}}}]}}
JSON
  cat >"$out_dir/requests/ephemeral-safe.json" <<'JSON'
{"spec":{"ephemeralContainers":[{"name":"safe","image":"registry.k8s.io/pause:3.10","securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}}}]}}
JSON
  cat >"$out_dir/requests/ephemeral-violation.json" <<'JSON'
{"spec":{"ephemeralContainers":[{"name":"violation","image":"registry.k8s.io/pause:3.10","securityContext":{"allowPrivilegeEscalation":true,"capabilities":{"drop":["ALL"]}}}]}}
JSON
else
  cat >"$out_dir/requests/ordinary-safe.json" <<'JSON'
{"apiVersion":"v1","kind":"Pod","metadata":{"name":"ordinary-safe","namespace":"policy-family-test"},"spec":{"automountServiceAccountToken":false,"restartPolicy":"Never","containers":[{"name":"safe","image":"registry.k8s.io/pause:3.10","securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}}}]}}
JSON
  cat >"$out_dir/requests/ordinary-violation.json" <<'JSON'
{"apiVersion":"v1","kind":"Pod","metadata":{"name":"ordinary-violation","namespace":"policy-family-test"},"spec":{"automountServiceAccountToken":false,"restartPolicy":"Never","containers":[{"name":"violation","image":"registry.k8s.io/pause:3.10","securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"],"add":["SYS_ADMIN"]}}}]}}
JSON
  cat >"$out_dir/requests/ephemeral-safe.json" <<'JSON'
{"spec":{"ephemeralContainers":[{"name":"safe","image":"registry.k8s.io/pause:3.10","securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}}}]}}
JSON
  cat >"$out_dir/requests/ephemeral-violation.json" <<'JSON'
{"spec":{"ephemeralContainers":[{"name":"violation","image":"registry.k8s.io/pause:3.10","securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"],"add":["SYS_ADMIN"]}}}]}}
JSON
fi

api_call ordinary-safe POST "/api/v1/namespaces/$namespace/pods?dryRun=All" application/json "$out_dir/requests/ordinary-safe.json"
api_call ordinary-violation POST "/api/v1/namespaces/$namespace/pods?dryRun=All" application/json "$out_dir/requests/ordinary-violation.json"
api_call ephemeral-safe PATCH "/api/v1/namespaces/$namespace/pods/baseline/ephemeralcontainers?dryRun=All" application/strategic-merge-patch+json "$out_dir/requests/ephemeral-safe.json"
api_call ephemeral-violation PATCH "/api/v1/namespaces/$namespace/pods/baseline/ephemeralcontainers?dryRun=All" application/strategic-merge-patch+json "$out_dir/requests/ephemeral-violation.json"

ordinary_status=$(cat "$out_dir/responses/ordinary-violation.status")
ephemeral_status=$(cat "$out_dir/responses/ephemeral-violation.status")
if [[ "$family" == "escalation" ]]; then
  ordinary_value=$(jq -c '[.spec.containers[]? | select(.name=="violation") | .securityContext.allowPrivilegeEscalation] | first // null' "$out_dir/responses/ordinary-violation.json")
  ephemeral_value=$(jq -c '[.spec.ephemeralContainers[]? | select(.name=="violation") | .securityContext.allowPrivilegeEscalation] | first // null' "$out_dir/responses/ephemeral-violation.json")
else
  ordinary_value=$(jq -c '[.spec.containers[]? | select(.name=="violation") | .securityContext.capabilities.add // []] | first // null' "$out_dir/responses/ordinary-violation.json")
  ephemeral_value=$(jq -c '[.spec.ephemeralContainers[]? | select(.name=="violation") | .securityContext.capabilities.add // []] | first // null' "$out_dir/responses/ephemeral-violation.json")
fi

kubectl get pod baseline -n "$namespace" -o json >"$out_dir/evidence/baseline-after.json"
kubectl get validatingwebhookconfigurations -o json >"$out_dir/evidence/validating-webhooks.json"
kubectl get mutatingwebhookconfigurations -o json >"$out_dir/evidence/mutating-webhooks.json"
kubectl get validatingadmissionpolicies -o json >"$out_dir/evidence/validating-admission-policies.json" 2>/dev/null || true
kubectl get validatingpolicies.policies.kyverno.io -o json >"$out_dir/evidence/kyverno-validating-policies.json" 2>/dev/null || true
kubectl get constrainttemplates.templates.gatekeeper.sh -o json >"$out_dir/evidence/gatekeeper-constraint-templates.json" 2>/dev/null || true
kubectl get clusteradmissionpolicies.policies.kubewarden.io -o json >"$out_dir/evidence/kubewarden-policies.json" 2>/dev/null || true

jq -n \
  --arg product "$product" \
  --arg family "$family" \
  --argjson ordinarySafe "$(cat "$out_dir/responses/ordinary-safe.status")" \
  --argjson ordinaryViolation "$ordinary_status" \
  --argjson ephemeralSafe "$(cat "$out_dir/responses/ephemeral-safe.status")" \
  --argjson ephemeralViolation "$ephemeral_status" \
  --argjson ordinaryReturned "$ordinary_value" \
  --argjson ephemeralReturned "$ephemeral_value" \
  '{product:$product,family:$family,httpStatus:{ordinarySafe:$ordinarySafe,ordinaryViolation:$ordinaryViolation,ephemeralSafe:$ephemeralSafe,ephemeralViolation:$ephemeralViolation},returnedViolationValue:{ordinary:$ordinaryReturned,ephemeral:$ephemeralReturned}}' \
  >"$out_dir/summary.json"

rm -f "$out_dir/ca.crt"
find "$out_dir/evidence" -type f -empty -delete
cat "$out_dir/summary.json"
