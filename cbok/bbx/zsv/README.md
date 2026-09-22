# ZSV compile helpers

`cbok zsv compile` builds changed ZSvirt Maven modules in a remote Docker
worktree container and can deploy the resulting JARs to a ZSphere/ZStack node.

## Remote Docker compile

The command always compiles through a Docker daemon. CBoK derives a stable
remote container name from the current worktree and reuses it on later runs:

```bash
cbok zsv compile --address 172.26.213.50 \
  --zsvirt-root /path/to/zsvirt \
  --ee-root /path/to/zsvirt-ee
```

Configure the remote daemon and build image in `[zsv_compile]`:

```ini
[zsv]
base_ref = origin/zsv_5.2.0

[zsv_compile]
remote_docker_host = tcp://172.26.50.70:2375
remote_docker_image = registry.docker.zstack.io:80/buildbin:debug9-zsvirt
remote_docker_platform = linux/amd64
remote_docker_workdir = /work
remote_docker_m2_volume = auto
remote_docker_min_free_gb = 20
```

Configure stable deployment paths in `[zsv_deploy]`:

```ini
[zsv_deploy]
remote_lib = /usr/local/zstack/apache-tomcat/webapps/zstack/WEB-INF/lib
site_packages = /var/lib/zstack/virtualenv/kvm/lib/python2.7/site-packages
kvm_virtualenv = /var/lib/zstack/virtualenv/kvm
backup_root = /var/lib/zstack/agent-replace-backup
```

Behavior:

- Reuses the worktree container on the configured remote Docker daemon.
- Pins `maven.mirror.zstack.io` to `172.24.201.252` when creating build/test
  containers so internal Maven dependencies do not rely on the daemon's DNS.
- Creates the worktree container and runs the full `./runMavenProfile ee` preparation
  only when the container has not completed full compile before.
- Streams local ZSvirt and `zsvirt-ee` worktrees into the container with
  `docker exec` tar pipes, so the remote daemon does not need local filesystem
  paths.
- Mounts a worktree-scoped Maven volume at `/var/maven/.m2` and links
  `/root/.m2` to it. `remote_docker_m2_volume = auto` uses the `zsv-m2`
  prefix; a custom value is treated as a prefix, not as one shared Maven
  repository across worktrees.
- Before creating a new worktree container, checks free space on the remote
  Docker root filesystem. If it is below `remote_docker_min_free_gb`, cbok stops
  and asks the AI to use the `cbok-zsv-container-cleanup` skill.
- Copies successful module build outputs to this command's local JAR copy
  directory and deploys from there, without writing build outputs back into the
  source worktree.
- Uses `[zsv] base_ref` as the shared upstream base for incremental compile
  changed-path detection.

Before selecting or building sources, `compile` fetches and rebases both
ZSvirt and EE onto `[zsv] base_ref`. `replace_agent` does the same for
`zsvirt-utility` before collecting changed files, and `replace_zstore` does so
for `zstack-store` before building. Agent `--dry-run` leaves Git state unchanged.
The base must be a configured remote branch such as `origin/zsv_5.2.0`.
The shared `check_if_committed` check rejects staged edits, unstaged edits, and
untracked files before fetching or rebasing. No changes are stashed automatically.
An existing unfinished Git operation, failed fetch, or conflict stops the
command. A failed rebase is aborted, restoring the original branch position.
These commands do not push rebased branches.

The main checkout owns `premium/`; it is included in source synchronization.
The external EE checkout is synchronized into `<main>/zsvirt-ee/`. Incremental
builds use `-Pee`, with built-in modules such as `premium/mevoco` and external
modules such as `zsvirt-ee/zvf` in the same reactor. EE builds use distinct
container and Maven-cache identities from the old repository layout. State
records use `zsvirt_root` / `zsvirt_head` and `ee_root` / `ee_head`, with separate
main and EE module selections. Upgrading an existing CBoK server database is
outside the scope of this change.

