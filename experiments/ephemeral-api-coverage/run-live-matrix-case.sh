#!/usr/bin/env bash
set -euo pipefail

product=${1:?product is required}
install_id=${2:?install id is required}
family=${3:?family is required}
repeat_id=${4:?repeat id is required}

case "$product" in
  kyverno|gatekeeper|kubewarden) ;;
  *) echo "unsupported product: $product" >&2; exit 2 ;;
esac
case "$family" in
  privileged|escalation|capabilities) ;;
  *) echo "unsupported family: $family" >&2; exit 2 ;;
esac
[[ "$install_id" =~ ^[0-9]+$ ]] || { echo "invalid install id" >&2; exit 2; }
[[ "$repeat_id" =~ ^[0-9]+$ ]] || { echo "invalid repeat id" >&2; exit 2; }

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
result_root=${LIVE_RESULT_ROOT:-"$repo_root/experiments/ephemeral-api-coverage/results/2026-09-19-live-matrix"}
out_dir="$result_root/$product/install-$install_id/$family/repeat-$repeat_id"
namespace="live-${product:0:2}-${install_id}-${family:0:3}-${repeat_id}"
image=busybox:1.36.1

rm -rf "$out_dir"
mkdir -p "$out_dir/requests" "$out_dir/responses" "$out_dir/evidence"

cleanup() {
  kubectl delete namespace "$namespace" --ignore-not-found --wait=false >/dev/null 2>&1 || true
  rm -f "$out_dir/ca.crt"
}
trap cleanup EXIT

cat <<YAML | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Namespace
metadata:
  name: $namespace
  labels:
    pod-security.kubernetes.io/enforce: privileged
    pod-security.kubernetes.io/audit: privileged
    pod-security.kubernetes.io/warn: privileged
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: experiment-runner
  namespace: $namespace
automountServiceAccountToken: false
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: experiment-runner
  namespace: $namespace
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
  namespace: $namespace
subjects:
- kind: ServiceAccount
  name: experiment-runner
  namespace: $namespace
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: experiment-runner
YAML

cat <<YAML | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: ephemeral-safe-base
  namespace: $namespace
spec:
  serviceAccountName: experiment-runner
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
---
apiVersion: v1
kind: Pod
metadata:
  name: ephemeral-violation-base
  namespace: $namespace
spec:
  serviceAccountName: experiment-runner
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
kubectl wait --for=condition=Ready pod/ephemeral-safe-base pod/ephemeral-violation-base -n "$namespace" --timeout=180s >/dev/null

token=$(kubectl create token experiment-runner -n "$namespace" --duration=1h)
server=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
kubectl config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d >"$out_dir/ca.crt"

normalize_headers() {
  local file=$1
  awk '{sub(/\r$/, ""); sub(/[ \t]+$/, ""); if ($0 == "") {pending = pending "\n"; next} printf "%s%s\n", pending, $0; pending = ""}' "$file" >"$file.tmp"
  mv "$file.tmp" "$file"
}

api_call() {
  local case_id=$1 method=$2 path=$3 content_type=$4 payload=$5 status
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

cat >"$out_dir/requests/ordinary-safe.json" <<JSON
{"apiVersion":"v1","kind":"Pod","metadata":{"name":"ordinary-safe","namespace":"$namespace"},"spec":{"automountServiceAccountToken":false,"restartPolicy":"Never","containers":[{"name":"main-safe","image":"$image","imagePullPolicy":"IfNotPresent","command":["sh","-c","echo ORDINARY_SAFE; id; grep -E '^(CapEff|NoNewPrivs):' /proc/self/status; sleep 120"],"securityContext":{"privileged":false,"allowPrivilegeEscalation":false,"runAsNonRoot":true,"runAsUser":65532,"capabilities":{"drop":["ALL"]},"seccompProfile":{"type":"RuntimeDefault"}}}]}}
JSON

case "$family" in
  privileged)
    violation_context='{"privileged":true}'
    ;;
  escalation)
    violation_context='{"privileged":false,"allowPrivilegeEscalation":true,"runAsNonRoot":true,"runAsUser":65532,"capabilities":{"drop":["ALL"]},"seccompProfile":{"type":"RuntimeDefault"}}'
    ;;
  capabilities)
    violation_context='{"privileged":false,"allowPrivilegeEscalation":false,"runAsNonRoot":false,"runAsUser":0,"capabilities":{"drop":["ALL"],"add":["SYS_ADMIN"]},"seccompProfile":{"type":"RuntimeDefault"}}'
    ;;
esac

jq -n \
  --arg ns "$namespace" \
  --arg image "$image" \
  --arg family "$family" \
  --argjson context "$violation_context" \
  '{apiVersion:"v1",kind:"Pod",metadata:{name:"ordinary-violation",namespace:$ns},spec:{automountServiceAccountToken:false,restartPolicy:"Never",containers:[{name:"main-violation",image:$image,imagePullPolicy:"IfNotPresent",command:["sh","-c",("echo ORDINARY_VIOLATION_"+($family|ascii_upcase)+"; id; grep -E \"^(CapEff|NoNewPrivs):\" /proc/self/status; sleep 120")],securityContext:$context}]}}' \
  >"$out_dir/requests/ordinary-violation.json"

