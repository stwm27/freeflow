import json
import os
from datetime import datetime
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import URL, create_engine, text

from redis import Redis


app = FastAPI(
    title="FlowRun API",
    version="0.1.0",    
    description="Distributed Task Execution Platform"
)

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

cache = Redis.from_url(
    os.environ["REDIS_URL"],
    decode_responses=True,
    socket_connect_timeout=3,
    socket_timeout=3,
)

class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    task_type: Literal["http_check", "demo"]
    parameters: dict[str, Any] = Field(default_factory=dict)


class TaskResponse(BaseModel):
    id: int
    name: str
    task_type: str
    parameters: dict[str, Any]
    created_at: datetime

class RunResponse(BaseModel):
    id: int
    task_id: int | None
    task_snapshot: dict[str, Any]
    status: str
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    published_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


@app.get("/hello")
def hello():
    return {"message": "Hello from FlowRun!"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/tasks", response_model=TaskResponse, status_code=201)
def create_task(task: TaskCreate):
    query = text("""
        INSERT INTO tasks (name, task_type, parameters)
        VALUES (:name, :task_type, CAST(:parameters AS JSONB))
        RETURNING id, name, task_type, parameters, created_at
    """)

    values = {
        "name": task.name,
        "task_type": task.task_type,
        "parameters": json.dumps(task.parameters),
    }

    with engine.begin() as connection:
        result = connection.execute(query, values)
        created_task = dict(result.mappings().one())

    return created_task


@app.get("/tasks", response_model=list[TaskResponse])
def list_tasks(limit: int = Query(default=100, ge=1, le=1000)):
    query = text("""
        SELECT id, name, task_type, parameters, created_at
        FROM tasks
        ORDER BY id DESC
        LIMIT :limit
    """)

    with engine.connect() as connection:
        result = connection.execute(query, {"limit": limit})
        tasks = [dict(row) for row in result.mappings()]

    return tasks

@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, response: Response):
    cache_key = f"task:{task_id}"
    cached_task = cache.get(cache_key)

    if cached_task is not None:
        response.headers["X-Cache"] = "HIT"
        return TaskResponse.model_validate_json(cached_task)

    query = text("""
        SELECT id, name, task_type, parameters, created_at
        FROM tasks
        WHERE id = :task_id
        FOR SHARE
    """)

    with engine.begin() as connection:
        result = connection.execute(query, {"task_id": task_id})
        task = result.mappings().one_or_none()

        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        task_response = TaskResponse(**dict(task))
        cache.set(cache_key, task_response.model_dump_json(), ex=60)

    response.headers["X-Cache"] = "MISS"
    return task_response

@app.put("/tasks/{task_id}", response_model=TaskResponse)
def update_task(task_id: int, task: TaskCreate):
    query = text("""
        UPDATE tasks
        SET name = :name,
            task_type = :task_type,
            parameters = CAST(:parameters AS JSONB)
        WHERE id = :task_id
        RETURNING id, name, task_type, parameters, created_at
    """)

    values = {
        "task_id": task_id,
        "name": task.name,
        "task_type": task.task_type,
        "parameters": json.dumps(task.parameters),
    }

    with engine.begin() as connection:
        result = connection.execute(query, values)
        updated_task = result.mappings().one_or_none()

        if updated_task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        response = dict(updated_task)
        cache.delete(f"task:{task_id}")

    return response


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int):
    query = text("""
        DELETE FROM tasks
        WHERE id = :task_id
        RETURNING id
    """)

    with engine.begin() as connection:
        result = connection.execute(query, {"task_id": task_id})
        deleted_id = result.scalar_one_or_none()

        if deleted_id is None:
            raise HTTPException(status_code=404, detail="Task not found")

        cache.delete(f"task:{task_id}")

    return Response(status_code=204)



@app.post(
    "/tasks/{task_id}/runs",
    response_model=RunResponse,
    status_code=202,
)
def create_run(task_id: int):
    task_query = text("""
        SELECT name, task_type, parameters
        FROM tasks
        WHERE id = :task_id
        FOR SHARE
    """)

    run_query = text("""
        INSERT INTO task_runs (task_id, task_snapshot)
        VALUES (:task_id, CAST(:task_snapshot AS JSONB))
        RETURNING
            id, task_id, task_snapshot, status, result, error,
            created_at, published_at, started_at, finished_at
    """)

    with engine.begin() as connection:
        task_result = connection.execute(
            task_query,
            {"task_id": task_id},
        )
        task = task_result.mappings().one_or_none()

        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        values = {
            "task_id": task_id,
            "task_snapshot": json.dumps(dict(task)),
        }

        run_result = connection.execute(run_query, values)
        run = dict(run_result.mappings().one())

    return run


@app.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: int):
    query = text("""
        SELECT
            id, task_id, task_snapshot, status, result, error,
            created_at, published_at, started_at, finished_at
        FROM task_runs
        WHERE id = :run_id
    """)

    with engine.connect() as connection:
        result = connection.execute(query, {"run_id": run_id})
        run = result.mappings().one_or_none()

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return dict(run)