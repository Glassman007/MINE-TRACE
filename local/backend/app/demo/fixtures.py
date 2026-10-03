"""Centralized hardcoded presentation data used only by demo mode."""
from __future__ import annotations
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

DEMO_VERSION = "mine-trace-local-demo-v1"
DEMO_NAMESPACE = uuid5(NAMESPACE_URL, DEMO_VERSION)

def demo_id(name: str) -> UUID:
    return uuid5(DEMO_NAMESPACE, name)

DEMO_MACHINE_ID = demo_id("machine:EXC-204")
DEMO_MACHINE = {
    "id": DEMO_MACHINE_ID,
    "display_name": "EXC-204",
    "asset_code": "EXC-204",
    "machine_type": "Hydraulic Excavator",
    "manufacturer": "MINE-TRACE Demo",
    "model": "EXC-204",
    "site_name": "North Ridge Mine",
    "site_area": "North Ridge Pit A",
}
DEMO_COMPONENTS = (
    ("engine", "Engine", "ENGINE"),
    ("hydraulic_pump", "Hydraulic Pump", "HYDRAULIC_PUMP"),
    ("boom", "Boom", "BOOM"),
    ("arm", "Arm", "ARM"),
    ("bucket", "Bucket", "BUCKET"),
    ("cooling", "Cooling System", "COOLING_SYSTEM"),
    ("final_drive", "Final Drive", "FINAL_DRIVE"),
)
COMPONENT_IDS = {key: demo_id(f"component:{key}") for key, _, _ in DEMO_COMPONENTS}
DEMO_ANCHOR = datetime(2026, 10, 3, 10, 0, tzinfo=timezone.utc)
DEMO_SESSION_ID = demo_id("session:day-shift")
DEMO_CLOSED_SESSION_ID = demo_id("session:previous-shift")
DEMO_HYDRAULIC_INCIDENT_ID = demo_id("incident:hydraulic-pressure")
DEMO_PENDING_INCIDENT_ID = demo_id("incident:cooling-inspection")
DEMO_CONFLICT_ID = demo_id("sync-conflict:previous-shift")
DEMO_EVIDENCE_IDS = {
    "previous_similar": demo_id("evidence:previous-similar"),
    "operator_observation": demo_id("evidence:operator-observation"),
    "pressure_event": demo_id("evidence:pressure-event"),
    "maintenance": demo_id("evidence:maintenance"),
    "verification_observation": demo_id("evidence:verification-observation"),
    "cooling_unresolved": demo_id("evidence:cooling-unresolved"),
}
# Presentation-only schematic coordinates. They do not claim physical geometry.
DEMO_COMPONENT_SCHEMATIC = {
    "ENGINE": (20, 48),
    "HYDRAULIC_PUMP": (34, 58),
    "BOOM": (56, 26),
    "ARM": (70, 34),
    "BUCKET": (84, 62),
    "COOLING_SYSTEM": (18, 30),
    "FINAL_DRIVE": (38, 80),
}
DEMO_QDRANT_LOCATION = "./demo-qdrant"
DEMO_EMBEDDING_PROVIDER = "demo_hash"
DEMO_EMBEDDING_MODEL = "mine-trace-demo-hash-v1"
DEMO_EMBEDDING_DIMENSION = 64
DEMO_RETURN_TO_SERVICE_POLICY_IDENTIFIER = "demo.north-ridge.return-to-service.v1"
DEMO_RETURN_TO_SERVICE_POLICY_REVISION = 1
DEMO_GLOBAL_BACKEND_BASE_URL = "https://central.demo.invalid"
