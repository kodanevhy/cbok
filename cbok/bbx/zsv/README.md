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
remote_docker_m2_volume = zsv-m2
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
- Mounts `remote_docker_m2_volume` at `/var/maven/.m2` and links `/root/.m2`
  to it.
- Copies successful module build outputs to this command's local JAR copy
  directory and deploys from there, without writing build outputs back into the
  source worktree.

## ARM64 Docker buildbin

For Docker-based compile on Apple Silicon, use the ARM64 buildbin context under:

```text
cbok/bbx/zsv/docker/buildbin-arm64
```

It keeps the legacy CentOS 7, Maven 3.5.2, JDK 8, and MariaDB 5.5 environment
shape while avoiding amd64 emulation when you build an ARM64 image for a remote
daemon that supports it.
