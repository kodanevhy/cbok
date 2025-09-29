FROM redhat/ubi9:latest

USER root

RUN yum -y install sudo wget gcc-c++ pcre pcre-devel zlib zlib-devel openssl openssl-devel procps-ng net-tools file

# You can download from https://www.python.org/ftp/python/3.9.6/Python-3.9.6.tar.xz
ADD Python-3.9.6.tar.xz /opt/

RUN cd /opt/Python-3.9.6/ && \
    ./configure --prefix=/ && make && make install && \
    rm -f /opt/Python-3.9.6.tar.xz

WORKDIR /root/cbok/

COPY . .

RUN python3 requirements/install.py

CMD ["python3", "manage.py", "runserver"]
