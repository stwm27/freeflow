FROM rabbitmq:4-management

USER root
COPY entrypoint.sh /usr/local/bin/flowrun-rabbitmq-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/flowrun-rabbitmq-entrypoint.sh \
    && chmod +x /usr/local/bin/flowrun-rabbitmq-entrypoint.sh \
    && ln -sf /var/lib/rabbitmq/.erlang.cookie /root/.erlang.cookie

ENTRYPOINT ["/usr/local/bin/flowrun-rabbitmq-entrypoint.sh"]
CMD ["rabbitmq-server"]
