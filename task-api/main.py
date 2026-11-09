from fastapi import FastAPI

app = FastAPI(
    title="FlowRun API",
    version="0.1.0",
    description="Distributed Task Execution Platform"
)


@app.get("/hello")
def hello():
    return {"message": "Hello from FlowRun!"}


@app.get("/health")
def health():
    return {"status": "ok"}