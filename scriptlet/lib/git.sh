#!/usr/bin/env bash

git_rebase_worktree() (
  local repo_root="${1:?repo_root required}"
  local base_ref="${2:?base_ref required}"
  require_cmd git
  cd "$repo_root" || return 1
  check_if_committed "$PWD" || return 1

  local state_path
  for state_path in rebase-merge rebase-apply MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
    if [[ -e "$(git rev-parse --git-path "$state_path")" ]]; then
      log_warn "Unfinished Git operation in $repo_root; resolve it before building"
      return 1
    fi
  done
  if [[ -n "$(git diff --name-only --diff-filter=U)" ]]; then
    log_warn "Unresolved conflicts in $repo_root; resolve them before building"
    return 1
  fi
  if git merge-base --is-ancestor "$base_ref" HEAD; then
    log_info "$repo_root already contains $base_ref at $(git rev-parse --short HEAD)"
    return 0
  fi

  log_info "Rebasing $repo_root onto $base_ref"
  if ! git -c core.editor=true -c rebase.updateRefs=false -c rebase.autoStash=false rebase "$base_ref"; then
    if [[ -d "$(git rev-parse --git-path rebase-merge)" || -d "$(git rev-parse --git-path rebase-apply)" ]]; then
      if ! git rebase --abort; then
        log_warn "Could not abort rebase in $repo_root; resolve the Git state manually"
        return 1
      fi
    fi
    log_warn "Rebase failed in $repo_root; build stopped"
    return 1
  fi
  git merge-base --is-ancestor "$base_ref" HEAD || return 1
  log_info "Rebased $repo_root to $(git rev-parse --short HEAD)"
)

check_if_committed() {
  local project_name="${1:?project_name or repository path required}"
  local repo_root="$project_name"
  if [[ "$repo_root" != /* ]]; then
    if [[ -z "${workspace:-}" ]]; then
      log_warn "workspace is required when passing an ES project name"
      return 1
    fi
    repo_root="${workspace}/Cursor/es/${project_name}"
  fi

  require_cmd git
  local git_status
  git_status="$(git -C "$repo_root" status --porcelain --untracked-files=all --ignore-submodules=none)" || return 1
  if [[ -n "$git_status" ]]; then
    log_warn "Uncommitted changes in $repo_root; commit them before continuing"
    log_warn "$git_status"
    return 1
  fi
}
