"""FastAPI application exposing Ansible automation endpoints."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import Settings, get_settings
from .executor.playbook_runner import PlaybookRun, PlaybookRunner
from .inventory.models import HostRecord
from .inventory.service import InventoryService
from .storage.files import FileStorage

app = FastAPI(title="Copilot Ansible Connector", version="0.1.0")


class HostRequest(BaseModel):
    name: str
    hostname: str
    username: str | None = None
    password: str | None = None
    port: int | None = None
    groups: list[str] = Field(default_factory=list)
    variables: dict[str, str] = Field(default_factory=dict)

    def to_record(self) -> HostRecord:
        return HostRecord(**self.dict())


class WriteFileRequest(BaseModel):
    relative_path: str = Field(..., description="Path relative to the configured playbook directory.")
    content: str


class RunPlaybookRequest(BaseModel):
    relative_playbook_path: str = Field(..., description="Path relative to the playbooks directory.")
    extra_args: list[str] | None = None


class RunResponse(BaseModel):
    run_id: str
    status: str
    summary: str | None = None


class InventoryHostResponse(BaseModel):
    name: str
    hostname: str
    username: str | None = None
    port: int | None = None
    groups: list[str] = Field(default_factory=list)
    variables: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_model(cls, record: HostRecord) -> "InventoryHostResponse":
        return cls(
            name=record.name,
            hostname=record.hostname,
            username=record.username,
            port=record.port,
            groups=record.groups,
            variables=record.variables,
        )


class RunStatusResponse(BaseModel):
    run_id: str
    status: str
    return_code: int | None = None
    summary: str | None = None
    error: str | None = None

    @classmethod
    def from_run(cls, run: PlaybookRun) -> "RunStatusResponse":
        return cls(
            run_id=run.run_id,
            status=run.status,
            return_code=run.return_code,
            summary=run.summary,
            error=run.error,
        )


async def get_inventory(settings: Settings = Depends(get_settings)) -> InventoryService:
    if not hasattr(app.state, "inventory_service"):
        app.state.inventory_service = InventoryService(settings.inventory_path)
    return app.state.inventory_service


async def get_file_storage(settings: Settings = Depends(get_settings)) -> FileStorage:
    if not hasattr(app.state, "file_storage"):
        app.state.file_storage = FileStorage(settings.playbooks_path)
    return app.state.file_storage


async def get_runner() -> PlaybookRunner:
    if not hasattr(app.state, "playbook_runner"):
        app.state.playbook_runner = PlaybookRunner()
    return app.state.playbook_runner


@app.get("/healthz")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/inventory/hosts", response_model=list[InventoryHostResponse])
async def list_hosts(inventory: InventoryService = Depends(get_inventory)):
    hosts = inventory.list_hosts()
    return [InventoryHostResponse.from_model(host) for host in hosts]


@app.post("/inventory/hosts", response_model=InventoryHostResponse, status_code=status.HTTP_201_CREATED)
async def upsert_host(
    payload: HostRequest,
    inventory: InventoryService = Depends(get_inventory),
):
    record = inventory.upsert_host(payload.to_record())
    return InventoryHostResponse.from_model(record)


@app.delete("/inventory/hosts/{name}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_host(name: str, inventory: InventoryService = Depends(get_inventory)):
    deleted = inventory.delete_host(name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Host not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/files/write", response_model=dict[str, str])
async def write_file(
    payload: WriteFileRequest,
    storage: FileStorage = Depends(get_file_storage),
):
    try:
        path = storage.write_text(payload.relative_path, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"path": str(path)}


@app.post("/playbooks/run", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_playbook(
    payload: RunPlaybookRequest,
    storage: FileStorage = Depends(get_file_storage),
    runner: PlaybookRunner = Depends(get_runner),
):
    playbook_path = storage.resolve_path(payload.relative_playbook_path)
    run = await runner.start_run(playbook_path, extra_args=payload.extra_args)
    return RunResponse(run_id=run.run_id, status=run.status)


@app.get("/runs/{run_id}", response_model=RunStatusResponse)
async def get_run(run_id: str, runner: PlaybookRunner = Depends(get_runner)):
    run = await runner.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunStatusResponse.from_run(run)


async def _sse_event_stream(generator: AsyncIterator[str]) -> AsyncIterator[bytes]:
    async for chunk in generator:
        yield f"data: {chunk.rstrip()}\n\n".encode("utf-8")
        await asyncio.sleep(0)


@app.get("/stream/{run_id}")
async def stream_logs(run_id: str, runner: PlaybookRunner = Depends(get_runner)):
    try:
        stream = runner.stream_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StreamingResponse(_sse_event_stream(stream), media_type="text/event-stream")

