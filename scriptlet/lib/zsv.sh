#!/usr/bin/env bash

zsv_node_status() {
  local label="${1:-}"

  echo "== ZSphere node ${label:-$(hostname)} =="
  echo "time: $(date -Is)"
  echo "hostname: $(hostname -f 2>/dev/null || hostname)"
  echo "kernel: $(uname -r)"
  echo "uptime: $(uptime -p 2>/dev/null || uptime)"

  if command -v zstack-upgrade >/dev/null 2>&1; then
    echo "zstack-upgrade: $(command -v zstack-upgrade)"
  else
    echo "zstack-upgrade: missing"
  fi

  if command -v zstack-ctl >/dev/null 2>&1; then
    echo "-- zstack-ctl status --"
    zstack-ctl status || true
  else
    echo "zstack-ctl: missing"
  fi
}

zsv_nodes_status() {
  local node

  [[ "$#" -gt 0 ]] || die "zsv_nodes_status requires at least one node"
  for node in "$@"; do
    ensure_remote_scriptlet "$node"
    remote_exec "$node" zsv_node_status "$node"
  done
}

zsv_authorize_public_keys() {
  local address="${1:?address required}"
  local local_keys="${2:?local public keys file required}"
  local remote_keys="/tmp/cbok-public-keys.$$"
  local remote_keys_q

  [[ -s "$local_keys" ]] || die "local public keys file is empty: $local_keys"

  _cbok_scp "$local_keys" "root@${address}:${remote_keys}"
  remote_keys_q=$(printf %q "$remote_keys")
  remote_bash "$address" "set -euo pipefail
keys_file=${remote_keys_q}
umask 077
mkdir -p /root/.ssh
touch /root/.ssh/authorized_keys
chmod 700 /root/.ssh
chmod 600 /root/.ssh/authorized_keys
while IFS= read -r key; do
  [[ -n \"\$key\" ]] || continue
  grep -qxF \"\$key\" /root/.ssh/authorized_keys || printf '%s\n' \"\$key\" >> /root/.ssh/authorized_keys
done < \"\$keys_file\"
rm -f \"\$keys_file\"
"
  log_info "installed SSH public keys on ${address}"
}

zsv_restart_mn() {
  local address="${1:?address required}"

  remote_bash "$address" "set -euo pipefail
if ! command -v zstack-ctl >/dev/null 2>&1; then
  echo 'zstack-ctl: missing' >&2
  exit 127
fi
zstack-ctl restart_node
zstack-ctl status
"
}

zsv_start_ui_if_needed() {
  local max_attempts="${1:-12}"
  local sleep_seconds="${2:-5}"
  local status
  local i

  require_cmd zstack-ctl

  status="$(zstack-ctl status 2>&1 || true)"
  printf '%s\n' "$status"
  if printf '%s\n' "$status" | grep -Eq 'UI status:.*Running'; then
    log_info "ZStack UI is already running"
    return 0
  fi

  log_info "starting ZStack UI"
  zstack-ctl start_ui
  for ((i = 1; i <= max_attempts; i++)); do
    status="$(zstack-ctl status 2>&1 || true)"
    printf '%s\n' "$status"
    if printf '%s\n' "$status" | grep -Eq 'UI status:.*Running'; then
      log_info "ZStack UI is running"
      return 0
    fi
    if [[ "$i" -lt "$max_attempts" ]]; then
      sleep "$sleep_seconds"
    fi
  done

  echo "ZStack UI did not reach Running status after start_ui" >&2
  return 1
}

zsv_ensure_ui_started() {
  local address="${1:?address required}"

  ensure_remote_scriptlet "$address"
  remote_exec "$address" zsv_start_ui_if_needed 12 5
}

_zsv_health_mysql() {
  local sql="${1:?sql required}"

  mysql -uroot -pzstack.mysql.password zstack -N -B -e "$sql" 2>/dev/null \
    || mysql -uzstack -pzstack.password zstack -N -B -e "$sql"
}

_zsv_unready_resources() {
  _zsv_health_mysql "
SELECT CONCAT('Host ', IFNULL(name, ''), ' ', IFNULL(managementIp, ''), ' state=', state, ' status=', status)
FROM HostVO
WHERE state <> 'Enabled' OR status <> 'Connected'
UNION ALL
SELECT CONCAT('PrimaryStorage ', IFNULL(name, ''), ' ', IFNULL(type, ''), ' state=', state, ' status=', status)
FROM PrimaryStorageVO
WHERE state <> 'Enabled' OR status <> 'Connected'
UNION ALL
SELECT CONCAT('BackupStorage ', IFNULL(name, ''), ' ', IFNULL(type, ''), ' state=', state, ' status=', status)
FROM BackupStorageVO
WHERE state <> 'Enabled' OR status <> 'Connected'
ORDER BY 1"
}

zsv_wait_local_resources_ready() {
  local timeout_seconds="${1:-1800}"
  local interval_seconds="${2:-10}"
  local deadline now pending

  require_cmd mysql
  deadline=$(($(date +%s) + timeout_seconds))

  while true; do
    if ! pending="$(_zsv_unready_resources 2>&1)"; then
      pending="resource health query failed: ${pending}"
    fi
    if [[ -z "$pending" ]]; then
      log_info "all hosts, primary storages, and backup storages are Enabled/Connected"
      return 0
    fi

    now=$(date +%s)
    if (( now >= deadline )); then
      echo "Timed out waiting for ZSphere resources to become Enabled/Connected after ${timeout_seconds}s:" >&2
      printf '%s\n' "$pending" >&2
      return 1
    fi

    log_info "waiting for ZSphere resources to become Enabled/Connected; pending:"
    printf '%s\n' "$pending"
    sleep "$interval_seconds"
  done
}

zsv_wait_resources_ready() {
  local address="${1:?address required}"
  local timeout_seconds="${2:-1800}"
  local interval_seconds="${3:-10}"

  ensure_remote_scriptlet "$address"
  remote_exec "$address" zsv_wait_local_resources_ready "$timeout_seconds" "$interval_seconds"
}

zsv_discover_management_nodes() {
  local address="${1:?address required}"

  remote_bash "$address" "set -euo pipefail
nodes=''
if command -v mysql >/dev/null 2>&1; then
  sql=\"SELECT hostName AS node FROM zstack.ManagementNodeVO WHERE hostName IS NOT NULL AND hostName <> ''
UNION
SELECT managementIp AS node FROM zstack.HostVO WHERE managementIp IS NOT NULL AND managementIp <> ''
AND status = 'Connected' AND hypervisorType = 'KVM'
ORDER BY node\"
  nodes=\$(mysql -uroot -pzstack.mysql.password -N -B -e \"\$sql\" \\
    2>/dev/null || true)
  if [[ -z \"\$nodes\" ]]; then
    nodes=\$(mysql -uzstack -pzstack.password -N -B -e \"\$sql\" \\
    2>/dev/null || true)
  fi
fi

if [[ -n \"\$nodes\" ]]; then
  printf '%s\n' \"\$nodes\" | awk 'NF && !seen[\$0]++'
  exit 0
fi

"
}

zsv_discover_healthy_kvm_hosts_from_primary() {
  local address="${1:?address required}"

  remote_bash "$address" "set -euo pipefail
rows=''
if command -v mysql >/dev/null 2>&1; then
  sql=\"SELECT IFNULL(managementIp, '') AS managementIp, IFNULL(state, '') AS state, IFNULL(status, '') AS status, IFNULL(name, '') AS name
FROM zstack.HostVO
WHERE hypervisorType = 'KVM'
  AND managementIp NOT IN ('172.24.192.148', '172.24.254.225')
ORDER BY managementIp\"
  rows=\$(mysql -uroot -pzstack.mysql.password -N -B -e \"\$sql\" \\
    2>/dev/null || true)
  if [[ -z \"\$rows\" ]]; then
    rows=\$(mysql -uzstack -pzstack.password -N -B -e \"\$sql\" \\
    2>/dev/null || true)
  fi
fi

if [[ -z \"\$rows\" ]]; then
  echo \"no KVM hosts found from primary node ${address}\" >&2
  exit 1
fi

bad=\$(printf '%s\n' \"\$rows\" | awk -F '\t' 'NF && (\$1 == \"\" || \$2 != \"Enabled\" || \$3 != \"Connected\") { printf \"  name=%s ip=%s state=%s status=%s\\n\", \$4, \$1, \$2, \$3 }')
if [[ -n \"\$bad\" ]]; then
  echo \"abnormal KVM hosts found from primary node ${address}:\" >&2
  printf '%s\n' \"\$bad\" >&2
  exit 1
fi

printf '%s\n' \"\$rows\" | awk -F '\t' 'NF && \$1 != \"\" { print \$1 }' | awk 'NF && !seen[\$0]++'
"
}

zsv_discover_ceph_primary_storage_nodes() {
  local address="${1:?address required}"

  remote_bash "$address" "set -euo pipefail
nodes=''
if command -v mysql >/dev/null 2>&1; then
  sql=\"SELECT DISTINCT hostname AS node FROM zstack.CephPrimaryStorageMonVO WHERE hostname IS NOT NULL AND hostname <> ''
ORDER BY node\"
  nodes=\$(mysql -uroot -pzstack.mysql.password -N -B -e \"\$sql\" \\
    2>/dev/null || true)
  if [[ -z \"\$nodes\" ]]; then
    nodes=\$(mysql -uzstack -pzstack.password -N -B -e \"\$sql\" \\
    2>/dev/null || true)
  fi
fi

if [[ -n \"\$nodes\" ]]; then
  printf '%s\n' \"\$nodes\" | awk 'NF && !seen[\$0]++'
  exit 0
fi

"
}

zsv_discover_zbs_primary_storage_nodes() {
  local address="${1:?address required}"

  remote_bash "$address" "set -euo pipefail
infos=''
if command -v mysql >/dev/null 2>&1; then
  sql=\"SELECT addonInfo FROM zstack.ExternalPrimaryStorageVO WHERE identity = 'zbs' AND addonInfo IS NOT NULL AND addonInfo <> ''\"
  infos=\$(mysql -uroot -pzstack.mysql.password -N -B -e \"\$sql\" \\
    2>/dev/null || true)
  if [[ -z \"\$infos\" ]]; then
    infos=\$(mysql -uzstack -pzstack.password -N -B -e \"\$sql\" \\
    2>/dev/null || true)
  fi
fi

if [[ -n \"\$infos\" ]]; then
  printf '%s\n' \"\$infos\" \\
    | grep -oE '\"addr\"[[:space:]]*:[[:space:]]*\"[^\"]+\"' \\
    | sed -E 's/.*\"addr\"[[:space:]]*:[[:space:]]*\"([^\"]+)\".*/\1/' \\
    | awk 'NF && !seen[\$0]++'
  exit 0
fi

"
}

zsv_discover_imagestore_bs_nodes_from_primary() {
  local address="${1:?address required}"

  remote_bash "$address" "set -euo pipefail
rows=''
if command -v mysql >/dev/null 2>&1; then
  sql=\"SELECT isbs.hostname FROM zstack.ImageStoreBackupStorageVO isbs
JOIN zstack.BackupStorageVO bs ON isbs.uuid = bs.uuid
WHERE bs.state = 'Enabled' AND bs.status = 'Connected'
  AND isbs.hostname IS NOT NULL AND isbs.hostname <> ''
ORDER BY isbs.hostname\"
  rows=\$(mysql -uroot -pzstack.mysql.password -N -B -e \"\$sql\" \\
    2>/dev/null || true)
  if [[ -z \"\$rows\" ]]; then
    rows=\$(mysql -uzstack -pzstack.password -N -B -e \"\$sql\" \\
    2>/dev/null || true)
  fi
fi

if [[ -n \"\$rows\" ]]; then
  printf '%s\n' \"\$rows\" | awk 'NF && !seen[\$0]++'
  exit 0
fi

"
}

_zsv_download_artifact() {
  local artifact_url="${1:?artifact_url required}"
  local artifact_name="${2:?artifact_name required}"
  local workdir="${3:?workdir required}"
  local expected_modified="${4:-}"
  local expected_size="${5:-}"
  local artifact_path="${workdir}/${artifact_name}"
  local meta_path="${artifact_path}.cbok-meta"

  mkdir -p "$workdir"

  if [[ -s "$artifact_path" ]]; then
    if [[ -z "$expected_modified" && -z "$expected_size" ]]; then
      log_info "reuse existing upgrade package without remote metadata: $artifact_path"
      return 0
    fi

    if [[ -f "$meta_path" ]] \
      && grep -Fxq "modified=${expected_modified}" "$meta_path" \
      && grep -Fxq "size=${expected_size}" "$meta_path"; then
      log_info "reuse existing upgrade package: $artifact_path"
      return 0
    fi

    log_info "cached upgrade package metadata changed, downloading again: $artifact_path"
  fi

  log_info "downloading upgrade package: $artifact_url"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --connect-timeout 20 -o "${artifact_path}.tmp" "$artifact_url"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "${artifact_path}.tmp" "$artifact_url"
  else
    die "curl or wget is required to download upgrade package"
  fi

  [[ -s "${artifact_path}.tmp" ]] || die "downloaded upgrade package is empty: ${artifact_path}.tmp"
  mv -f "${artifact_path}.tmp" "$artifact_path"
  {
    printf 'url=%s\n' "$artifact_url"
    printf 'name=%s\n' "$artifact_name"
    printf 'modified=%s\n' "$expected_modified"
    printf 'size=%s\n' "$expected_size"
  } > "$meta_path"
}

_zsv_download_iso() {
  _zsv_download_artifact "$@"
}

zsv_perform_upgrade() {
  local artifact_url="${1:?artifact_url required}"
  local artifact_name="${2:?artifact_name required}"
  local workdir="${3:-/var/lib/cbok/zsv-upgrade}"
  local expected_modified="${4:-}"
  local expected_size="${5:-}"
  local upgrade_type="${6:-iso}"

  _zsv_download_artifact "$artifact_url" "$artifact_name" "$workdir" \
    "$expected_modified" "$expected_size"

  export TERM="${TERM:-xterm}"
  case "$upgrade_type" in
    bin)
      log_info "running upgrade in $workdir: bash $artifact_name -u"
      (
        cd "$workdir"
        bash "$artifact_name" -u
      )
      ;;
    iso)
      require_cmd zstack-upgrade
      log_info "running upgrade in $workdir: zstack-upgrade $artifact_name"
      (
        cd "$workdir"
        zstack-upgrade "$artifact_name"
      )
      ;;
    *)
      die "unsupported upgrade type: $upgrade_type"
      ;;
  esac
}

zsv_upgrade_latest() {
  local primary_node="${1:?primary_node required}"
  local artifact_url="${2:?artifact_url required}"
  local artifact_name="${3:?artifact_name required}"
  local expected_modified="${4:-}"
  local expected_size="${5:-}"
  local upgrade_type="${6:-iso}"

  ensure_remote_scriptlet "$primary_node"
  remote_exec "$primary_node" zsv_perform_upgrade "$artifact_url" "$artifact_name" \
    /var/lib/cbok/zsv-upgrade "$expected_modified" "$expected_size" "$upgrade_type"
}

# --- ZStack dev: check package ZSV schema drift before upgrade ---

zsv_mysql_query() {
  local address="${1:?address required}"
  local sql="${2:?sql required}"
  local sql_q
  sql_q=$(printf %q "$sql")

  remote_bash "$address" "set -euo pipefail
require_cmd mysql
mysql -uzstack -pzstack.password -N -B -e ${sql_q}
"
}

_zsv_sql_string() {
  local value="${1:-}"
  printf "'"
  printf '%s' "$value" | sed "s/'/''/g"
  printf "'"
}

_zsv_expect_one_line() {
  local list_file="${1:?list file required}"
  local label="${2:?label required}"
  local content count
  content=$(awk 'NF' "$list_file" || true)
  if [[ -z "$content" ]]; then
    count=0
  else
    count=$(printf '%s\n' "$content" | wc -l | tr -d ' ')
  fi
  if [[ "$count" != "1" ]]; then
    echo "expected exactly one ${label}, found ${count}" >&2
    if [[ -n "$content" ]]; then
      printf '%s\n' "$content" | sed 's/^/  /' >&2 || true
    fi
    return 1
  fi
  printf '%s\n' "$content"
}

_zsv_unpack_installer_bin() {
  local bin_path="${1:?installer bin required}"
  local output_dir="${2:?output dir required}"
  local lines payload_lines

  [[ -f "$bin_path" ]] || die "installer bin missing: $bin_path"
  mkdir -p "$output_dir"
  lines=$(wc -l < "$bin_path" | tr -d ' ')
  payload_lines=$((lines - 11))
  (( payload_lines > 0 )) || die "invalid installer bin payload: $bin_path"
  tail -n "$payload_lines" "$bin_path" | tar x -C "$output_dir"
}

_zsv_versions_from_text() {
  local text="${1:-}"
  printf '%s\n' "$text" \
    | grep -Eo '(^|[^0-9])([0-9]+\.){2,3}[0-9]([^0-9]|$)' \
    | sed -E 's/^[^0-9]*//; s/[^0-9]*$//' \
    | sort -u || true
}

_zsv_artifact_schema_version() {
  local artifact_url="${1:?artifact url required}"
  local artifact_name="${2:?artifact name required}"
  local versions count

  versions=$(_zsv_versions_from_text "$artifact_name")
  count=$(printf '%s\n' "$versions" | awk 'NF' | wc -l | tr -d ' ')
  if [[ "$count" != "0" ]]; then
    _zsv_expect_one_line <(printf '%s\n' "$versions" | awk 'NF') \
      "ZSV schema version from artifact name"
    return $?
  fi

  versions=$(_zsv_versions_from_text "$artifact_url")
  _zsv_expect_one_line <(printf '%s\n' "$versions" | awk 'NF') \
    "ZSV schema version from artifact URL"
}

_zsv_extract_schema_from_war() {
  local war_path="${1:?zstack war required}"
  local sql_dir="${2:?sql dir required}"
  local source_label="${3:?source label required}"
  local workdir="${4:?workdir required}"
  local target_version="${5:?target version required}"
  local entries entry target

  require_cmd unzip
  [[ -f "$war_path" ]] || die "zstack.war missing: $war_path"
  mkdir -p "$sql_dir"
  entries="${workdir}/zsv-schema-entries.txt"
  unzip -Z -1 "$war_path" \
    | awk -v prefix="WEB-INF/classes/db/zsv/V${target_version}__" \
        'index($0, prefix) == 1 && $0 ~ /\.sql$/ && substr($0, length(prefix) + 1) !~ /\//' \
        > "$entries"
  if ! entry=$(_zsv_expect_one_line "$entries" "ZSV schema SQL for ${target_version}"); then
    return 1
  fi
  target="${sql_dir}/$(basename "$entry")"
  unzip -p "$war_path" "$entry" > "$target"
  printf '%s!%s\n' "$source_label" "$entry" > "${target}.source"
}

_zsv_extract_schema_from_tgz() {
  local tgz_path="${1:?zstack tgz required}"
  local sql_dir="${2:?sql dir required}"
  local workdir="${3:?workdir required}"
  local source_label="${4:?source label required}"
  local target_version="${5:?target version required}"
  local entries war_entry war_path

  [[ -f "$tgz_path" ]] || die "zstack tgz missing: $tgz_path"
  entries="${workdir}/zstack-war-entries.txt"
  tar -tzf "$tgz_path" | grep -E '(^|/)zstack\.war$' > "$entries" || true
  if ! war_entry=$(_zsv_expect_one_line "$entries" "zstack.war"); then
    return 1
  fi
  tar -xzf "$tgz_path" -C "$workdir" "$war_entry"
  war_path="${workdir}/${war_entry}"
  _zsv_extract_schema_from_war "$war_path" "$sql_dir" "$source_label" "$workdir" "$target_version"
}

_zsv_extract_schema_from_bin() {
  local bin_path="${1:?installer bin required}"
  local sql_dir="${2:?sql dir required}"
  local workdir="${3:?workdir required}"
  local target_version="${4:?target version required}"
  local unpack_dir entries tgz_path

  unpack_dir="${workdir}/bin-unpack"
  mkdir -p "$unpack_dir"
  _zsv_unpack_installer_bin "$bin_path" "$unpack_dir"
  entries="${workdir}/zstack-tgz-entries.txt"
  find "$unpack_dir" -maxdepth 1 -type f -name 'zstack*.tgz' -print > "$entries"
  if ! tgz_path=$(_zsv_expect_one_line "$entries" "zstack tgz"); then
    return 1
  fi
  _zsv_extract_schema_from_tgz "$tgz_path" "$sql_dir" "$workdir" "$bin_path" "$target_version"
}

_zsv_extract_schema_from_iso() {
  local iso_path="${1:?iso required}"
  local sql_dir="${2:?sql dir required}"
  local workdir="${3:?workdir required}"
  local target_version="${4:?target version required}"
  local mnt installer

  require_cmd mount
  [[ -f "$iso_path" ]] || die "ISO missing: $iso_path"
  mnt="${workdir}/iso-mnt"
  mkdir -p "$mnt"
  mount -o loop,ro "$iso_path" "$mnt"
  printf '%s\n' "$mnt" >> "${workdir}/mounts"
  installer="${mnt}/zstack-installer.bin"
  [[ -f "$installer" ]] || die "zstack-installer.bin not found in ISO: $iso_path"
  _zsv_extract_schema_from_bin "$installer" "$sql_dir" "$workdir" "$target_version"
}

_zsv_extract_schema_from_artifact() {
  local artifact_path="${1:?artifact path required}"
  local upgrade_type="${2:?upgrade type required}"
  local sql_dir="${3:?sql dir required}"
  local workdir="${4:?workdir required}"
  local target_version="${5:?target version required}"

  case "$upgrade_type" in
    bin)
      _zsv_extract_schema_from_bin "$artifact_path" "$sql_dir" "$workdir" "$target_version"
      ;;
    iso)
      _zsv_extract_schema_from_iso "$artifact_path" "$sql_dir" "$workdir" "$target_version"
      ;;
    *)
      die "unsupported upgrade type: $upgrade_type"
      ;;
  esac
}

_zsv_schema_mysql_local() {
  local sql="${1:?sql required}"
  _zsv_health_mysql "$sql"
}

_zsv_flyway_checksum() {
  local sql_file="${1:?sql file required}"
  python - "$sql_file" <<'PY'
import sys
import zlib

checksum = 0
first = True
with open(sys.argv[1], "rb") as f:
    for line in f:
        if line.endswith(b"\n"):
            line = line[:-1]
        if line.endswith(b"\r"):
            line = line[:-1]
        if first and line.startswith(b"\xef\xbb\xbf"):
            line = line[3:]
        first = False
        checksum = zlib.crc32(line, checksum) & 0xffffffff
if checksum >= 0x80000000:
    checksum -= 0x100000000
print(checksum)
PY
}

zsv_schema_precheck_local_artifact() {
  local artifact_url="${1:?artifact_url required}"
  local artifact_name="${2:?artifact_name required}"
  local workdir="${3:-/var/lib/cbok/zsv-upgrade}"
  local expected_modified="${4:-}"
  local expected_size="${5:-}"
  local upgrade_type="${6:-iso}"
  local db_address="${7:?db address required}"
  local artifact_path tmp sql_dir schema_file source_label script version script_sql row
  local migration_version version_rank applied_checksum applied_script resolved_checksum

  _zsv_download_artifact "$artifact_url" "$artifact_name" "$workdir" \
    "$expected_modified" "$expected_size"
  artifact_path="${workdir}/${artifact_name}"

  tmp=$(mktemp -d /tmp/cbok-zsv-schema-artifact.XXXXXX)
  _zsv_schema_precheck_cleanup() {
    if [[ -f "${tmp}/mounts" ]]; then
      tac "${tmp}/mounts" | while IFS= read -r mountpoint; do
        [[ -n "$mountpoint" ]] || continue
        umount "$mountpoint" >/dev/null 2>&1 || true
      done
    fi
    rm -rf "$tmp"
  }
  trap _zsv_schema_precheck_cleanup RETURN

  sql_dir="${tmp}/sql"
  mkdir -p "$sql_dir"
  if ! version=$(_zsv_artifact_schema_version "$artifact_url" "$artifact_name"); then
    return 1
  fi
  if ! _zsv_extract_schema_from_artifact "$artifact_path" "$upgrade_type" "$sql_dir" "$tmp" "$version"; then
    return 1
  fi
  if ! schema_file=$(_zsv_expect_one_line <(find "$sql_dir" -maxdepth 1 -type f -name '*.sql' -print | sort) \
      "extracted ZSV schema SQL"); then
    return 1
  fi
  script=$(basename "$schema_file")
  script_sql=$(_zsv_sql_string "$script")

  row=$(_zsv_schema_mysql_local "SELECT version, version_rank, IFNULL(checksum, ''), script FROM zstack.schema_version WHERE success = 1 AND script = ${script_sql}" || true)
  if [[ -z "$row" ]]; then
    log_info "Package ZSV schema migration ${script} has not been applied on ${db_address}; skip checksum precheck."
    return 0
  fi
  if ! row=$(_zsv_expect_one_line <(printf '%s\n' "$row" | awk 'NF') \
      "applied ZSV schema row for ${script}"); then
    return 1
  fi
  IFS=$'\t' read -r migration_version version_rank applied_checksum applied_script <<< "$row"
  source_label=$(cat "${schema_file}.source")
  resolved_checksum=$(_zsv_flyway_checksum "$schema_file")

  if [[ "$applied_checksum" == "$resolved_checksum" ]]; then
    log_info "ZSV schema checksum already matches ${source_label}."
    return 0
  fi

  printf '%s\n' "__CBOK_ZSV_SCHEMA_PRECHECK__"
  printf 'primary_node=%s\n' "$db_address"
  printf 'artifact_path=%s\n' "$artifact_path"
  printf 'sql_source=%s\n' "$source_label"
  printf 'script=%s\n' "$applied_script"
  printf 'version=%s\n' "${migration_version:-$version}"
  printf 'version_rank=%s\n' "$version_rank"
  printf 'applied_checksum=%s\n' "$applied_checksum"
  printf 'resolved_checksum=%s\n' "$resolved_checksum"
  return 1
}

zsv_schema_precheck_artifact() {
  local address="${1:?address required}"
  local artifact_url="${2:?artifact_url required}"
  local artifact_name="${3:?artifact_name required}"
  local expected_modified="${4:-}"
  local expected_size="${5:-}"
  local upgrade_type="${6:-iso}"

  ensure_remote_scriptlet "$address"
  remote_exec "$address" zsv_schema_precheck_local_artifact \
    "$artifact_url" "$artifact_name" /var/lib/cbok/zsv-upgrade \
    "$expected_modified" "$expected_size" "$upgrade_type" "$address"
}

zsv_schema_stage_sql_dir() {
  local address="${1:?address required}"
  local local_dir="${2:?local SQL dir required}"
  local remote_dir="${3:?remote SQL dir required}"

  [[ -d "$local_dir" ]] || die "local SQL dir missing: $local_dir"
  remote_mkdir "$address" "$remote_dir"
  _cbok_rsync -az --delete "${local_dir}/" "root@${address}:${remote_dir}/"
}

zsv_schema_flyway_migrate() {
  local address="${1:?address required}"
  local remote_dir="${2:?remote SQL dir required}"
  local dir_q url_q
  dir_q=$(printf %q "$remote_dir")
  url_q=$(printf %q "jdbc:mysql://${address}:3306/zstack")

  remote_bash "$address" "set -uo pipefail
flyway=
for candidate in \\
  /usr/local/zstack/apache-tomcat/webapps/zstack/WEB-INF/classes/tools/flyway-3.2.1/flyway \\
  /usr/local/zstack/apache-tomcat-*/webapps/zstack/WEB-INF/classes/tools/flyway-3.2.1/flyway \\
  /usr/local/zstack/upgrade/*/zstack/WEB-INF/classes/tools/flyway-3.2.1/flyway; do
  if [[ -f \"\$candidate\" ]]; then
    flyway=\"\$candidate\"
    break
  fi
done
[[ -n \"\$flyway\" ]] || die \"flyway not found under /usr/local/zstack\"
[[ -d ${dir_q} ]] || die \"schema SQL dir missing: ${dir_q}\"
bash \"\$flyway\" migrate -outOfOrder=true -user=zstack -password=zstack.password -url=${url_q} -locations=filesystem:${dir_q}/
"
}

# --- ZStack dev: backup Tomcat WEB-INF/lib and sync built JARs (used by cbok zsv compile) ---

zsv_tomcat_lib_ensure_backup() {
  local address="${1:?address required}"
  local lib="${2:?remote WEB-INF/lib required}"

  local lib_q backup_q
  lib_q=$(printf %q "$lib")
  backup_q=$(printf %q "${lib}.cbok-backup")
  remote_bash "$address" "set -euo pipefail
lib=${lib_q}
backup=${backup_q}
if [[ -e \"\$backup\" ]]; then
  log_info \"lib backup already exists, skip: \$backup\"
else
  [[ -d \"\$lib\" ]] || die \"remote lib dir missing: \$lib\"
  cp -a \"\$lib\" \"\$backup\"
  log_info \"created lib backup: \$backup\"
fi
"
}

zsv_scp_jars_to_remote() {
  local address="${1:?address required}"
  local remote_staging="${2:?remote staging dir required}"
  shift 2

  [[ "$#" -gt 0 ]] || die "zsv_scp_jars_to_remote: no local jar paths"
  remote_mkdir "$address" "$remote_staging"

  local f
  for f in "$@"; do
    [[ -f "$f" ]] || die "not a regular file: $f"
    _cbok_scp "$f" "root@${address}:${remote_staging}/"
  done
}

zsv_remote_install_jars_from_staging() {
  local address="${1:?address required}"
  local staging="${2:?remote staging dir required}"
  local lib="${3:?remote WEB-INF/lib required}"

  local sq lq
  sq=$(printf %q "$staging")
  lq=$(printf %q "$lib")
  remote_bash "$address" "set -euo pipefail
shopt -s nullglob
j=(\"${sq}\"/*.jar)
[[ \${#j[@]} -gt 0 ]] || die \"no jars under remote staging ${sq}\"
cp -f \"${sq}\"/*.jar \"${lq}/\"
rm -f \"${sq}\"/*.jar
	"
}

zsv_scp_web_classes_archive_to_remote() {
  local address="${1:?address required}"
  local remote_archive="${2:?remote archive required}"
  local local_archive="${3:?local archive required}"

  [[ -f "$local_archive" ]] || die "not a regular file: $local_archive"
  remote_mkdir "$address" "$(dirname "$remote_archive")"
  _cbok_scp "$local_archive" "root@${address}:${remote_archive}"
}

zsv_remote_install_web_classes_archive() {
  local address="${1:?address required}"
  local remote_archive="${2:?remote archive required}"
  local classes="${3:?remote WEB-INF/classes required}"

  local aq cq bq
  aq=$(printf %q "$remote_archive")
  cq=$(printf %q "$classes")
  bq=$(printf %q "${classes}.cbok-backup")
  remote_bash "$address" "set -euo pipefail
archive=${aq}
classes=${cq}
backup=${bq}
list=\$(mktemp)
[[ -f \"\$archive\" ]] || die \"remote archive missing: \$archive\"
[[ -d \"\$classes\" ]] || die \"remote classes dir missing: \$classes\"
mkdir -p \"\$backup\"
tar -tzf \"\$archive\" > \"\$list\"
while IFS= read -r rel; do
  [[ -n \"\$rel\" ]] || continue
  [[ \"\$rel\" == */ ]] && continue
  [[ \"\$rel\" != /* ]] || die \"archive contains absolute path: \$rel\"
  [[ \"\$rel\" != *..* ]] || die \"archive contains unsafe path: \$rel\"
  target=\"\$classes/\$rel\"
  if [[ -e \"\$target\" && ! -e \"\$backup/\$rel\" ]]; then
    mkdir -p \"\$backup/\$(dirname \"\$rel\")\"
    cp -a \"\$target\" \"\$backup/\$rel\"
  fi
done < \"\$list\"
tar --no-same-owner -xzf \"\$archive\" -C \"\$classes\"
while IFS= read -r rel; do
  [[ -n \"\$rel\" ]] || continue
  [[ \"\$rel\" == */ ]] && continue
  target=\"\$classes/\$rel\"
  [[ -e \"\$target\" ]] || continue
  chown --reference=\"\$classes\" \"\$target\" 2>/dev/null || true
done < \"\$list\"
rm -f \"\$list\"
rm -f \"\$archive\"
"
}

# --- ZStack dev: replace changed kvmagent/zstacklib runtime files (used by cbok zsv replace_agent) ---

zsv_agent_stage_archive() {
  local address="${1:?address required}"
  local local_archive="${2:?local archive required}"
  local remote_archive="${3:?remote archive required}"
  local remote_staging="${4:?remote staging dir required}"

  [[ -f "$local_archive" ]] || die "local archive missing: $local_archive"
  remote_mkdir "$address" "$(dirname "$remote_archive")"
  _cbok_scp "$local_archive" "root@${address}:${remote_archive}"

  local archive_q staging_q
  archive_q=$(printf %q "$remote_archive")
  staging_q=$(printf %q "$remote_staging")
  remote_bash "$address" "set -euo pipefail
rm -rf ${staging_q}
mkdir -p ${staging_q}
tar -xzf ${archive_q} -C ${staging_q}
rm -f ${archive_q}
find ${staging_q} -type f -print
"
}

zsv_agent_apply_staging() {
  local address="${1:?address required}"
  local script="${2:?remote apply script required}"

  remote_bash "$address" "$script"
}
