# MINE-TRACE edge-to-central transport contracts

These files are generated from the backend Pydantic/OpenAPI models. Do not hand-edit the JSON schema snapshots.

Regenerate from the backend repository root with:

```text
python scripts/generate_transport_contracts.py
```

## Version policy

`schema_version` uses `MAJOR.MINOR` format.

- Major changes are incompatible. A receiver must inspect `schema_version` first and reject an unsupported major before interpreting business fields.
- Minor changes stay within the same major and are reserved for backward-compatible contract evolution.
- The current contract version is `1.0` and the supported major is `1`.

Each portable deployment ZIP may copy this directory as a snapshot. Runtime code must not depend on an external `../../shared` checkout, and browser code must not import Python modules.
