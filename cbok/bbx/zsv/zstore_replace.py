from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import shlex
import time


LOG = logging.getLogger(__name__)

DEFAULT_IMAGE = "golang:1.18-bullseye"
REMOTE_BIN_DIR = "/usr/local/zstack/imagestore/bin"


def _run(runner, command: str, *, purge_output: bool = False):
    return runner.run_command(
        ["bash", "-lc", command],
        cmd_purge_output=purge_output,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build(root: Path, runner, image: str) -> int:
    command = " ".join([
        "docker run --rm --platform linux/amd64",
        "-v", shlex.quote(f"{root}:/src"),
        "-w /src",
        shlex.quote(image),
        "bash -lc", shlex.quote("GOROOT=/usr/local/go make build ARCH=amd64"),
    ])
    return _run(runner, command).returncode


def _deploy_node(node: str, zstore: Path, zstcli: Path, runner, stamp: str) -> int:
    remote_stage = f"/tmp/cbok-zstore-{stamp}"
    copy_command = " ".join([
        "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
        shlex.quote(f"root@{node}"),
        shlex.quote(f"rm -rf {remote_stage} && mkdir -p {remote_stage}"),
        "&& scp -q -o BatchMode=yes -o StrictHostKeyChecking=no",
        shlex.quote(str(zstore)),
        shlex.quote(str(zstcli)),
        shlex.quote(f"root@{node}:{remote_stage}/"),
    ])
    result = _run(runner, copy_command)
    if result.returncode != 0:
        return result.returncode

    backup = f"{REMOTE_BIN_DIR}/backup-cbok-{stamp}"
    remote_script = f"""
set -euo pipefail
stage={shlex.quote(remote_stage)}
bin={shlex.quote(REMOTE_BIN_DIR)}
backup={shlex.quote(backup)}
init_script=/etc/rc.d/init.d/zstack-imagestorebackupstorage
mkdir -p "$backup"
cp -a "$bin/zstore" "$bin/zstcli" "$backup/"
has_service=0
systemctl cat zstack-imagestorebackupstorage.service >/dev/null 2>&1 && has_service=1
restart_imagestore() {{
  # Prefer the SysV init script's own restart: it stops the daemon via
  # `pgrep -x zstore` and frees the port before starting. `systemctl restart`
  # is unreliable here because the daemon runs in a `systemd-run --scope`
  # transient unit that the service unit does not track, so systemd skips the
  # stop step and `start` then fails with "port already in use".
  if [ -x "$init_script" ]; then
    "$init_script" restart
  else
    systemctl restart zstack-imagestorebackupstorage.service
  fi
  for _ in $(seq 1 30); do
    pgrep -x zstore >/dev/null 2>&1 && break
    sleep 1
  done
  pgrep -x zstore >/dev/null
}}
rollback() {{
  cp -af "$backup/zstore" "$bin/zstore"
  cp -af "$backup/zstcli" "$bin/zstcli"
  if [ "$has_service" -eq 1 ]; then
    restart_imagestore || true
  fi
}}
trap rollback ERR
install -m 0755 "$stage/zstore" "$bin/.zstore.cbok-new"
install -m 0755 "$stage/zstcli" "$bin/.zstcli.cbok-new"
mv -f "$bin/.zstore.cbok-new" "$bin/zstore"
mv -f "$bin/.zstcli.cbok-new" "$bin/zstcli"
if [ "$has_service" -eq 1 ]; then
  restart_imagestore
fi
sha256sum "$bin/zstore" "$bin/zstcli"
trap - ERR
rm -rf "$stage"
"""
    command = " ".join([
        "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
        shlex.quote(f"root@{node}"),
        shlex.quote(remote_script),
    ])
    return _run(runner, command, purge_output=True).returncode


def run_zstore_replace_flow(zstore_root: str, nodes: list[str], runner, image: str = DEFAULT_IMAGE) -> int:
    root = Path(os.path.realpath(zstore_root))
    if not (root / "src/image-store").is_dir():
        LOG.error("Invalid zstack-store root: %s", root)
        return 1
    if not nodes:
        LOG.error("No healthy KVM hosts discovered")
        return 1

    if _build(root, runner, image) != 0:
        return 1

    zstore = root / "build/out/zstore/zstore"
    zstcli = root / "build/out/zstore/zstcli"
    if not zstore.is_file() or not zstcli.is_file():
        LOG.error("Build did not produce zstore and zstcli under %s", root / "build/out/zstore")
        return 1

    LOG.info("zstore sha256=%s", _sha256(zstore))
    LOG.info("zstcli sha256=%s", _sha256(zstcli))
    stamp = time.strftime("%Y%m%d%H%M%S")
    for node in nodes:
        LOG.info("Deploying zstore to %s", node)
        if _deploy_node(node, zstore, zstcli, runner, stamp) != 0:
            LOG.error("zstore deployment failed on %s", node)
            return 1
    return 0
