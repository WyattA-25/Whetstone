"""Whetstone web UI. Run locally: python -m whetstone.web  (then open http://127.0.0.1:8000)."""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

load_dotenv()

from .data import RunReader  # noqa: E402  (reads env set by load_dotenv)

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Whetstone", docs_url=None, redoc_url=None)
reader = RunReader()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "source": reader.source}


@app.get("/api/runs")
def runs() -> list[dict]:
    return reader.list_runs()


@app.get("/api/runs/{run_id}")
def run(run_id: str) -> dict:
    data = reader.get_run(run_id)
    if data is None:
        raise HTTPException(404, "run not found")
    return data
