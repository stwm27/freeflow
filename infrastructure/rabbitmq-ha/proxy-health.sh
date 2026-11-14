#!/bin/sh
set -eu

printf 'show stat\n' |
    socat -T 2 - UNIX-CONNECT:/tmp/rabbitmq-haproxy.sock |
    awk -F, '
        $1 == "amqp" && $2 == "BACKEND" && $18 == "UP" { amqp = 1 }
        $1 == "management" && $2 == "BACKEND" && $18 == "UP" { management = 1 }
        END { exit !(amqp && management) }
    '
