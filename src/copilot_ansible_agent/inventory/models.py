"""Inventory data models based on Pydantic."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, validator


class HostRecord(BaseModel):
    """Representation of a single Ansible host record."""

    name: str = Field(description="Logical inventory hostname (unique identifier).")
    hostname: str = Field(description="Reachable network address (IP or DNS).")
    username: str | None = Field(default=None, description="Remote SSH username.")
    password: str | None = Field(default=None, description="Remote SSH password (optional).")
    port: int | None = Field(default=None, description="SSH port (defaults to 22).")
    groups: list[str] = Field(default_factory=list, description="Ansible groups this host belongs to.")
    variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional host-level variables (e.g. ansible_become).",
    )

    @validator("name")
    def _normalise_name(cls, value: str) -> str:
        # Ansible hostnames cannot contain spaces, replace with dashes
        return value.strip().replace(" ", "-")

    def to_ansible_mapping(self) -> dict[str, Any]:
        """Convert to the host vars mapping expected by Ansible."""
        mapping: dict[str, Any] = {"ansible_host": self.hostname}
        if self.username:
            mapping["ansible_user"] = self.username
        if self.password:
            mapping["ansible_password"] = self.password
        if self.port:
            mapping["ansible_port"] = self.port
        mapping.update(self.variables)
        return mapping


class InventorySnapshot(BaseModel):
    """Serialisable snapshot of the full inventory."""

    hosts: dict[str, HostRecord] = Field(default_factory=dict)
    groups: dict[str, list[str]] = Field(default_factory=dict)

    def to_ansible_inventory(self) -> dict[str, Any]:
        """Render the snapshot into Ansible-compatible dictionary structure."""
        groups_mapping: dict[str, Any] = {}
        for group, members in self.groups.items():
            groups_mapping[group] = {
                "hosts": {host: {} for host in members},
            }

        ansible_hosts = {name: host.to_ansible_mapping() for name, host in self.hosts.items()}

        return {
            "all": {
                "hosts": ansible_hosts,
                "children": groups_mapping,
            }
        }