cat >"$out_dir/requests/ephemeral-safe.json" <<JSON
{"spec":{"ephemeralContainers":[{"name":"debug-safe","image":"$image","imagePullPolicy":"IfNotPresent","command":["sh","-c","echo EPHEMERAL_SAFE; id; grep -E '^(CapEff|NoNewPrivs):' /proc/self/status; sleep 120"],"securityContext":{"privileged":false,"allowPrivilegeEscalation":false,"runAsNonRoot":true,"runAsUser":65532,"capabilities":{"drop":["ALL"]},"seccompProfile":{"type":"RuntimeDefault"}}}]}}
JSON

jq -n \
  --arg image "$image" \
  --arg family "$family" \
  --argjson context "$violation_context" \
  '{spec:{ephemeralContainers:[{name:"debug-violation",image:$image,imagePullPolicy:"IfNotPresent",command:["sh","-c",("echo EPHEMERAL_VIOLATION_"+($family|ascii_upcase)+"; id; grep -E \"^(CapEff|NoNewPrivs):\" /proc/self/status; sleep 120")],securityContext:$context}]}}' \
  >"$out_dir/requests/ephemeral-violation.json"

api_call ordinary-safe POST "/api/v1/namespaces/$namespace/pods" application/json "$out_dir/requests/ordinary-safe.json"
api_call ordinary-violation POST "/api/v1/namespaces/$namespace/pods" application/json "$out_dir/requests/ordinary-violation.json"
api_call ephemeral-safe PATCH "/api/v1/namespaces/$namespace/pods/ephemeral-safe-base/ephemeralcontainers" application/strategic-merge-patch+json "$out_dir/requests/ephemeral-safe.json"
api_call ephemeral-violation PATCH "/api/v1/namespaces/$namespace/pods/ephemeral-violation-base/ephemeralcontainers" application/strategic-merge-patch+json "$out_dir/requests/ephemeral-violation.json"

is_success() {
  local status=$1
  (( status >= 200 && status < 300 ))
}

