#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
runner="$repo_root/experiments/ephemeral-api-coverage/run-live-matrix-case.sh"
result_root=${LIVE_RESULT_ROOT:-"$repo_root/experiments/ephemeral-api-coverage/results/2026-09-19-live-matrix"}
install_start=${INSTALL_START:-1}
install_end=${INSTALL_END:-3}
repeats=${REPEATS:-5}
products=${RUN_PRODUCTS:-"kyverno gatekeeper kubewarden"}
families=${RUN_FAMILIES:-"privileged escalation capabilities"}

kyverno_chart=${KYVERNO_CHART:-"$HOME/.cache/helm/repository/kyverno-3.9.1.tgz"}
kyverno_policies_chart=${KYVERNO_POLICIES_CHART:-"$HOME/.cache/helm/repository/kyverno-policies-3.9.1.tgz"}
gatekeeper_chart=${GATEKEEPER_CHART:-"$HOME/.cache/helm/repository/gatekeeper-3.23.1.tgz"}
kubewarden_chart=${KUBEWARDEN_CHART:-"$HOME/.cache/helm/repository/admission-controller-6.0.2.tgz"}
gatekeeper_source="$repo_root/work/gatekeeper-library-22a40962"
kubewarden_source="$repo_root/work/kubewarden-admission-6.0.2"

for required in "$runner" "$kyverno_chart" "$kyverno_policies_chart" "$gatekeeper_chart" "$kubewarden_chart"; do
  [[ -e "$required" ]] || { echo "missing required file: $required" >&2; exit 2; }
done

mkdir -p "$result_root"

wait_kyverno_policy() {
  local name=$1 ready=0
  for _ in $(seq 1 90); do
    ready=$(kubectl get validatingpolicy.policies.kyverno.io "$name" -o json 2>/dev/null | jq '.status.conditionStatus.ready // false' || printf 'false')
    [[ "$ready" == "true" ]] && return 0
    sleep 2
  done
  echo "Kyverno policy did not become ready: $name" >&2
  return 1
}

install_kyverno() {
  helm upgrade --install kyverno "$kyverno_chart" \
    --namespace kyverno --create-namespace --wait --timeout 10m \
    --set admissionController.replicas=1 \
    --set backgroundController.enabled=false \
    --set cleanupController.enabled=false \
    --set reportsController.enabled=false >/dev/null
}

install_gatekeeper() {
  helm upgrade --install gatekeeper "$gatekeeper_chart" \
    --namespace gatekeeper-system --create-namespace --wait --timeout 10m \
    --set replicas=1 --set auditInterval=0 >/dev/null

}

wait_kubewarden_policy() {
  local name=$1 active=false
  for _ in $(seq 1 120); do
    active=$(kubectl get clusteradmissionpolicy.policies.kubewarden.io "$name" -o json 2>/dev/null | jq '((.status.policyStatus // "") | ascii_downcase) == "active"' || printf 'false')
    [[ "$active" == "true" ]] && return 0
    sleep 2
  done
  echo "Kubewarden policy did not become active: $name" >&2
  return 1
}

install_kubewarden() {
  helm upgrade --install admission-controller "$kubewarden_chart" \
    --namespace kubewarden --create-namespace --wait --timeout 15m \
    --set recommendedPolicies.enabled=false \
    --set policyServer.enabled=true \
    --set policyServer.replicaCount=1 \
    --set auditScanner.enable=false \
    --set replicas=1 >/dev/null
}

prepare_family_kyverno() {
  local family=$1 policy
  case "$family" in
    privileged) policy=disallow-privileged-containers ;;
    escalation) policy=disallow-privilege-escalation ;;
    capabilities) policy=disallow-capabilities-strict ;;
  esac
  helm upgrade --install kyverno-policies "$kyverno_policies_chart" \
    --namespace kyverno --wait --timeout 5m \
    --set policyType=ValidatingPolicy \
    --set podSecurityStandard=custom \
    --set-json "podSecurityPolicies=[\"$policy\"]" \
    --set validationFailureAction=Enforce >/dev/null
  wait_kyverno_policy "$policy"
}

prepare_family_gatekeeper() {
  local family=$1 template constraint crd kind name template_name binding
  kubectl delete k8spspprivilegedcontainer.constraints.gatekeeper.sh psp-privileged-container --ignore-not-found --wait=true >/dev/null 2>&1 || true
  kubectl delete k8spspallowprivilegeescalationcontainer.constraints.gatekeeper.sh psp-allow-privilege-escalation-container --ignore-not-found --wait=true >/dev/null 2>&1 || true
  kubectl delete k8spspcapabilities.constraints.gatekeeper.sh psp-capabilities-restricted --ignore-not-found --wait=true >/dev/null 2>&1 || true
  case "$family" in
    privileged)
      template=template.yaml; constraint=constraint.yaml
      crd=k8spspprivilegedcontainer.constraints.gatekeeper.sh
      kind=k8spspprivilegedcontainer.constraints.gatekeeper.sh; name=psp-privileged-container
      template_name=k8spspprivilegedcontainer
      ;;
    escalation)
      template=allow-escalation-template.yaml; constraint=allow-escalation-constraint.yaml
      crd=k8spspallowprivilegeescalationcontainer.constraints.gatekeeper.sh
      kind=k8spspallowprivilegeescalationcontainer.constraints.gatekeeper.sh; name=psp-allow-privilege-escalation-container
      template_name=k8spspallowprivilegeescalationcontainer
      ;;
    capabilities)
      template=capabilities-template.yaml; constraint=capabilities-constraint.yaml
      crd=k8spspcapabilities.constraints.gatekeeper.sh
      kind=k8spspcapabilities.constraints.gatekeeper.sh; name=psp-capabilities-restricted
      template_name=k8spspcapabilities
      ;;
  esac
  kubectl apply -f "$gatekeeper_source/$template" >/dev/null
  kubectl wait --for=condition=Established "crd/$crd" --timeout=180s >/dev/null
  kubectl apply -f "$gatekeeper_source/$constraint" >/dev/null
  kubectl patch "$kind" "$name" --type merge -p '{"spec":{"enforcementAction":"deny"}}' >/dev/null
  binding="gatekeeper-${template_name}-${name}"
  for _ in $(seq 1 90); do
    kubectl get validatingadmissionpolicybinding "$binding" >/dev/null 2>&1 && break
    sleep 2
  done
  kubectl get validatingadmissionpolicybinding "$binding" >/dev/null
  sleep 3
}

