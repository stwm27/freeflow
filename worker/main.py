import asyncio
import json
import logging
import os
import socket

import aio_pika
from sqlalchemy import URL, create_engine, text
from sqlalchemy.exc import SQLAlchemyError


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


def execute_task(snapshot):
    if snapshot["task_type"] != "demo":
        raise ValueError(
            f"Unsupported task type: {snapshot['task_type']}"
        )

    return {
        "message": snapshot["parameters"].get(
            "message",
            "Demo task completed",
        ),
        "worker": socket.gethostname(),
    }


def process_run(run_id):
    select_query = text("""
        SELECT status, task_snapshot
        FROM task_runs
        WHERE id = :run_id
        FOR UPDATE
    """)

    start_query = text("""
        UPDATE task_runs
        SET status = 'running',
            started_at = clock_timestamp()
        WHERE id = :run_id
    """)

    finish_query = text("""
        UPDATE task_runs
        SET status = :status,
            result = CAST(:result AS JSONB),
            error = :error,
            finished_at = clock_timestamp()
        WHERE id = :run_id
    """)

    with engine.begin() as connection:
        row = connection.execute(
            select_query,
            {"run_id": run_id},
        ).mappings().one_or_none()

        if row is None:
            logger.warning("Run %s does not exist", run_id)
            return

        if row["status"] in ("succeeded", "failed"):
            logger.info("Run %s already finished, skipping", run_id)
            return

        connection.execute(start_query, {"run_id": run_id})

        status = "succeeded"
        result_json = None
        error = None

        try:
            result = execute_task(row["task_snapshot"])
            result_json = json.dumps(result)

        except Exception as exc:
            status = "failed"
            error = str(exc)
            logger.exception("Execution failed for run %s", run_id)

        connection.execute(
            finish_query,
            {
                "run_id": run_id,
                "status": status,
                "result": result_json,
                "error": error,
            },
        )

    logger.info("Run %s finished: %s", run_id, status)


async def main():
    connection = await aio_pika.connect_robust(
        host=os.environ["RABBITMQ_HOST"],
        login=os.environ["RABBITMQ_USER"],
        password=os.environ["RABBITMQ_PASSWORD"],
        timeout=10,
    )

    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=1)

        queue = await channel.declare_queue(
            QUEUE_NAME,
            durable=True,
            arguments={"x-queue-type": "quorum"},
        )

        logger.info("Worker started, waiting for messages")

        async with queue.iterator() as messages:
            async for message in messages:
                try:
                    payload = json.loads(message.body)
                    run_id = payload["run_id"]

                    if (
                        type(run_id) is not int
                        or not 0 < run_id < 2**63
                    ):
                        raise ValueError("Invalid run_id")

                except (ValueError, TypeError, KeyError):
                    logger.exception("Rejecting invalid message")
                    await message.reject(requeue=False)
                    continue

                async with message.process(requeue=True):
                    while True:
                        try:
                            await asyncio.to_thread(
                                process_run,
                                run_id,
                            )
                            break

                        except SQLAlchemyError:
                            logger.exception(
                                "Database error for run %s, retrying",
                                run_id,
                            )
                            await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())