from __future__ import annotations

from pathlib import Path

from copilot_ansible_agent.storage.files import FileStorage


def test_file_storage_write_and_read(tmp_path: Path) -> None:
    storage = FileStorage(tmp_path)
    storage.write_text("playbooks/sample.yml", "content")
    assert (tmp_path / "playbooks" / "sample.yml").read_text(encoding="utf-8") == "content"

