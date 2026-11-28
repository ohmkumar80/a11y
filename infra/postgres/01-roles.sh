#!/bin/sh
# Runs once on first container start (docker-entrypoint-initdb.d).
# Three roles, deliberately different (see docs/PROJECT_PLAN.md 3.4):
#   a11y_owner - owns tables, runs migrations. FORCE RLS makes it subject to policies too.
#   a11y_app   - API and workers. Not the owner, NOBYPASSRLS.
#   a11y_admin - Super Admin cross-tenant reads. BYPASSRLS; each use is audit-logged.
set -eu
: "${A11Y_OWNER_PASSWORD:?}" "${A11Y_APP_PASSWORD:?}" "${A11Y_ADMIN_PASSWORD:?}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v DBNAME="$POSTGRES_DB" -v owner_pw="$A11Y_OWNER_PASSWORD" -v app_pw="$A11Y_APP_PASSWORD" -v admin_pw="$A11Y_ADMIN_PASSWORD" <<'SQL'
CREATE ROLE a11y_owner LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'owner_pw';
CREATE ROLE a11y_app   LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'app_pw';
CREATE ROLE a11y_admin LOGIN NOSUPERUSER BYPASSRLS   PASSWORD :'admin_pw';

ALTER DATABASE :"DBNAME" OWNER TO a11y_owner;
REVOKE ALL ON DATABASE :"DBNAME" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"DBNAME" TO a11y_owner, a11y_app, a11y_admin;

\connect :"DBNAME"
ALTER SCHEMA public OWNER TO a11y_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO a11y_app, a11y_admin;
-- Tables created later by a11y_owner are readable/writable by the app role only via these defaults.
ALTER DEFAULT PRIVILEGES FOR ROLE a11y_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO a11y_app;
ALTER DEFAULT PRIVILEGES FOR ROLE a11y_owner IN SCHEMA public
  GRANT SELECT ON TABLES TO a11y_admin;
ALTER DEFAULT PRIVILEGES FOR ROLE a11y_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO a11y_app;
SQL
