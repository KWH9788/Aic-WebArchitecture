#!/usr/bin/env bash
set -euo pipefail

sql_file="${1:?Usage: run_remote_mysql_file.sh <sql-file>}"

cd ~/Aic-WebArchitecture

sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
  sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot --default-character-set=utf8mb4 aic_db' \
  < "$sql_file"
