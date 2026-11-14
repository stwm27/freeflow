FROM postgres:16

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv curl haproxy \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/patroni \
    && /opt/patroni/bin/pip install --no-cache-dir "patroni[psycopg3,etcd3]>=4.1,<4.2"

ENV PATH="/opt/patroni/bin:${PATH}"
ENV PGDATA=/var/lib/postgresql/data/pgdata

COPY patroni.yml /etc/patroni/patroni.yml
COPY haproxy.cfg /etc/patroni/haproxy.cfg
COPY post-init.sh /opt/flowrun/post-init.sh
COPY check-router.py /opt/flowrun/check-router.py

RUN sed -i 's/\r$//' /opt/flowrun/post-init.sh \
    && chmod +x /opt/flowrun/post-init.sh \
    && install -d -o postgres -g postgres -m 0700 /var/lib/postgresql/data

USER postgres
ENTRYPOINT ["patroni"]
CMD ["/etc/patroni/patroni.yml"]
