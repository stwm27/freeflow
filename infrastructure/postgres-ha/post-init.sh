#!/bin/sh
set -eu

psql "$1" -v ON_ERROR_STOP=1 <<'SQL'
SELECT 'CREATE DATABASE flowrun'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'flowrun')
\gexec
SQL