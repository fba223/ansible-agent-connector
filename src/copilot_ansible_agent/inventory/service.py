"""Inventory management backed by a YAML file."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterable

import yaml

from .models import HostRecord, InventorySnapshot


class InventoryService:
    """Thread-safe inventory CRUD operations."""

    def __init__(self, inventory_path: Path) -> None:
        self.inventory_path = inventory_path
        self._lock = threading.RLock()
        self._snapshot = InventorySnapshot()
        self.inventory_path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    # ------------------------------------------------------------------ utils
    def _load(self) -> None:
        if not self.inventory_path.exists():
            self._persist()
            return

        with self.inventory_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

        hosts: dict[str, HostRecord] = {}
        groups: dict[str, list[str]] = {}

        all_section = data.get("all", {})
        raw_hosts = all_section.get("hosts", {})
        for name, vars_map in raw_hosts.items():
            vars_map = vars_map or {}
            hosts[name] = HostRecord(
                name=name,
                hostname=vars_map.get("ansible_host", name),
                username=vars_map.get("ansible_user"),
                password=vars_map.get("ansible_password"),
                port=vars_map.get("ansible_port"),
                groups=[],
                variables={
                    key: value
                    for key, value in vars_map.items()
                    if key not in {"ansible_host", "ansible_user", "ansible_password", "ansible_port"}
                },
            )

        raw_groups = all_section.get("children", {})
        for group, payload in raw_groups.items():
            members = list((payload or {}).get("hosts", {}).keys())
            groups[group] = members
            for host in members:
                if host in hosts:
                    hosts[host].groups.append(group)

        self._snapshot = InventorySnapshot(hosts=hosts, groups=groups)

    def _persist(self) -> None:
        data = self._snapshot.to_ansible_inventory()
        with self.inventory_path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=True)

    def _update_group_membership(self, host: HostRecord) -> None:
        for group, members in self._snapshot.groups.items():
            if host.name in members and group not in host.groups:
                members.remove(host.name)
        for group in host.groups:
            members = self._snapshot.groups.setdefault(group, [])
            if host.name not in members:
                members.append(host.name)

    # ------------------------------------------------------------------- API
    def list_hosts(self) -> Iterable[HostRecord]:
        with self._lock:
            return list(self._snapshot.hosts.values())

    def get_host(self, name: str) -> HostRecord | None:
        with self._lock:
            return self._snapshot.hosts.get(name)

    def upsert_host(self, record: HostRecord) -> HostRecord:
        with self._lock:
            self._snapshot.hosts[record.name] = record
            self._update_group_membership(record)
            self._persist()
            return record

    def delete_host(self, name: str) -> bool:
        with self._lock:
            if name not in self._snapshot.hosts:
                return False
            del self._snapshot.hosts[name]
            for members in self._snapshot.groups.values():
                if name in members:
                    members.remove(name)
            self._persist()
            return True

    def rename_host(self, old_name: str, new_name: str) -> HostRecord:
        with self._lock:
            record = self._snapshot.hosts.pop(old_name)
            record.name = new_name
            self._snapshot.hosts[new_name] = record
            for members in self._snapshot.groups.values():
                for idx, member in enumerate(list(members)):
                    if member == old_name:
                        members[idx] = new_name
            self._persist()
            return record

    def set_groups(self, name: str, groups: list[str]) -> HostRecord:
        with self._lock:
            record = self._snapshot.hosts[name]
            record.groups = groups
            self._update_group_membership(record)
            self._persist()
            return record

    def reset(self) -> None:
        """Clear inventory (useful for tests)."""
        with self._lock:
            self._snapshot = InventorySnapshot()
            self._persist()

