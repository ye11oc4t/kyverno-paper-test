#!/usr/bin/env bash
set -euo pipefail
STUDY_CACHE=/root/.cache/kyverno-paper-study
mkdir -p "$STUDY_CACHE/bin" "$STUDY_CACHE/vendor"
curl --fail --location --silent --show-error --retry 2 https://github.com/kubernetes-sigs/kind/releases/download/v0.33.0/kind-linux-amd64 -o "$STUDY_CACHE/bin/kind"
printf '%s  %s\n' aee6151561422756b764a4ae28e7f44cda5af5a9eead3cc9985112b1de8d8e0d "$STUDY_CACHE/bin/kind" | sha256sum --check
curl --fail --location --silent --show-error --retry 2 https://dl.k8s.io/release/v1.35.8/bin/linux/amd64/kubectl -o "$STUDY_CACHE/bin/kubectl"
curl --fail --location --silent --show-error --retry 2 https://dl.k8s.io/release/v1.35.8/bin/linux/amd64/kubectl.sha256 -o "$STUDY_CACHE/bin/kubectl.sha256"
printf '%s  %s\n' "$(cat "$STUDY_CACHE/bin/kubectl.sha256")" "$STUDY_CACHE/bin/kubectl" | sha256sum --check
chmod +x "$STUDY_CACHE/bin/kind" "$STUDY_CACHE/bin/kubectl"
curl --fail --location --silent --show-error --retry 2 https://github.com/kyverno/kyverno/releases/download/v1.19.1/install.yaml -o "$STUDY_CACHE/vendor/kyverno-v1.19.1.yaml"
curl --fail --location --silent --show-error --retry 2 https://raw.githubusercontent.com/open-policy-agent/gatekeeper/v3.23.1/deploy/gatekeeper.yaml -o "$STUDY_CACHE/vendor/gatekeeper-v3.23.1.yaml"
printf '%s  %s\n' d3322cb346d3d42dd0f41e230b0d1d7bc5619960e1c36fdac4d9151d724b88e6 "$STUDY_CACHE/vendor/kyverno-v1.19.1.yaml" | sha256sum --check
printf '%s  %s\n' 3c178abe6de4dcdcd2810c2945468a0d7a15ccf0036e324b73308643e94d6f72 "$STUDY_CACHE/vendor/gatekeeper-v3.23.1.yaml" | sha256sum --check
docker pull kindest/node:v1.35.8@sha256:07b2536e30b803ed61d1677a79df6115f798ce64c80f9e22f6ed45afd09323c0
docker pull registry.k8s.io/pause:3.10@sha256:ee6521f290b2168b6e0935a181d4cff9be1ac3f505666ef0e3c98fae8199917a
docker tag registry.k8s.io/pause:3.10@sha256:ee6521f290b2168b6e0935a181d4cff9be1ac3f505666ef0e3c98fae8199917a study.local/approved/pause:3.10
docker tag registry.k8s.io/pause:3.10@sha256:ee6521f290b2168b6e0935a181d4cff9be1ac3f505666ef0e3c98fae8199917a study.local/alternate/pause:3.10
"$STUDY_CACHE/bin/kind" version
"$STUDY_CACHE/bin/kubectl" version --client -o json
sha256sum "$STUDY_CACHE/vendor/"*.yaml
