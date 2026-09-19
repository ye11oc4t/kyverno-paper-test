#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
out_dir="$repo_root/experiments/ephemeral-api-coverage/results/2026-09-19-live-native-controls"
cluster=live-native-controls
rm -rf "$out_dir"
mkdir -p "$out_dir/requests" "$out_dir/responses" "$out_dir/evidence"

cleanup() {
  kind delete cluster --name "$cluster" >/dev/null 2>&1 || true
  rm -f "$out_dir/ca.crt"
}
trap cleanup EXIT

kind delete cluster --name "$cluster" >/dev/null 2>&1 || true
kind create cluster --name "$cluster" --image kindest/node:v1.35.8 --wait 180s >/dev/null

cat <<'YAML' | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Namespace
metadata:
  name: live-psa
  labels:
    pod-security.kubernetes.io/enforce: baseline
    pod-security.kubernetes.io/audit: baseline
    pod-security.kubernetes.io/warn: baseline
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: runner
  namespace: live-psa
automountServiceAccountToken: false
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: runner
  namespace: live-psa
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["create", "get", "list"]
- apiGroups: [""]
  resources: ["pods/ephemeralcontainers"]
  verbs: ["get", "patch", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: runner
  namespace: live-psa
subjects:
- kind: ServiceAccount
  name: runner
  namespace: live-psa
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: runner
---
apiVersion: v1
kind: Namespace
metadata:
  name: live-rbac
  labels:
    pod-security.kubernetes.io/enforce: privileged
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: runner
  namespace: live-rbac
automountServiceAccountToken: false
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: runner
  namespace: live-rbac
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["create", "get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: runner
  namespace: live-rbac
subjects:
- kind: ServiceAccount
  name: runner
  namespace: live-rbac
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: runner
YAML

for namespace in live-psa live-rbac; do
  for pod in safe-base violation-base; do
    cat <<YAML | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: $pod
  namespace: $namespace
spec:
  automountServiceAccountToken: false
  containers:
  - name: base
    image: registry.k8s.io/pause:3.10
    imagePullPolicy: IfNotPresent
    securityContext:
      privileged: false
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
      runAsNonRoot: true
      runAsUser: 65532
      seccompProfile:
        type: RuntimeDefault
YAML
  done
  kubectl wait --for=condition=Ready pod/safe-base pod/violation-base -n "$namespace" --timeout=180s >/dev/null
done

server=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
kubectl config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d >"$out_dir/ca.crt"

cat >"$out_dir/requests/safe.json" <<'JSON'
{"spec":{"ephemeralContainers":[{"name":"debug-safe","image":"busybox:1.36.1","imagePullPolicy":"IfNotPresent","command":["sh","-c","echo NATIVE_SAFE; id; grep -E '^(CapEff|NoNewPrivs):' /proc/self/status; sleep 120"],"securityContext":{"privileged":false,"allowPrivilegeEscalation":false,"runAsNonRoot":true,"runAsUser":65532,"capabilities":{"drop":["ALL"]},"seccompProfile":{"type":"RuntimeDefault"}}}]}}
JSON
cat >"$out_dir/requests/privileged.json" <<'JSON'
{"spec":{"ephemeralContainers":[{"name":"debug-privileged","image":"busybox:1.36.1","imagePullPolicy":"IfNotPresent","command":["sh","-c","echo NATIVE_PRIVILEGED; id; grep -E '^(CapEff|NoNewPrivs):' /proc/self/status; sleep 120"],"securityContext":{"privileged":true}}]}}
JSON

normalize_headers() {
  local file=$1
  awk '{sub(/\r$/, ""); sub(/[ \t]+$/, ""); if ($0 == "") {pending = pending "\n"; next} printf "%s%s\n", pending, $0; pending = ""}' "$file" >"$file.tmp"
  mv "$file.tmp" "$file"
}

api_call() {
  local case_id=$1 namespace=$2 pod=$3 payload=$4 token status
  token=$(kubectl create token runner -n "$namespace" --duration=30m)
  status=$(curl --silent --show-error --cacert "$out_dir/ca.crt" \
    --request PATCH \
    --header "Authorization: Bearer $token" \
    --header 'Content-Type: application/strategic-merge-patch+json' \
    --dump-header "$out_dir/responses/$case_id.headers.txt" \
    --output "$out_dir/responses/$case_id.json" \
    --write-out '%{http_code}' \
    --data-binary "@$payload" \
    "$server/api/v1/namespaces/$namespace/pods/$pod/ephemeralcontainers")
  normalize_headers "$out_dir/responses/$case_id.headers.txt"
  printf '%s\n' "$status" >"$out_dir/responses/$case_id.status"
}

api_call psa-safe live-psa safe-base "$out_dir/requests/safe.json"
for _ in $(seq 1 90); do
  safe_state=$(kubectl get pod safe-base -n live-psa -o json | jq -r '.status.ephemeralContainerStatuses[]? | select(.name=="debug-safe") | if .state.running then "Running" elif .state.terminated then "Terminated" elif .state.waiting then "Waiting:"+.state.waiting.reason else "Missing" end')
  [[ "$safe_state" == "Running" || "$safe_state" == "Terminated" ]] && break
  sleep 2
done
kubectl logs safe-base -n live-psa -c debug-safe >"$out_dir/evidence/psa-safe.container.log"
api_call psa-privileged live-psa violation-base "$out_dir/requests/privileged.json"
api_call rbac-privileged live-rbac violation-base "$out_dir/requests/privileged.json"

kubectl get pod safe-base -n live-psa -o json >"$out_dir/evidence/psa-safe.pod.json"
kubectl get pod violation-base -n live-psa -o json >"$out_dir/evidence/psa-violation.pod.json"
kubectl get pod violation-base -n live-rbac -o json >"$out_dir/evidence/rbac-violation.pod.json"
kubectl version -o json >"$out_dir/evidence/kubernetes-version.json"

psa_safe_status=$(<"$out_dir/responses/psa-safe.status")
psa_violation_status=$(<"$out_dir/responses/psa-privileged.status")
rbac_violation_status=$(<"$out_dir/responses/rbac-privileged.status")
psa_violation_stored=$(jq '[.spec.ephemeralContainers[]? | select(.name=="debug-privileged")] | length > 0' "$out_dir/evidence/psa-violation.pod.json")
rbac_violation_stored=$(jq '[.spec.ephemeralContainers[]? | select(.name=="debug-privileged")] | length > 0' "$out_dir/evidence/rbac-violation.pod.json")

jq -n \
  --argjson psaSafe "$psa_safe_status" --arg safeState "$safe_state" \
  --argjson psaViolation "$psa_violation_status" --argjson psaStored "$psa_violation_stored" \
  --argjson rbacViolation "$rbac_violation_status" --argjson rbacStored "$rbac_violation_stored" \
  '{podSecurityAdmission:{safeEphemeralHttp:$psaSafe,safeEphemeralRuntime:$safeState,privilegedEphemeralHttp:$psaViolation,privilegedEphemeralStored:$psaStored},rbac:{privilegedEphemeralHttp:$rbacViolation,privilegedEphemeralStored:$rbacStored}}' \
  >"$out_dir/summary.json"

cat "$out_dir/summary.json"
