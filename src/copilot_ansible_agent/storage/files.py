"""Utility helpers for managing local file storage."""

from __future__ import annotations

from pathlib import Path


class FileStorage:
    """Simple helper to manage writing and reading files with a safe root."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve a user-provided path under the storage root."""
        candidate = (self.base_dir / relative_path).resolve()
        if not str(candidate).startswith(str(self.base_dir.resolve())):
            raise ValueError("Invalid path; must reside under storage directory.")
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate

    def write_text(self, relative_path: str, content: str) -> Path:
        target = self.resolve_path(relative_path)
        target.write_text(content, encoding="utf-8")
        return target

    def read_text(self, relative_path: str) -> str:
        target = self.resolve_path(relative_path)
        return target.read_text(encoding="utf-8")