## Groovy integration tests

```bash
cbok zsv groovy_test --zsvirt-repo /path/to/zsvirt \
  --ee-repo /path/to/zsvirt-ee \
  --zsvirt-branch zsv_5.2.0 --ee-branch zsv_5.2.0 \
  --test-class org.zstack.test.integration.kvm.KvmTest
```

Both source repositories must have no staged, unstaged, or untracked changes;
the runner checks them before fetching or creating test worktrees.
Only committed sources are tested. Reused test worktrees are reset to their
recorded commits to remove generated harnesses from previous runs.
The runner creates worktrees for both repositories, preserves the main
repository's `premium/`, and links only `zsvirt-ee/`. It finds the requested
source in `test`, `tests/test-simple`, `tests/test-authentication`, or
`zsvirt-ee/tests-ee/test-ee`. The class must identify a unique module;
missing classes or duplicate fully qualified names fail before building,
with matching module paths reported for ambiguity.
The selected module determines its harness (`Test`, `Test` with `PremiumEnv`, or `TestEe`);
a Java package containing `premium` does not identify an external repository.
Both full and incremental compilation use the EE build profile.

Groovy tests refresh both source repositories before resolving the requested
refs, then rebase their detached test worktrees before generating test harnesses.
The source branches stay unchanged. Reuse records the source, upstream, and
rebased commits; a new source or upstream commit invalidates those worktrees.

PR references accept `zsvirt`, `zsvirt-ee`, `zsvirt-utility`, and `zstack-store`.
The old `zstack` and `premium` repository labels are no longer accepted.

## ZSphere upgrade schema file

`cbok zsv upgrade` downloads or reuses the exact BIN/ISO package on the primary
node, parses the target version from the package name or URL, and extracts the
matching `WEB-INF/classes/db/zsv/V<version>__*.sql` file. The matching SQL must
exist exactly once; missing or multiple matches stop the command. If that
script already has a successful `zstack.schema_version` row, cbok compares its
Flyway checksum before upgrade. If the checksum differs, cbok stops before
upgrade and asks the AI to use the `cbok-zsv-upgrade-db-repair` skill. cbok does
not apply schema SQL or run `flyway repair` automatically.

## Worktree container cleanup

List reusable worktree containers and their recorded PR/MR links first:

```bash
cbok zsv list_worktree_container_prs
```

The output includes each container's ZSvirt and EE roots, current branch, and
database-recorded PR/MR links. Review those PR/MR states outside cbok, then pass the
explicit container names to delete:

```bash
cbok zsv prune_worktree_containers \
  --container-name cbok-zsv-worktree-example-1234 \
  --execute
```

Without `--execute`, `prune_worktree_containers` only previews the selected
containers. Cleanup removes both the `cbok-zsv-worktree-*` container and the
recorded `zsv-m2-*` Maven volume, then removes the matching cbok state rows
after Docker cleanup succeeds. Both commands inspect records for
`remote_docker_host` in `[zsv_compile]`, matching the remote Docker daemon used
by compile.

PR/MR links are stored in `bbx_zsvworktreecontainerpullrequest` when the
worktree container record is created or refreshed by `cbok zsv compile`. Pass
them explicitly to compile with one `--pr-url <repo>=<url>[,<repo>=<url>...]`,
where `<repo>` is `zsvirt`, `zsvirt-ee`, `zsvirt-utility`, or `zstack-store`.
`cbok zsv groovy_test` does not refresh PR/MR links.
The list command only reads those recorded URLs; cbok does not query or decide
PR/MR state.

## ARM64 Docker buildbin

The legacy ARM64 buildbin context is retained under:

```text
cbok/bbx/zsv/docker/buildbin-arm64
```

Its Maven 3.5.2 cannot compile current ZSvirt sources: maven-compiler-plugin
3.13.0 requires Maven 3.6.3 or newer. Use the AMD64 build image configured above;
a compatible ARM64 replacement has not been verified.
