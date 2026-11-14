#!/bin/sh
set -eu

cp /run/secrets/rabbitmq_cookie /var/lib/rabbitmq/.erlang.cookie
chown rabbitmq:rabbitmq /var/lib/rabbitmq/.erlang.cookie
chmod 600 /var/lib/rabbitmq/.erlang.cookie

exec docker-entrypoint.sh "$@"
