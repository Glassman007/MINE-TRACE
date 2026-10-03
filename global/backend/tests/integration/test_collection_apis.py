from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from app.db.session import get_db_session
from tests.sqlite_test_db import create_sqlite_test_engine
from app.domain.enums import IncidentStatus
from app.main import app
from app.models import ComponentRecord, IncidentRecord, MachineRecord


MACHINE_A = UUID(int=1)
MACHINE_B = UUID(int=2)
MACHINE_C = UUID(int=3)
MACHINE_D = UUID(int=4)
COMPONENT_A = UUID(int=101)
COMPONENT_B = UUID(int=102)
INCIDENT_A = UUID(int=201)
INCIDENT_B = UUID(int=202)
INCIDENT_C = UUID(int=203)
INCIDENT_D = UUID(int=204)


@pytest.fixture
def collection_env(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    engine = create_sqlite_test_engine(tmp_path / 'collections.db')
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    base = datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc)

    with factory.begin() as session:
        session.add_all(
            [
                MachineRecord(
                    id=MACHINE_A,
                    display_name="Alpha Hauler",
                    asset_code="HT-01",
                    machine_type="Haul Truck",
                    manufacturer="Maker A",
                    model="HT-X",
                    site_name="North Mine",
                    site_area="North Ramp",
                ),
                MachineRecord(
                    id=MACHINE_B,
                    display_name="Bravo Excavator",
                    asset_code="EX-01",
                    machine_type="Excavator",
                    manufacturer="Maker B",
                    model="EX-X",
                    site_name="South Mine",
                    site_area="Pit 2",
                ),
                MachineRecord(
                    id=MACHINE_C,
                    display_name=None,
                    asset_code="LD-01",
                    machine_type="Wheel Loader",
                    manufacturer=None,
                    model=None,
                    site_name="North Mine",
                    site_area=None,
                ),
                MachineRecord(
                    id=MACHINE_D,
                    display_name="Alpha Hauler",
                    asset_code="HT-02",
                    machine_type="Haul Truck",
                    manufacturer="Maker A",
                    model="HT-Y",
                    site_name="North Mine",
                    site_area="West Ramp",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                ComponentRecord(
                    id=COMPONENT_A,
                    machine_id=MACHINE_A,
                    display_name="Main Hydraulics",
                    component_type="Hydraulic System",
                    manufacturer="Hydro Co",
                    model="H-100",
                ),
                ComponentRecord(
                    id=COMPONENT_B,
                    machine_id=MACHINE_A,
                    display_name="Service Brakes",
                    component_type="Brake System",
                    manufacturer="Brake Co",
                    model="B-200",
                ),
            ]
        )
        session.add_all(
            [
                IncidentRecord(
                    id=INCIDENT_A,
                    machine_id=MACHINE_A,
                    status=IncidentStatus.OPEN,
                    severity="HIGH",
                    owner_ref="team-a",
                    due_state="DUE_SOON",
                    due_time=base + timedelta(hours=2),
                    created_at=base,
                    updated_at=base + timedelta(hours=1),
                ),
                IncidentRecord(
                    id=INCIDENT_B,
                    machine_id=MACHINE_A,
                    status=IncidentStatus.VERIFYING,
                    severity="CRITICAL",
                    owner_ref="team-b",
                    due_state="IN_PROGRESS",
                    due_time=base + timedelta(hours=1),
                    created_at=base + timedelta(minutes=10),
                    updated_at=base + timedelta(hours=3),
                ),
                IncidentRecord(
                    id=INCIDENT_C,
                    machine_id=MACHINE_B,
                    status=IncidentStatus.VERIFIED,
                    severity="HIGH",
                    owner_ref="team-a",
                    due_state="RESOLVED",
                    due_time=base - timedelta(hours=1),
                    created_at=base + timedelta(minutes=20),
                    updated_at=base + timedelta(hours=3),
                ),
                IncidentRecord(
                    id=INCIDENT_D,
                    machine_id=MACHINE_D,
                    status=IncidentStatus.OPEN,
                    severity="LOW",
                    owner_ref=None,
                    due_state=None,
                    due_time=None,
                    created_at=base - timedelta(hours=1),
                    updated_at=base,
                ),
            ]
        )

    def override_db() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_db
    try:
        with TestClient(app) as client:
            yield {"client": client, "factory": factory}
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_asset_code_is_unique_when_supplied(collection_env: dict[str, Any]) -> None:
    with collection_env["factory"]() as session:
        session.add(
            MachineRecord(
                id=UUID(int=999),
                display_name="Duplicate Code Machine",
                asset_code="HT-01",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_machine_and_component_metadata_persist_and_detail_endpoints_expose_it(
    collection_env: dict[str, Any],
) -> None:
    with collection_env["factory"]() as session:
        machine = session.scalar(select(MachineRecord).where(MachineRecord.id == MACHINE_A))
        component = session.scalar(
            select(ComponentRecord).where(ComponentRecord.id == COMPONENT_A)
        )
        assert machine is not None and machine.asset_code == "HT-01"
        assert machine.display_name == "Alpha Hauler"
        assert component is not None and component.component_type == "Hydraulic System"
        assert component.model == "H-100"

    client = collection_env["client"]
    machine_response = client.get(f"/api/v1/machines/{MACHINE_A}")
    component_response = client.get(f"/api/v1/components/{COMPONENT_A}")
    machine_components = client.get(f"/api/v1/machines/{MACHINE_A}/components")

    assert machine_response.status_code == 200
    assert machine_response.json() == {
        "id": str(MACHINE_A),
        "display_name": "Alpha Hauler",
        "asset_code": "HT-01",
        "machine_type": "Haul Truck",
        "manufacturer": "Maker A",
        "model": "HT-X",
        "site_name": "North Mine",
        "site_area": "North Ramp",
        "latest_sync_received_at": None,
        "latest_acknowledged_at": None,
        "latest_acknowledgement_status": None,
        "latest_report_revision": None,
    }
    assert component_response.status_code == 200
    assert component_response.json()["display_name"] == "Main Hydraulics"
    assert component_response.json()["component_type"] == "Hydraulic System"
    assert [item["id"] for item in machine_components.json()["components"]] == [
        str(COMPONENT_A),
        str(COMPONENT_B),
    ]


def test_machine_collection_total_filters_search_and_deterministic_ordering(
    collection_env: dict[str, Any],
) -> None:
    client = collection_env["client"]

    response = client.get("/api/v1/machines")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    assert body["offset"] == 0
    assert body["limit"] == 50
    assert [item["id"] for item in body["items"]] == [
        str(MACHINE_A),
        str(MACHINE_D),
        str(MACHINE_B),
        str(MACHINE_C),
    ]

    north = client.get("/api/v1/machines", params={"site": "North Mine"}).json()
    assert north["total"] == 3
    assert {item["id"] for item in north["items"]} == {
        str(MACHINE_A),
        str(MACHINE_C),
        str(MACHINE_D),
    }

    haul = client.get("/api/v1/machines", params={"machine_type": "Haul Truck"}).json()
    assert haul["total"] == 2
    assert [item["id"] for item in haul["items"]] == [str(MACHINE_A), str(MACHINE_D)]

    search = client.get("/api/v1/machines", params={"search": "ht-0"}).json()
    assert search["total"] == 2
    assert [item["asset_code"] for item in search["items"]] == ["HT-01", "HT-02"]


def test_machine_collection_pagination_keeps_full_sqlite_total(
    collection_env: dict[str, Any],
) -> None:
    body = collection_env["client"].get(
        "/api/v1/machines", params={"offset": 1, "limit": 2}
    ).json()
    assert body["total"] == 4
    assert body["offset"] == 1
    assert body["limit"] == 2
    assert [item["id"] for item in body["items"]] == [str(MACHINE_D), str(MACHINE_B)]


def test_incident_collection_filters_paginates_and_orders_without_audit_history(
    collection_env: dict[str, Any],
) -> None:
    client = collection_env["client"]
    body = client.get("/api/v1/incidents").json()
    assert body["total"] == 4
    assert [item["incident_id"] for item in body["items"]] == [
        str(INCIDENT_C),
        str(INCIDENT_B),
        str(INCIDENT_A),
        str(INCIDENT_D),
    ]
    assert all("audit_events" not in item for item in body["items"])

    page = client.get("/api/v1/incidents", params={"offset": 1, "limit": 2}).json()
    assert page["total"] == 4
    assert [item["incident_id"] for item in page["items"]] == [
        str(INCIDENT_B),
        str(INCIDENT_A),
    ]

    filters = (
        ({"machine": str(MACHINE_A)}, {str(INCIDENT_A), str(INCIDENT_B)}),
        ({"status": "OPEN"}, {str(INCIDENT_A), str(INCIDENT_D)}),
    )
    for params, expected in filters:
        filtered = client.get("/api/v1/incidents", params=params).json()
        assert filtered["total"] == len(expected)
        assert {item["incident_id"] for item in filtered["items"]} == expected


def test_incident_detail_semantics_remain_compatible(collection_env: dict[str, Any]) -> None:
    body = collection_env["client"].get(f"/api/v1/incidents/{INCIDENT_A}").json()
    assert body["incident_id"] == str(INCIDENT_A)
    assert body["machine_id"] == str(MACHINE_A)
    assert body["status"] == "OPEN"
    assert body["severity"] == "HIGH"
    assert body["owner_ref"] == "team-a"
    assert body["audit_events"] == []


def test_overview_uses_sqlite_counts_and_includes_zero_status_keys(
    collection_env: dict[str, Any],
) -> None:
    response = collection_env["client"].get("/api/v1/overview")
    assert response.status_code == 200
    assert response.json() == {
        "machines_total": 4,
        "components_total": 2,
        "incidents_total": 4,
        "incidents_by_status": {
            "OPEN": 2,
            "VERIFYING": 1,
            "VERIFIED": 1,
            "RECURRED": 0,
        },
    }
