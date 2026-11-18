#!/bin/bash
# Airflow's metadata DB lives in the same Postgres instance (saves a container on small machines).
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER airflow WITH PASSWORD '${AIRFLOW_DB_PASSWORD}';
    CREATE DATABASE airflow OWNER airflow;
EOSQL
