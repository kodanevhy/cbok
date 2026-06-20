# ZSV buildbin arm64

ARM64 replacement build context for the old `registry.docker.zstack.io:80/buildbin:debug7`
container used by `cbok zsv compile` on Apple Silicon hosts.

The original `buildbin:debug7` image is `linux/amd64`. Running it on an
Apple Silicon Mac forces emulation and makes local ZStack Maven builds slow and
hot. This context rebuilds the required Java compile environment as `linux/arm64`
while keeping the legacy CentOS 7 and MariaDB 5.5 shape.

Included:

- CentOS 7 AltArch (`aarch64`)
- OpenJDK 8
- Apache Maven 3.5.2
- MariaDB 5.5.68
- Git, GCC/G++, make, rsync, zip/unzip, curl/wget, SSH client
- UTF-8 locale

Build:

```bash
docker buildx build --platform linux/arm64 --load \
  -t zstack-buildbin:debug7-arm64 \
  cbok/bbx/zsv/docker/buildbin-arm64
```

Use it through the remote Docker compile settings:

```bash
cbok zsv compile --address 172.26.213.50 \
  --zstack-root /path/to/zstack \
  --premium-root /path/to/premium \
  --docker-container zsv-buildbin-arm64
```

Configure `cbok.conf`:

```ini
[zsv_compile]
remote_docker_host = tcp://172.26.50.70:2375
remote_docker_image = zstack-buildbin:debug7-arm64
remote_docker_platform = linux/arm64
remote_docker_workdir = /work
remote_docker_m2_volume = zstack-m2-arm64
```

Quick verification:

```bash
DOCKER_HOST=tcp://172.26.50.70:2375 docker exec zsv-buildbin-arm64 bash -lc \
  'uname -m; java -version; mvn -version; mysqladmin ping'
```
