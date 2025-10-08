"""Async playbook execution with log streaming."""

from __future__ import annotations

import asyncio
import shlex
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config import get_settings


@dataclass
class PlaybookRun:
    """Runtime state for an ansible-playbook execution."""

    run_id: str
    command: list[str]
    inventory_path: Path
    playbook_path: Path
    status: str = "pending"
    return_code: Optional[int] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    summary: Optional[str] = None
    error: Optional[str] = None
    logs: list[str] = field(default_factory=list)
    subscribers: list[asyncio.Queue[Optional[str]]] = field(default_factory=list)

    def add_log(self, line: str) -> None:
        self.logs.append(line)
        for queue in list(self.subscribers):
            queue.put_nowait(line)

    def complete_streams(self) -> None:
        for queue in list(self.subscribers):
            queue.put_nowait(None)


class PlaybookRunner:
    """Manage asynchronous ansible-playbook executions."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._runs: Dict[str, PlaybookRun] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ public
    async def start_run(
        self,
        playbook_path: Path,
        *,
        inventory_path: Optional[Path] = None,
        extra_args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
    ) -> PlaybookRun:
        inventory_path = inventory_path or self._settings.inventory_path
        if not playbook_path.exists():
            raise FileNotFoundError(f"Playbook not found: {playbook_path}")
        if not inventory_path.exists():
            raise FileNotFoundError(f"Inventory not found: {inventory_path}")

        cmd = [
            self._settings.ansible_playbook_binary,
            "-i",
            str(inventory_path),
            str(playbook_path),
        ]
        if extra_args:
            cmd.extend(extra_args)

        run = PlaybookRun(
            run_id=str(uuid.uuid4()),
            command=cmd,
            inventory_path=inventory_path,
            playbook_path=playbook_path,
        )

        async with self._lock:
            self._runs[run.run_id] = run

        asyncio.create_task(self._execute(run, env=env))
        return run

    async def get_run(self, run_id: str) -> PlaybookRun | None:
        async with self._lock:
            return self._runs.get(run_id)

    async def list_runs(self) -> list[PlaybookRun]:
        async with self._lock:
            return list(self._runs.values())

    async def stream_run(self, run_id: str) -> asyncio.AsyncIterator[str]:
        run = await self.get_run(run_id)
        if not run:
            raise KeyError(f"Unknown run_id: {run_id}")

        queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        # Prime with historical logs
        for line in run.logs:
            queue.put_nowait(line)

        run.subscribers.append(queue)
        try:
            while True:
                line = await queue.get()
                if line is None:
                    break
                yield line
        finally:
            run.subscribers.remove(queue)

    # ----------------------------------------------------------------- private
    async def _execute(self, run: PlaybookRun, *, env: Optional[dict[str, str]]) -> None:
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        command_display = " ".join(shlex.quote(part) for part in run.command)
        run.add_log(f"$ {command_display}\n")

        process = await asyncio.create_subprocess_exec(
            *run.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        await asyncio.gather(
            self._drain_stream(process.stdout, run, source="stdout"),
            self._drain_stream(process.stderr, run, source="stderr"),
        )

        run.return_code = await process.wait()
        run.finished_at = datetime.now(timezone.utc)
        run.status = "succeeded" if run.return_code == 0 else "failed"
        run.summary = self._build_summary(run)
        if run.return_code != 0 and not run.error:
            run.error = f"Process exited with code {run.return_code}"
        run.complete_streams()

    async def _drain_stream(
        self,
        stream: asyncio.StreamReader,
        run: PlaybookRun,
        *,
        source: str,
    ) -> None:
        while True:
            line = await stream.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace")
            run.add_log(decoded)
            if source == "stderr":
                run.error = decoded.strip()

    def _build_summary(self, run: PlaybookRun) -> str:
        if not run.logs:
            return "Playbook produced no output."

        recap_index = None
        for idx in range(len(run.logs) - 1, -1, -1):
            if "PLAY RECAP" in run.logs[idx]:
                recap_index = idx
                break

        if recap_index is not None:
            recap_lines = [line.strip() for line in run.logs[recap_index:]]
            status_line = recap_lines[1].strip() if len(recap_lines) > 1 else ""
            if run.return_code == 0:
                return f"Playbook completed successfully. Recap: {status_line}"
            return f"Playbook failed. Recap: {status_line}"

        if run.return_code == 0:
            return "Playbook completed successfully."
        return run.error or "Playbook failed with an unknown error."

