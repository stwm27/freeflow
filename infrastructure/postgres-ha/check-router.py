import os
import sys

import psycopg


try:
    with psycopg.connect(
        host="127.0.0.1",
        port=5432,
        dbname="postgres",
        user="flowrun",
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=2,
        options="-c statement_timeout=2000",
    ) as connection:
        row = connection.execute("SELECT NOT pg_is_in_recovery()").fetchone()
        sys.exit(0 if row and row[0] else 1)
except psycopg.Error:
    sys.exit(1)
