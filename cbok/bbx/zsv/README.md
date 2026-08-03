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
