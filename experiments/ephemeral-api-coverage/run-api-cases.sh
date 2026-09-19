#!/usr/bin/env bash
set -euo pipefail

product=${1:?product is required}
run_id=${2:?run id is required}
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
out_dir="$repo_root/experiments/ephemeral-api-coverage/results/2026-09-19/$product/$run_id"
namespace=policy-gap-test

mkdir -p "$out_dir/cases" "$out_dir/evidence"

kubectl version -o json >"$out_dir/evidence/kubernetes-version.json"
kubectl get nodes -o json >"$out_dir/evidence/nodes.json"

cat <<'YAML' | kubectl apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: policy-gap-test
  labels:
    pod-security.kubernetes.io/enforce: privileged
    pod-security.kubernetes.io/audit: privileged
    pod-security.kubernetes.io/warn: privileged
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: experiment-runner
  namespace: policy-gap-test
automountServiceAccountToken: false
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: experiment-runner
  namespace: policy-gap-test
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
  namespace: policy-gap-test
subjects:
- kind: ServiceAccount
  name: experiment-runner
  namespace: policy-gap-test
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
  namespace: policy-gap-test
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
kubectl get pod baseline -n "$namespace" -o json >"$out_dir/evidence/baseline-before.json"

token=$(kubectl create token experiment-runner -n "$namespace" --duration=1h)
server=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
kubectl config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d >"$out_dir/evidence/ca.crt"
ca_file="$out_dir/evidence/ca.crt"

api_call() {
  local case_id=$1
  local method=$2
  local path=$3
  local content_type=$4
  local payload=$5
  local case_dir="$out_dir/cases/$case_id"
  local started_at
  local status
  local payload_sha
  mkdir -p "$case_dir"
  cp "$payload" "$case_dir/request.json"
  started_at=$(date --iso-8601=ns)
  payload_sha=$(sha256sum "$payload" | awk '{print $1}')
  status=$(curl --silent --show-error \
    --cacert "$ca_file" \
    --request "$method" \
    --header "Authorization: Bearer $token" \
    --header "Content-Type: $content_type" \
    --dump-header "$case_dir/response-headers.txt" \
    --output "$case_dir/response.json" \
    --write-out '%{http_code}' \
    --data-binary "@$payload" \
    "$server$path")
  jq -n \
    --arg case "$case_id" \
    --arg method "$method" \
    --arg path "$path" \
    --arg contentType "$content_type" \
    --arg startedAt "$started_at" \
    --arg completedAt "$(date --iso-8601=ns)" \
    --arg requestSha256 "$payload_sha" \
    --argjson httpStatus "$status" \
    '{case:$case,method:$method,path:$path,contentType:$contentType,startedAt:$startedAt,completedAt:$completedAt,requestSha256:$requestSha256,httpStatus:$httpStatus}' \
    >"$case_dir/meta.json"
}

cat >"$out_dir/ssar-pods-create.json" <<'JSON'
{"apiVersion":"authorization.k8s.io/v1","kind":"SelfSubjectAccessReview","spec":{"resourceAttributes":{"namespace":"policy-gap-test","verb":"create","group":"","resource":"pods"}}}
JSON
api_call SSAR-pods-create POST /apis/authorization.k8s.io/v1/selfsubjectaccessreviews application/json "$out_dir/ssar-pods-create.json"

cat >"$out_dir/ssar-ephemeral-update.json" <<'JSON'
{"apiVersion":"authorization.k8s.io/v1","kind":"SelfSubjectAccessReview","spec":{"resourceAttributes":{"namespace":"policy-gap-test","verb":"update","group":"","resource":"pods","subresource":"ephemeralcontainers"}}}
JSON
api_call SSAR-ephemeral-update POST /apis/authorization.k8s.io/v1/selfsubjectaccessreviews application/json "$out_dir/ssar-ephemeral-update.json"

cat >"$out_dir/c0.json" <<'JSON'
{"apiVersion":"v1","kind":"Pod","metadata":{"name":"c0-safe","namespace":"policy-gap-test"},"spec":{"automountServiceAccountToken":false,"restartPolicy":"Never","containers":[{"name":"main","image":"registry.k8s.io/pause:3.10","securityContext":{"privileged":false}}]}}
JSON
cat >"$out_dir/c1.json" <<'JSON'
{"apiVersion":"v1","kind":"Pod","metadata":{"name":"c1-privileged","namespace":"policy-gap-test"},"spec":{"automountServiceAccountToken":false,"restartPolicy":"Never","containers":[{"name":"main","image":"registry.k8s.io/pause:3.10","securityContext":{"privileged":true}}]}}
JSON
cat >"$out_dir/c2.json" <<'JSON'
{"spec":{"ephemeralContainers":[{"name":"debug-safe","image":"registry.k8s.io/pause:3.10","securityContext":{"privileged":false}}]}}
JSON
cat >"$out_dir/c3.json" <<'JSON'
{"spec":{"ephemeralContainers":[{"name":"debug-privileged","image":"registry.k8s.io/pause:3.10","securityContext":{"privileged":true}}]}}
JSON

api_call C0 POST "/api/v1/namespaces/$namespace/pods?dryRun=All" application/json "$out_dir/c0.json"
api_call C1 POST "/api/v1/namespaces/$namespace/pods?dryRun=All" application/json "$out_dir/c1.json"
api_call C2 PATCH "/api/v1/namespaces/$namespace/pods/baseline/ephemeralcontainers?dryRun=All" application/strategic-merge-patch+json "$out_dir/c2.json"
api_call C3 PATCH "/api/v1/namespaces/$namespace/pods/baseline/ephemeralcontainers?dryRun=All" application/strategic-merge-patch+json "$out_dir/c3.json"

kubectl get pod baseline -n "$namespace" -o json >"$out_dir/evidence/baseline-after.json"
jq -n \
  --arg product "$product" \
  --arg run "$run_id" \
  --arg c0 "$(jq -r .httpStatus "$out_dir/cases/C0/meta.json")" \
  --arg c1 "$(jq -r .httpStatus "$out_dir/cases/C1/meta.json")" \
  --arg c2 "$(jq -r .httpStatus "$out_dir/cases/C2/meta.json")" \
  --arg c3 "$(jq -r .httpStatus "$out_dir/cases/C3/meta.json")" \
  --arg ssarCreate "$(jq -r '.status.allowed' "$out_dir/cases/SSAR-pods-create/response.json")" \
  --arg ssarEphemeral "$(jq -r '.status.allowed' "$out_dir/cases/SSAR-ephemeral-update/response.json")" \
  '{product:$product,run:$run,httpStatus:{C0:($c0|tonumber),C1:($c1|tonumber),C2:($c2|tonumber),C3:($c3|tonumber)},rbac:{podsCreate:($ssarCreate=="true"),ephemeralUpdate:($ssarEphemeral=="true")}}' \
  >"$out_dir/summary.json"

rm -f \
  "$out_dir/ssar-pods-create.json" \
  "$out_dir/ssar-ephemeral-update.json" \
  "$out_dir/c0.json" \
  "$out_dir/c1.json" \
  "$out_dir/c2.json" \
  "$out_dir/c3.json" \
  "$out_dir/evidence/ca.crt"
cat "$out_dir/summary.json"
