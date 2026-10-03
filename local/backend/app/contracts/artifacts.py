from __future__ import annotations

import json
from pathlib import Path
from typing import Type

from pydantic import BaseModel

from app.main import app
from app.schemas.session_reports import EvidenceManifest, MachineSessionReport
from app.schemas.sync import IncidentUpdate, SyncAcknowledgement, SyncEnvelope

CONTRACT_MODELS: dict[str, Type[BaseModel]] = {
    "machine-session-report.schema.json": MachineSessionReport,
    "evidence-manifest.schema.json": EvidenceManifest,
    "incident-update.schema.json": IncidentUpdate,
    "sync-envelope.schema.json": SyncEnvelope,
    "sync-acknowledgement.schema.json": SyncAcknowledgement,
}


def generated_contract_documents() -> dict[str, dict[str, object]]:
    documents: dict[str, dict[str, object]] = {
        filename: model.model_json_schema(mode="serialization")
        for filename, model in CONTRACT_MODELS.items()
    }
    documents["openapi.json"] = app.openapi()
    return documents


def write_contract_documents(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for filename, document in generated_contract_documents().items():
        (destination / filename).write_text(
            json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
