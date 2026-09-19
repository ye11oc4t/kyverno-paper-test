#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
out_dir="$repo_root/experiments/ephemeral-api-coverage/results/2026-09-19-kubernetes-controls"
cluster=pg-k8s-controls

kind delete cluster --name "$cluster" >/dev/null 2>&1 || true
kind create cluster --name "$cluster" --image kindest/node:v1.35.8 --wait 180s
trap 'kind delete cluster --name "$cluster" >/dev/null 2>&1 || true' EXIT

rm -rf "$out_dir"
mkdir -p "$out_dir/requests" "$out_dir/responses" "$out_dir/evidence"

kubectl version -o json >"$out_dir/evidence/kubernetes-version.json"
kubectl get nodes -o json >"$out_dir/evidence/nodes.json"

cat <<'YAML' | kubectl apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: psa-control
  labels:
    pod-security.kubernetes.io/enforce: baseline
    pod-security.kubernetes.io/audit: baseline
    pod-security.kubernetes.io/warn: baseline
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: psa-runner
  namespace: psa-control
automountServiceAccountToken: false
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: psa-runner
  namespace: psa-control
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get"]
- apiGroups: [""]
  resources: ["pods/ephemeralcontainers"]
  verbs: ["get", "patch", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: psa-runner
  namespace: psa-control
subjects:
- kind: ServiceAccount
  name: psa-runner
  namespace: psa-control
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: psa-runner
---
apiVersion: v1
kind: Namespace
metadata:
  name: rbac-control
  labels:
    pod-security.kubernetes.io/enforce: privileged
    pod-security.kubernetes.io/audit: privileged
    pod-security.kubernetes.io/warn: privileged
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: rbac-runner
  namespace: rbac-control
automountServiceAccountToken: false
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: rbac-runner
  namespace: rbac-control
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: rbac-runner
  namespace: rbac-control
subjects:
- kind: ServiceAccount
  name: rbac-runner
  namespace: rbac-control
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: rbac-runner
YAML

for namespace in psa-control rbac-control; do
  cat <<YAML | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: baseline
  namespace: $namespace
spec:
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
done

server=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
ca_file=$(mktemp)
trap 'rm -f "$ca_file"; kind delete cluster --name "$cluster" >/dev/null 2>&1 || true' EXIT
kubectl config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d >"$ca_file"

normalize_headers() {
  local file=$1
  awk '{sub(/\r$/, ""); sub(/[ \t]+$/, ""); if ($0 == "") {pending = pending "\n"; next} printf "%s%s\n", pending, $0; pending = ""}' "$file" >"$file.tmp"
  mv "$file.tmp" "$file"
}

api_call() {
  local case_id=$1
  local token=$2
  local method=$3
  local path=$4
  local content_type=$5
  local payload=$6
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
  normalize_headers "$out_dir/responses/$case_id.headers.txt"
  printf '%s\n' "$status" >"$out_dir/responses/$case_id.status"
}

cat >"$out_dir/safe.json" <<'JSON'
{"spec":{"ephemeralContainers":[{"name":"debug-safe","image":"registry.k8s.io/pause:3.10","imagePullPolicy":"IfNotPresent","securityContext":{"privileged":false,"allowPrivilegeEscalation":false,"runAsNonRoot":true,"runAsUser":65532,"capabilities":{"drop":["ALL"]},"seccompProfile":{"type":"RuntimeDefault"}}}]}}
JSON
cat >"$out_dir/psa-privileged.json" <<'JSON'
{"spec":{"ephemeralContainers":[{"name":"debug-safe","image":"registry.k8s.io/pause:3.10","imagePullPolicy":"IfNotPresent","securityContext":{"privileged":false,"allowPrivilegeEscalation":false,"runAsNonRoot":true,"runAsUser":65532,"capabilities":{"drop":["ALL"]},"seccompProfile":{"type":"RuntimeDefault"}}},{"name":"debug-privileged","image":"registry.k8s.io/pause:3.10","imagePullPolicy":"IfNotPresent","securityContext":{"privileged":true}}]}}
JSON
cat >"$out_dir/rbac-privileged.json" <<'JSON'
{"spec":{"ephemeralContainers":[{"name":"debug-privileged","image":"registry.k8s.io/pause:3.10","imagePullPolicy":"IfNotPresent","securityContext":{"privileged":true}}]}}
JSON

psa_token=$(kubectl create token psa-runner -n psa-control --duration=1h)
rbac_token=$(kubectl create token rbac-runner -n rbac-control --duration=1h)

api_call PSA_SAFE "$psa_token" PATCH /api/v1/namespaces/psa-control/pods/baseline/ephemeralcontainers application/strategic-merge-patch+json "$out_dir/safe.json"
api_call PSA_PRIVILEGED "$psa_token" PATCH /api/v1/namespaces/psa-control/pods/baseline/ephemeralcontainers application/strategic-merge-patch+json "$out_dir/psa-privileged.json"
api_call RBAC_PRIVILEGED "$rbac_token" PATCH /api/v1/namespaces/rbac-control/pods/baseline/ephemeralcontainers application/strategic-merge-patch+json "$out_dir/rbac-privileged.json"

kubectl get pod baseline -n psa-control -o json >"$out_dir/evidence/psa-pod-after.json"
kubectl get pod baseline -n rbac-control -o json >"$out_dir/evidence/rbac-pod-after.json"
kubectl auth can-i update pods --subresource=ephemeralcontainers -n psa-control --as=system:serviceaccount:psa-control:psa-runner >"$out_dir/evidence/psa-can-update.txt"
kubectl auth can-i update pods --subresource=ephemeralcontainers -n rbac-control --as=system:serviceaccount:rbac-control:rbac-runner >"$out_dir/evidence/rbac-can-update.txt" || true

psa_safe=$(cat "$out_dir/responses/PSA_SAFE.status")
psa_privileged=$(cat "$out_dir/responses/PSA_PRIVILEGED.status")
rbac_privileged=$(cat "$out_dir/responses/RBAC_PRIVILEGED.status")
psa_has_privileged=$(jq '[.spec.ephemeralContainers[]? | select(.name=="debug-privileged")] | length > 0' "$out_dir/evidence/psa-pod-after.json")
rbac_has_privileged=$(jq '[.spec.ephemeralContainers[]? | select(.name=="debug-privileged")] | length > 0' "$out_dir/evidence/rbac-pod-after.json")

jq -n \
  --argjson psaSafeHttp "$psa_safe" \
  --argjson psaPrivilegedHttp "$psa_privileged" \
  --argjson rbacPrivilegedHttp "$rbac_privileged" \
  --argjson psaStoredPrivileged "$psa_has_privileged" \
  --argjson rbacStoredPrivileged "$rbac_has_privileged" \
  --arg psaCanUpdate "$(cat "$out_dir/evidence/psa-can-update.txt")" \
  --arg rbacCanUpdate "$(cat "$out_dir/evidence/rbac-can-update.txt")" \
  '{psa:{safeEphemeralHttp:$psaSafeHttp,privilegedEphemeralHttp:$psaPrivilegedHttp,rbacCanUpdate:($psaCanUpdate=="yes"),privilegedStored:$psaStoredPrivileged},rbac:{privilegedEphemeralHttp:$rbacPrivilegedHttp,rbacCanUpdate:($rbacCanUpdate=="yes"),privilegedStored:$rbacStoredPrivileged}}' \
  >"$out_dir/summary.json"

rm -f "$out_dir/safe.json" "$out_dir/psa-privileged.json" "$out_dir/rbac-privileged.json"
cat "$out_dir/summary.json"
