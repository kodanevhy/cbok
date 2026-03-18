#!/usr/bin/env bash

check_if_committed() {
  local project_name="${1:?project_name required}"

  if [[ -z "${workspace:-}" ]]; then
    # keep old behavior: bbx scripts export workspace via python settings
    die "workspace variable is required (export workspace=\$(python -c 'from cbok import settings; print(settings.Workspace)'))"
  fi

  # Now we only support project from es.
  pushd "${workspace}/Cursor/es/${project_name}" >/dev/null || die "cannot locate project: ${workspace}/Cursor/es/${project_name}"
  local output flag
  output="$(git status 2>/dev/null || true)"
  popd >/dev/null || true

  flag="$(echo "$output" | grep -F "nothing to commit, working tree clean" || true)"
  if [[ -z "$flag" ]]; then
    die "you should commit the changes first"
  fi
}
