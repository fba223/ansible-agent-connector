"""Configuration management for the Copilot Ansible Agent."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseSettings, Field, validator


class Settings(BaseSettings):
    """Centralised runtime configuration for the agent."""

    # General
    project_root: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[2],
        description="Root directory of the project repository.",
    )
    data_dir: Path = Field(
        default_factory=lambda: Path("data"),
        description="Directory for persisting dynamic artefacts (inventory, docs, playbooks, runs).",
    )

    # Inventory
    inventory_filename: str = Field(default="inventory.yml")

    # LLM Configuration
    openai_api_key: Optional[str] = Field(default=None, env="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini")
    openai_base_url: Optional[str] = Field(default=None)
    azure_openai_endpoint: Optional[str] = Field(default=None, env="AZURE_OPENAI_ENDPOINT")
    azure_openai_deployment: Optional[str] = Field(default=None, env="AZURE_OPENAI_DEPLOYMENT")

    # Connector
    connector_type: str = Field(default="ssh", description="Connector implementation id (ssh/rest).")
    ssh_host: Optional[str] = Field(default=None)
    ssh_port: int = Field(default=22)
    ssh_username: Optional[str] = Field(default=None)
    ssh_password: Optional[str] = Field(default=None)
    ssh_pkey_path: Optional[Path] = Field(default=None)
    ssh_pkey_passphrase: Optional[str] = Field(default=None)

    # Execution
    ansible_playbook_binary: str = Field(default="ansible-playbook")
    remote_workspace: Path = Field(
        default=Path("~/copilot-ansible-agent"),
        description="Remote workspace directory on the Ansible master node.",
    )

    # Storage folders (relative to data_dir unless absolute)
    inventory_dir: Path = Field(default=Path("inventory"))
    documents_dir: Path = Field(default=Path("documents"))
    playbooks_dir: Path = Field(default=Path("playbooks"))
    executions_dir: Path = Field(default=Path("executions"))

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        validate_assignment = True

    @validator(
        "data_dir",
        pre=True,
    )
    def _normalise_data_dir(cls, value: Path | str, values: dict[str, Path]) -> Path:
        project_root: Path = values.get("project_root", Path.cwd())
        candidate = Path(value) if not isinstance(value, Path) else value
        if candidate.is_absolute():
            return candidate
        return project_root / candidate

    @validator(
        "inventory_dir",
        "documents_dir",
        "playbooks_dir",
        "executions_dir",
        pre=True,
    )
    def _ensure_path(cls, value: Path | str) -> Path:
        if isinstance(value, Path):
            return value
        return Path(value)

    @property
    def inventory_path(self) -> Path:
        return self.data_dir / self.inventory_dir / self.inventory_filename

    @property
    def documents_path(self) -> Path:
        return self.data_dir / self.documents_dir

    @property
    def playbooks_path(self) -> Path:
        return self.data_dir / self.playbooks_dir

    @property
    def executions_path(self) -> Path:
        return self.data_dir / self.executions_dir


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance and ensure data directories exist."""
    settings = Settings()
    for path in (
        settings.data_dir,
        settings.inventory_path.parent,
        settings.documents_path,
        settings.playbooks_path,
        settings.executions_path,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return settings
