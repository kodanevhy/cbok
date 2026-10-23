# ZSV compile helpers

`cbok zsv compile` builds changed ZStack Maven modules in a remote Docker
worktree container and can deploy the resulting JARs to a ZSphere/ZStack node.

## Remote Docker compile

The command always compiles through a Docker daemon. CBoK derives a stable
remote container name from the current worktree and reuses it on later runs:

```bash
cbok zsv compile --address 172.26.213.50 \
  --zstack-root /path/to/zstack \
  --premium-root /path/to/premium
```

Configure the remote daemon and build image in `[zsv_compile]`:

```ini
[zsv]
base_ref = origin/feature-zsv-5.1.0-encryption
sync_repos = zsvirt:zsv_5.2.0,zsvirt-ee:zsv_5.2.0,zsvirt-utility:zsv_5.2.0,zstack:5.5.48,premium:5.5.48

[zsv_compile]
remote_docker_host = tcp://172.26.50.70:2375
remote_docker_image = registry.docker.zstack.io:80/buildbin:debug7
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
- Creates the worktree container and runs the full premium profile preparation
  only when the container has not completed full compile before.
- Streams local `zstack/` and `premium/` worktrees into the container with
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

## Upstream repository sync

Run `cbok zsv sync_repos` after selecting an editor and company with
`cbok workspace use`. The command locates
`<workspace>/<editor>/<company>/zstack-workspace`. Each comma-separated entry in
`[zsv] sync_repos` must specify `project:branch`; repository names alone are not
accepted. The command fetches all branches from each repository's `upstream`
remote, checks out the configured local branch, and fast-forwards it to the
matching upstream branch. A missing local branch is created from upstream.
It never fetches from `origin` or pushes to the personal fork.
After synchronization succeeds, a summary table lists each project, configured
branch, upstream ref, 12-character commit SHA, and result.

All configured repositories are checked and their upstream branches fetched
before any working tree is updated. Missing repositories or upstream branches,
uncommitted changes, unfinished Git operations, a configured branch checked out
in another worktree, and local commits or divergence on the configured branch
stop the command. Commits on other development branches are preserved. The
command does not reset, clean, or rebase local work. If an
update fails after validation, earlier updates may already have completed.

Branch, HEAD, and working tree state are rechecked after fetching and before
each update. Ignored local files that conflict with upstream changes also stop
the command. Fetching, checking out, and merging do not recurse into submodules.
An initialized submodule stays at its original commit when switching branches;
that expected gitlink difference is allowed, but local submodule edits are not.

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

The output includes each container's zstack/premium root, current branch, and
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
where `<repo>` is `zstack`, `premium`, `zstack-utility`, or `zstack-store`.
`cbok zsv groovy_test` does not refresh PR/MR links.
The list command only reads those recorded URLs; cbok does not query or decide
PR/MR state.

## ARM64 Docker buildbin

For Docker-based compile on Apple Silicon, use the ARM64 buildbin context under:

```text
cbok/bbx/zsv/docker/buildbin-arm64
```

It keeps the legacy CentOS 7, Maven 3.5.2, JDK 8, and MariaDB 5.5 environment
shape while avoiding amd64 emulation when you build an ARM64 image for a remote
daemon that supports it.
