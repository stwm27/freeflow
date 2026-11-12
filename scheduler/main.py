import asyncio
import json
import logging
import os

import aio_pika
from sqlalchemy import URL, create_engine, text


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

database_url = URL.create(
    drivername="postgresql+psycopg",
    username=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PASSWORD"],
    host=os.environ["POSTGRES_HOST"],
    port=5432,
    database=os.environ["POSTGRES_DB"],
)

engine = create_engine(
    database_url,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 5},
)

QUEUE_NAME = "flowrun.tasks"


async def publish_one(channel, queue_name):
    select_query = text("""
        SELECT id
        FROM task_runs
        WHERE status = 'pending'
        ORDER BY id
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    """)

    update_query = text("""
        UPDATE task_runs
        SET status = 'queued',
            published_at = NOW()
        WHERE id = :run_id
    """)

    with engine.begin() as connection:
        run_id = connection.execute(select_query).scalar_one_or_none()

        if run_id is None:
            return False

        message = aio_pika.Message(
            body=json.dumps({"run_id": run_id}).encode("utf-8"),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=str(run_id),
        )

        await channel.default_exchange.publish(
            message,
            routing_key=queue_name,
            mandatory=True,
            timeout=10,
        )

        connection.execute(update_query, {"run_id": run_id})

    logger.info("Published run %s", run_id)
    return True


async def main():
    connection = await aio_pika.connect_robust(
        host=os.environ["RABBITMQ_HOST"],
        login=os.environ["RABBITMQ_USER"],
        password=os.environ["RABBITMQ_PASSWORD"],
        timeout=10,
    )

    async with connection:
        channel = await connection.channel(
            publisher_confirms=True,
            on_return_raises=True,
        )

        queue = await channel.declare_queue(
            QUEUE_NAME,
            durable=True,
            arguments={"x-queue-type": "quorum"},
        )

        logger.info("Scheduler started")

        while True:
            try:
                await channel.ready()
                published = await publish_one(channel, queue.name)

                if not published:
                    await asyncio.sleep(1)

            except Exception:
                logger.exception("Publishing failed, retrying in 3 seconds")
                await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())