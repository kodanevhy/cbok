#!/bin/bash
set -e

if [ "${1:0:1}" = '-' ]; then
  set -- mysqld_safe "$@"
fi

DATADIR="/var/lib/mysql"
FIRST_INIT=0

init_database() {
  if [ ! -d "$DATADIR/mysql" ]; then
    if [ -z "$MYSQL_ROOT_PASSWORD" ] && [ -z "$MYSQL_ALLOW_EMPTY_PASSWORD" ]; then
      echo >&2 'error: database is uninitialized and MYSQL_ROOT_PASSWORD not set'
      exit 1
    fi

    mysql_install_db --user=mysql --datadir="$DATADIR" >/tmp/mysql_install_db.log
    FIRST_INIT=1
  fi

  chown -R mysql:mysql "$DATADIR"
}

start_database() {
  /usr/bin/mysqld_safe --datadir="$DATADIR" >/tmp/mysql_start.log 2>&1 &

  for _ in $(seq 1 60); do
    if /usr/bin/mysqladmin ping >/tmp/mysql_ping.log 2>&1; then
      return 0
    fi
    sleep 1
  done

  cat /tmp/mysql_start.log >&2 || true
  cat /tmp/mysql_ping.log >&2 || true
  return 1
}

configure_database() {
  [ "$FIRST_INIT" -eq 1 ] || return 0

  tempSqlFile='/tmp/mysql-first-time.sql'
  cat > "$tempSqlFile" <<-EOSQL
DELETE FROM mysql.user ;
CREATE USER 'root'@'%' IDENTIFIED BY '${MYSQL_ROOT_PASSWORD}' ;
GRANT ALL ON *.* TO 'root'@'%' WITH GRANT OPTION ;
DROP DATABASE IF EXISTS test ;
EOSQL

  if [ "$MYSQL_DATABASE" ]; then
    echo "CREATE DATABASE IF NOT EXISTS \`$MYSQL_DATABASE\` ;" >> "$tempSqlFile"
    if [ "$MYSQL_CHARSET" ]; then
      echo "ALTER DATABASE \`$MYSQL_DATABASE\` CHARACTER SET \`$MYSQL_CHARSET\` ;" >> "$tempSqlFile"
    fi
    if [ "$MYSQL_COLLATION" ]; then
      echo "ALTER DATABASE \`$MYSQL_DATABASE\` COLLATE \`$MYSQL_COLLATION\` ;" >> "$tempSqlFile"
    fi
  fi

  if [ "$MYSQL_USER" ] && [ "$MYSQL_PASSWORD" ]; then
    echo "CREATE USER '$MYSQL_USER'@'%' IDENTIFIED BY '$MYSQL_PASSWORD' ;" >> "$tempSqlFile"
    if [ "$MYSQL_DATABASE" ]; then
      echo "GRANT ALL ON \`$MYSQL_DATABASE\`.* TO '$MYSQL_USER'@'%' ;" >> "$tempSqlFile"
    fi
  fi

  echo 'FLUSH PRIVILEGES ;' >> "$tempSqlFile"
  mysql < "$tempSqlFile"
}

case "$1" in
  mysqld|mysqld_safe)
    init_database
    exec "$@"
    ;;
  *)
    init_database
    start_database
    configure_database
    exec "$@"
    ;;
esac
