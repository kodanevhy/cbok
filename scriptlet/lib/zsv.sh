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

# --- ZStack dev: repair local-branch ZSV schema drift before ISO upgrade ---

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

zsv_schema_apply_sql_file() {
  local address="${1:?address required}"
  local local_sql="${2:?local SQL file required}"
  local remote_sql="${3:-/tmp/cbok-zsv-schema-repair.sql}"

  [[ -f "$local_sql" ]] || die "local SQL file missing: $local_sql"
  _cbok_scp "$local_sql" "root@${address}:${remote_sql}"

  local remote_sql_q
  remote_sql_q=$(printf %q "$remote_sql")
  remote_bash "$address" "set -euo pipefail
require_cmd mysql
log_info \"applying schema repair SQL: ${remote_sql_q}\"
mysql -uzstack -pzstack.password < ${remote_sql_q}
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
