FROM --platform=linux/arm64 centos:7

ENV container=docker \
    LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    JAVA_HOME=/etc/alternatives/jre \
    M2_HOME=/usr/share/apache-maven \
    MAVEN_HOME=/usr/share/apache-maven \
    MYSQL_ALLOW_EMPTY_PASSWORD=yes \
    MYSQL_ROOT_PASSWORD=

ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/share/apache-maven/bin

RUN set -eux; \
    for f in /etc/yum.repos.d/*.repo; do \
      sed -i 's/^mirrorlist=/#mirrorlist=/' "$f"; \
      sed -i 's|^#baseurl=http://mirror.centos.org/altarch/|baseurl=http://vault.centos.org/altarch/|' "$f"; \
      sed -i 's|^#baseurl=http://mirror.centos.org/centos/|baseurl=http://vault.centos.org/centos/|' "$f"; \
    done; \
    yum clean all; \
    yum -y install \
      java-1.8.0-openjdk-devel \
      git gcc gcc-c++ make \
      glibc-devel glibc-static \
      python python2-pip \
      rsync zip unzip tar curl wget which findutils coreutils \
      openssh-clients \
      mariadb mariadb-server; \
    curl -fsSL https://archive.apache.org/dist/maven/maven-3/3.5.2/binaries/apache-maven-3.5.2-bin.tar.gz -o /tmp/apache-maven-3.5.2-bin.tar.gz; \
    tar -xzf /tmp/apache-maven-3.5.2-bin.tar.gz -C /usr/share; \
    ln -s /usr/share/apache-maven-3.5.2 /usr/share/apache-maven; \
    ln -s /usr/share/apache-maven/bin/mvn /usr/bin/mvn; \
    ln -s /usr/share/apache-maven/bin/mvnDebug /usr/bin/mvnDebug; \
    rm -f /tmp/apache-maven-3.5.2-bin.tar.gz; \
    yum clean all; \
    rm -rf /var/cache/yum

RUN localedef -i en_US -f UTF-8 en_US.UTF-8 || true

COPY docker-entrypoint.sh /docker-entrypoint.sh

RUN chmod +x /docker-entrypoint.sh

WORKDIR /root/repo
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["bash"]
