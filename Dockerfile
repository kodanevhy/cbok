# NOTE:
# *base* is used to build whole image: docker build --platform linux/amd64 --build-arg STAGE_SECOND_BASE_IMAGE=base -t docker.io/kodanevhy/cbok:latest .
# stage 1: docker build --target base --platform linux/amd64 -t docker.io/kodanevhy/cbok-base:latest .
# stage 2: docker build --platform linux/amd64 --build-arg STAGE_SECOND_BASE_IMAGE=docker.io/kodanevhy/cbok-base:latest -t docker.io/kodanevhy/cbok:latest .


ARG STAGE_FIRST_BASE_IMAGE=redhat/ubi9:latest
ARG STAGE_SECOND_BASE_IMAGE=cbok-base:latest

FROM ${STAGE_FIRST_BASE_IMAGE} AS base

USER root

ENV TZ=Asia/Shanghai

RUN mkdir -p ~/.pip/
RUN cat > ~/.pip/pip.conf <<EOF
[global]
index-url = https://pypi.doubanio.com/simple
trusted-host = pypi.doubanio.com
EOF

RUN yum -y install tk-devel sqlite-devel ncurses-devel \
    xz-devel libffi-devel bzip2-devel sudo wget gcc-c++ pcre pcre-devel zlib zlib-devel \
    openssl openssl-devel procps-ng net-tools file xz xz-libs patch

# You can download from https://www.python.org/ftp/python/3.12.10/Python-3.12.10.tar.xz
ADD static/Python-3.12.10.tar.xz /opt/

RUN cd /opt/Python-3.12.10/ && \
    ./configure --prefix=/opt/python3.12.10 --enable-optimizations && make -j$(nproc) && make altinstall && \
    rm -f /opt/Python-3.12.10.tar.xz && rm -rf /opt/Python-3.12.10/

RUN ln -sf /opt/python3.12.10/bin/python3.12 /usr/bin/python3 && \
    ln -sf /opt/python3.12.10/bin/pip3.12 /usr/bin/pip3

FROM ${STAGE_SECOND_BASE_IMAGE} AS cbok

WORKDIR /root/cbok/

COPY requirements.txt .
RUN pip3 install -r requirements.txt

COPY . .

EXPOSE 8000
