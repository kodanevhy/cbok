# ZSV compile helpers

`cbok zsv compile` builds changed ZStack Maven modules and can deploy the
resulting JARs to a ZSphere/ZStack node.

## Docker tmpfs compile

Use this when the build must stay inside the Docker buildbin environment. The
container copies source into a Linux tmpfs, writes Maven `target/` files there,
then syncs successful build outputs back to the host checkout. This avoids the
slow Docker Desktop bind-mount path for Java/AspectJ small-file writes.

Add optional keys to `[zsv_compile]` in `cbok.conf`:

```ini
[zsv_compile]
docker_container = none

docker_tmpfs_enabled = true
docker_tmpfs_image = zstack-buildbin:debug7-arm64
docker_tmpfs_platform = linux/arm64
docker_tmpfs_size = 6g
docker_tmpfs_workdir = /work
docker_tmpfs_container_name = zsv-buildbin-arm64-tmpfs
docker_tmpfs_m2_volume = zsv-m2
docker_tmpfs_preload_m2 = true
docker_tmpfs_m2_source = ~/.m2/repository

# Optional when premium/ is a sibling of zstack/ instead of zstack/premium.
docker_tmpfs_premium_source = ../premium
```

Behavior:

- Runs a fresh container from `docker_tmpfs_image`.
- Mounts the host checkout read-only under `/src`.
- Mounts the host checkout read-write under `/out` only for final `target/`
  sync.
- Mounts `docker_tmpfs_m2_volume` at `/root/.m2`.
- Optionally preloads missing Maven artifacts from `docker_tmpfs_m2_source`.
- Copies `zstack/` and, when present, `premium/` into `docker_tmpfs_workdir`.
- Runs the normal Maven command from the copied workspace.

Benchmark on Apple Silicon for `./runMavenProfile premium` up to the current
`crypto` compile failure:

- Docker bind mount: Maven `Total time: 13:57 min`, wall time `844s`.
- Docker tmpfs: source copy `13s`, Maven `Total time: 03:18 min`, wall time
  `218s`.

## ARM64 Docker buildbin

For Docker-based compile on Apple Silicon, use the ARM64 buildbin context under:

```text
cbok/bbx/zsv/docker/buildbin-arm64
```

It keeps the legacy CentOS 7, Maven 3.5.2, JDK 8, and MariaDB 5.5 environment
shape while avoiding amd64 emulation.