prepare_family_kubewarden() {
  local family=$1 manifest name
  kubectl delete clusteradmissionpolicy.policies.kubewarden.io no-privileged-pod no-privilege-escalation drop-capabilities --ignore-not-found --wait=true >/dev/null 2>&1 || true
  case "$family" in
    privileged) manifest=pod-privileged.yaml; name=no-privileged-pod ;;
    escalation) manifest=allow-privilege-escalation.yaml; name=no-privilege-escalation ;;
    capabilities) manifest=capabilities.yaml; name=drop-capabilities ;;
  esac
  kubectl apply -f "$kubewarden_source/$manifest" >/dev/null
  wait_kubewarden_policy "$name"
}

collect_install_evidence() {
  local product=$1 install_id=$2 phase=$3
  local dir="$result_root/$product/install-$install_id/install-evidence/$phase"
  mkdir -p "$dir"
  kubectl version -o json >"$dir/kubernetes-version.json"
  kubectl get nodes -o json >"$dir/nodes.json"
  kubectl get validatingwebhookconfigurations -o json >"$dir/validating-webhooks.json"
  kubectl get mutatingwebhookconfigurations -o json >"$dir/mutating-webhooks.json"
  kubectl get validatingadmissionpolicies -o json >"$dir/validating-admission-policies.json" 2>/dev/null || true
  kubectl get validatingpolicies.policies.kyverno.io -o json >"$dir/kyverno-validating-policies.json" 2>/dev/null || true
  kubectl get validatingpolicybindings.policies.kyverno.io -o json >"$dir/kyverno-validating-policy-bindings.json" 2>/dev/null || true
  kubectl get constrainttemplates.templates.gatekeeper.sh -o json >"$dir/gatekeeper-constraint-templates.json" 2>/dev/null || true
  kubectl get constraints -o json >"$dir/gatekeeper-constraints.json" 2>/dev/null || true
  kubectl get clusteradmissionpolicies.policies.kubewarden.io -o json >"$dir/kubewarden-policies.json" 2>/dev/null || true
  kubectl get policyservers.policies.kubewarden.io -A -o json >"$dir/kubewarden-policy-servers.json" 2>/dev/null || true
  kubectl get pods -A -o json >"$dir/all-pods.json"
  case "$product" in
    kyverno)
      helm get values kyverno -n kyverno -o json >"$dir/engine-helm-values.json"
      helm get values kyverno-policies -n kyverno -o json >"$dir/policy-helm-values.json" 2>/dev/null || true
      kubectl logs -n kyverno -l app.kubernetes.io/component=admission-controller --all-containers --prefix --tail=-1 >"$dir/engine.log" 2>"$dir/engine-log.stderr" || true
      ;;
    gatekeeper)
      helm get values gatekeeper -n gatekeeper-system -o json >"$dir/engine-helm-values.json"
      kubectl logs -n gatekeeper-system -l control-plane=controller-manager --all-containers --prefix --tail=-1 >"$dir/engine.log" 2>"$dir/engine-log.stderr" || true
      ;;
    kubewarden)
      helm get values admission-controller -n kubewarden -o json >"$dir/engine-helm-values.json"
      kubectl logs -n kubewarden --all-containers --prefix --tail=-1 >"$dir/engine.log" 2>"$dir/engine-log.stderr" || true
      ;;
  esac
  find "$dir" -type f -empty -delete
}

for product in $products; do
  for install_id in $(seq "$install_start" "$install_end"); do
    cluster="live-${product}-${install_id}"
    echo "[$(date -Iseconds)] creating $cluster"
    kind delete cluster --name "$cluster" >/dev/null 2>&1 || true
    kind create cluster --name "$cluster" --image kindest/node:v1.35.8 --wait 180s >/dev/null
    echo "[$(date -Iseconds)] installing $product install $install_id"
    "install_$product"
    collect_install_evidence "$product" "$install_id" engine

    for family in $families; do
      echo "[$(date -Iseconds)] activating $product family=$family"
      "prepare_family_$product" "$family"
      collect_install_evidence "$product" "$install_id" "$family-before"
      for repeat_id in $(seq 1 "$repeats"); do
        echo "[$(date -Iseconds)] running $product install=$install_id family=$family repeat=$repeat_id"
        LIVE_RESULT_ROOT="$result_root" "$runner" "$product" "$install_id" "$family" "$repeat_id" >/dev/null
        jq -r '"result ordinary=" + (.httpStatus.ordinaryViolation|tostring) + " ephemeral=" + (.httpStatus.ephemeralViolation|tostring) + " stored=" + (.persisted.ephemeralViolation|tostring) + " runtime=" + .runtime.ephemeralViolation.state' \
          "$result_root/$product/install-$install_id/$family/repeat-$repeat_id/summary.json"
      done
      collect_install_evidence "$product" "$install_id" "$family-after"
    done
    kind delete cluster --name "$cluster" >/dev/null
  done
done

echo "[$(date -Iseconds)] live study complete: $result_root"
