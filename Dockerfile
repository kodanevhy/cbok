FROM redhat/ubi9:latest AS base

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
    openssl openssl-devel procps-ng net-tools file xz xz-libs cronie

# You can download from https://www.python.org/ftp/python/3.9.6/Python-3.9.6.tar.xz
ADD static/Python-3.9.6.tar.xz /opt/

RUN cd /opt/Python-3.9.6/ && \
    ./configure --prefix=/opt/python3.9.6 --enable-optimizations && make -j$(nproc) && make altinstall && \
    rm -f /opt/Python-3.9.6.tar.xz && rm -rf /opt/Python-3.9.6/

RUN ln -sf /opt/python3.9.6/bin/python3.9 /usr/bin/python3 && \
    ln -sf /opt/python3.9.6/bin/pip3.9 /usr/bin/pip3

FROM base AS cbok

WORKDIR /root/cbok/

COPY requirements.txt .
COPY requirements/ requirements
RUN pip3 install -r requirements.txt

COPY . .

RUN python3 manage.py makemigrations user && \
    python3 manage.py makemigrations xadmin && \
    python3 manage.py makemigrations bbx && \
    python3 manage.py makemigrations alert && \
    python3 manage.py migrate

RUN python3 manage.py crontab add

RUN cat > /opt/cbok.sh <<EOF
#!/bin/bash

set -ex

/usr/sbin/crond -n -x ext,sch,proc | tee /var/log/cron.log &

python3 manage.py runserver 0.0.0.0:8000 --noreload
EOF

CMD ["bash", "/opt/cbok.sh"]

EXPOSE 8000
