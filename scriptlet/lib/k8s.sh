#!/usr/bin/env bash

k8s_kubectl() {
  # Unified entry: if address is empty -> local; else -> remote root@address
  local address="${1:-}"
  shift || true

  if [[ -n "$address" ]]; then
    remote_exec "$address" kubectl "$@"
  else
    kubectl "$@"
  fi
}

k8s_kubectl_apply_dir() {
  local address="${1:-}"
  local dir="${2:?dir required}"

  if [[ -n "$address" ]]; then
    remote_exec "$address" bash -lc "
      set -e
      for f in '${dir}'/*.yaml; do
        [ -f \"\$f\" ] || continue
        echo \"Applying \$f ...\"
        kubectl apply -f \"\$f\"
      done
    "
  else
    local f
    for f in "${dir}"/*.yaml; do
      [[ -f "$f" ]] || continue
      echo "Applying $f ..."
      kubectl apply -f "$f"
    done
  fi
}

k8s_kubectl_wait_ready() {
  local address="${1:-}"
  local namespace="${2:?namespace required}"
  local selector="${3:?selector required}"
  local timeout="${4:-300s}"

  if [[ -n "$address" ]]; then
    remote_exec "$address" kubectl wait --for=condition=Ready pod -l "${selector}" -n "${namespace}" --timeout="${timeout}"
  else
    kubectl wait --for=condition=Ready pod -l "${selector}" -n "${namespace}" --timeout="${timeout}"
  fi
}
