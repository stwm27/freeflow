#!/bin/sh
set -eu

rm -f /tmp/firewall-ready

# Rules apply inside the network namespace shared with PostgreSQL.
iptables-restore -w 5 <<'RULES'
*filter
:INPUT DROP [0:0]
:FORWARD DROP [0:0]
:OUTPUT ACCEPT [0:0]
-A INPUT -i lo -j ACCEPT
-A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
-A INPUT -s 172.28.30.10/32 -p tcp --dport 5432 -j ACCEPT
-A INPUT -s 172.28.30.20/32 -p tcp --dport 5432 -j ACCEPT
-A INPUT -s 172.28.30.30/32 -p tcp --dport 5432 -j ACCEPT
COMMIT
RULES

touch /tmp/firewall-ready
echo "PostgreSQL firewall rules applied"
exec tail -f /dev/null
