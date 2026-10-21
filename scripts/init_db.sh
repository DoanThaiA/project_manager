#!/usr/bin/env bash
# Khởi tạo database project_manager trên PostgreSQL dùng chung (container carbon_analyst_db).
#   ./scripts/init_db.sh          # tạo user + database nếu chưa có, chạy migration (Alembic)
#   ./scripts/init_db.sh --demo   # kèm dữ liệu mẫu (db/seeds/02_demo_data.sql) nếu database còn trống
# Không bao giờ xoá dữ liệu có sẵn. Schema do Alembic quản lý (backend/migrations), API cũng tự
# chạy `alembic upgrade head` mỗi lần khởi động.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

CONTAINER="${PG_CONTAINER:-carbon_analyst_db}"
SUPERUSER="${PG_SUPERUSER:-postgres}"
DB="${PM_DB_NAME:-project_manager}"
: "${PM_DB_PASSWORD:?Đặt PM_DB_PASSWORD trong $ROOT/.env}"

psql_super() { docker exec -i "$CONTAINER" psql -v ON_ERROR_STOP=1 -q -U "$SUPERUSER" -d postgres "$@"; }
psql_pm() { docker exec -i "$CONTAINER" psql -v ON_ERROR_STOP=1 -q -U pm_user -d "$DB" "$@"; }

echo "→ Tạo user pm_user / database $DB nếu chưa có"
psql_super -v pw="$PM_DB_PASSWORD" -v db="$DB" <<'SQL'
SELECT format('CREATE ROLE pm_user LOGIN CREATEDB PASSWORD %L', :'pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pm_user') \gexec
SELECT format('CREATE DATABASE %I OWNER pm_user', :'db')
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db') \gexec
-- Server dùng chung chạy UTC; current_date (ngày log, quá hạn) cần theo giờ Việt Nam
SELECT format('ALTER DATABASE %I SET timezone TO %L', :'db', 'Asia/Ho_Chi_Minh') \gexec
SQL

was_empty="$(psql_pm -Atc "SELECT to_regclass('public.projects') IS NULL")"

echo "→ Chạy migration (alembic upgrade head)"
docker compose -f "$ROOT/docker-compose.yml" run --rm --build --no-deps api alembic upgrade head

if [[ "${1:-}" == "--demo" ]]; then
  if [[ "$was_empty" == "t" ]]; then
    psql_pm < "$ROOT/db/seeds/02_demo_data.sql"
    echo "  + dữ liệu mẫu (mật khẩu Demo@123)"
  else
    echo "  ! Database đã có dữ liệu — bỏ qua dữ liệu mẫu"
  fi
fi
echo "✓ Xong"
