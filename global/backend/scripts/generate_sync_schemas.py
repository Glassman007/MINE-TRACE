from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.contracts.sync import (
    CURRENT_SYNC_SCHEMA_VERSION,
    EvidenceManifest,
    IncidentUpdate,
    MachineSessionReport,
    SyncAcknowledgement,
    SyncEnvelope,
)

OUT = ROOT / "shared" / "schema"

MODELS = {
    "machine-session-report.schema.json": MachineSessionReport,
    "evidence-manifest.schema.json": EvidenceManifest,
    "incident-update.schema.json": IncidentUpdate,
    "sync-envelope.schema.json": SyncEnvelope,
    "sync-acknowledgement.schema.json": SyncAcknowledgement,
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, model in MODELS.items():
        schema = model.model_json_schema(ref_template="#/$defs/{model}")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["x-mine-trace-schema-version"] = CURRENT_SYNC_SCHEMA_VERSION
        (OUT / filename).write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