capture_container() {
  local case_id=$1 pod=$2 container=$3 status=$4
  local state="NotAdmitted"
  if is_success "$status"; then
    for _ in $(seq 1 90); do
      state=$(kubectl get pod "$pod" -n "$namespace" -o json 2>/dev/null | jq -r --arg c "$container" '
        ([.status.containerStatuses[]?, .status.ephemeralContainerStatuses[]?] | flatten | map(select(.name==$c)) | first) as $s |
        if $s == null then "Missing"
        elif $s.state.running then "Running"
        elif $s.state.terminated then "Terminated"
        elif $s.state.waiting then "Waiting:" + $s.state.waiting.reason
        else "Unknown" end' || true)
      [[ "$state" == "Running" || "$state" == "Terminated" ]] && break
      sleep 2
    done
    kubectl get pod "$pod" -n "$namespace" -o json >"$out_dir/evidence/$case_id.pod.json" 2>"$out_dir/evidence/$case_id.get.stderr" || true
    kubectl logs "$pod" -n "$namespace" -c "$container" >"$out_dir/evidence/$case_id.container.log" 2>"$out_dir/evidence/$case_id.container.stderr" || true
  fi
  printf '%s\n' "$state" >"$out_dir/evidence/$case_id.runtime-state.txt"
}

ordinary_safe_status=$(<"$out_dir/responses/ordinary-safe.status")
ordinary_violation_status=$(<"$out_dir/responses/ordinary-violation.status")
ephemeral_safe_status=$(<"$out_dir/responses/ephemeral-safe.status")
ephemeral_violation_status=$(<"$out_dir/responses/ephemeral-violation.status")

capture_container ordinary-safe ordinary-safe main-safe "$ordinary_safe_status"
capture_container ordinary-violation ordinary-violation main-violation "$ordinary_violation_status"
capture_container ephemeral-safe ephemeral-safe-base debug-safe "$ephemeral_safe_status"
capture_container ephemeral-violation ephemeral-violation-base debug-violation "$ephemeral_violation_status"

kubectl get pod ephemeral-safe-base -n "$namespace" -o json >"$out_dir/evidence/ephemeral-safe-base.final.json"
kubectl get pod ephemeral-violation-base -n "$namespace" -o json >"$out_dir/evidence/ephemeral-violation-base.final.json"
kubectl get events -n "$namespace" --sort-by=.metadata.creationTimestamp -o json >"$out_dir/evidence/events.json"

pod_has_container() {
  local file=$1 name=$2
  if [[ ! -s "$file" ]]; then printf 'false'; return; fi
  jq -c --arg n "$name" '([.spec.containers[]?, .spec.ephemeralContainers[]?] | flatten | map(select(.name==$n)) | length) == 1' "$file"
}

ordinary_safe_persisted=$(pod_has_container "$out_dir/evidence/ordinary-safe.pod.json" main-safe)
ordinary_violation_persisted=$(pod_has_container "$out_dir/evidence/ordinary-violation.pod.json" main-violation)
ephemeral_safe_persisted=$(pod_has_container "$out_dir/evidence/ephemeral-safe.pod.json" debug-safe)
ephemeral_violation_persisted=$(pod_has_container "$out_dir/evidence/ephemeral-violation.pod.json" debug-violation)

log_value() {
  local file=$1 pattern=$2
  [[ -s "$file" ]] && awk -v p="$pattern" '$1 == p {print $2; exit}' "$file" || true
}

ordinary_safe_cap=$(log_value "$out_dir/evidence/ordinary-safe.container.log" CapEff:)
ordinary_safe_nnp=$(log_value "$out_dir/evidence/ordinary-safe.container.log" NoNewPrivs:)
ordinary_violation_cap=$(log_value "$out_dir/evidence/ordinary-violation.container.log" CapEff:)
ordinary_violation_nnp=$(log_value "$out_dir/evidence/ordinary-violation.container.log" NoNewPrivs:)
ephemeral_safe_cap=$(log_value "$out_dir/evidence/ephemeral-safe.container.log" CapEff:)
ephemeral_safe_nnp=$(log_value "$out_dir/evidence/ephemeral-safe.container.log" NoNewPrivs:)
ephemeral_violation_cap=$(log_value "$out_dir/evidence/ephemeral-violation.container.log" CapEff:)
ephemeral_violation_nnp=$(log_value "$out_dir/evidence/ephemeral-violation.container.log" NoNewPrivs:)

jq -n \
  --arg product "$product" --argjson install "$install_id" --arg family "$family" --argjson repeat "$repeat_id" --arg namespace "$namespace" \
  --argjson ordinarySafeHttp "$ordinary_safe_status" --argjson ordinaryViolationHttp "$ordinary_violation_status" \
  --argjson ephemeralSafeHttp "$ephemeral_safe_status" --argjson ephemeralViolationHttp "$ephemeral_violation_status" \
  --argjson ordinarySafePersisted "$ordinary_safe_persisted" --argjson ordinaryViolationPersisted "$ordinary_violation_persisted" \
  --argjson ephemeralSafePersisted "$ephemeral_safe_persisted" --argjson ephemeralViolationPersisted "$ephemeral_violation_persisted" \
  --arg ordinarySafeState "$(<"$out_dir/evidence/ordinary-safe.runtime-state.txt")" \
  --arg ordinaryViolationState "$(<"$out_dir/evidence/ordinary-violation.runtime-state.txt")" \
  --arg ephemeralSafeState "$(<"$out_dir/evidence/ephemeral-safe.runtime-state.txt")" \
  --arg ephemeralViolationState "$(<"$out_dir/evidence/ephemeral-violation.runtime-state.txt")" \
  --arg ordinarySafeCap "$ordinary_safe_cap" --arg ordinarySafeNNP "$ordinary_safe_nnp" \
  --arg ordinaryViolationCap "$ordinary_violation_cap" --arg ordinaryViolationNNP "$ordinary_violation_nnp" \
  --arg ephemeralSafeCap "$ephemeral_safe_cap" --arg ephemeralSafeNNP "$ephemeral_safe_nnp" \
  --arg ephemeralViolationCap "$ephemeral_violation_cap" --arg ephemeralViolationNNP "$ephemeral_violation_nnp" \
  '{product:$product,install:$install,family:$family,repeat:$repeat,namespace:$namespace,
    httpStatus:{ordinarySafe:$ordinarySafeHttp,ordinaryViolation:$ordinaryViolationHttp,ephemeralSafe:$ephemeralSafeHttp,ephemeralViolation:$ephemeralViolationHttp},
    persisted:{ordinarySafe:$ordinarySafePersisted,ordinaryViolation:$ordinaryViolationPersisted,ephemeralSafe:$ephemeralSafePersisted,ephemeralViolation:$ephemeralViolationPersisted},
    runtime:{
      ordinarySafe:{state:$ordinarySafeState,capEff:$ordinarySafeCap,noNewPrivs:$ordinarySafeNNP},
      ordinaryViolation:{state:$ordinaryViolationState,capEff:$ordinaryViolationCap,noNewPrivs:$ordinaryViolationNNP},
      ephemeralSafe:{state:$ephemeralSafeState,capEff:$ephemeralSafeCap,noNewPrivs:$ephemeralSafeNNP},
      ephemeralViolation:{state:$ephemeralViolationState,capEff:$ephemeralViolationCap,noNewPrivs:$ephemeralViolationNNP}
    }}' >"$out_dir/summary.json"

find "$out_dir/evidence" -type f -empty -delete
cat "$out_dir/summary.json"
