from __future__ import annotations

from pathlib import Path

from copilot_ansible_agent.inventory.models import HostRecord
from copilot_ansible_agent.inventory.service import InventoryService


def test_upsert_and_delete_host(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.yml"
    service = InventoryService(inventory_path)

    record = HostRecord(
        name="web01",
        hostname="10.0.0.10",
        username="root",
        groups=["web"],
        variables={"ansible_become": True},
    )
    service.upsert_host(record)

    hosts = list(service.list_hosts())
    assert len(hosts) == 1
    assert hosts[0].hostname == "10.0.0.10"
    assert hosts[0].groups == ["web"]

    service.delete_host("web01")
    assert list(service.list_hosts()) == []
    assert inventory_path.exists()

