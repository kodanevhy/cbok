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

Run as a long-lived compile container:

```bash
docker run -d --name zsv-buildbin-arm64 --platform linux/arm64 \
  -v /Users/mizar/Workspace/Cursor/zs/zstack-workspace/zstack:/root/zstack \
  -v zstack-m2-arm64:/root/.m2 \
  -w /root/zstack \
  zstack-buildbin:debug7-arm64 sleep infinity
```

Configure `cbok.conf`:

```ini
[zsv_compile]
docker_container = zsv-buildbin-arm64
docker_zstack_root = /root/zstack
```

Quick verification:

```bash
docker exec zsv-buildbin-arm64 bash -lc \
  'uname -m; java -version; mvn -version; mysqladmin ping'
```
