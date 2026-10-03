# MINE-TRACE canonical domain contracts

This package defines domain vocabulary and validation only. It contains no API,
SQLAlchemy model, repository, migration, Qdrant, embedding, or LLM behavior.

## Specification-backed decisions

- Incident lifecycle states are exactly `OPEN`, `VERIFYING`, `VERIFIED`, and
  `RECURRED`.
- Allowed transitions are exactly:
  - `OPEN -> VERIFYING`
  - `VERIFYING -> VERIFIED`
  - `VERIFYING -> RECURRED`
  - `VERIFIED -> RECURRED`
  - `RECURRED -> VERIFYING`
- `OPEN -> VERIFIED` is therefore invalid.
- Context quality is exactly `KNOWN`, `UNKNOWN`, or `STALE`.
- EvidenceBundle status is exactly `READY`, `PARTIAL`, or
  `INSUFFICIENT_EVIDENCE`.
- Audit actions are represented by a closed enum rather than arbitrary strings.

## Deliberate MVP implementation decisions

The requirements name persisted concepts but do not define every field or every
controlled vocabulary. The contracts therefore expose only fields needed to
identify concepts, express required relationships, or satisfy an explicit
architectural rule.

- UUIDs are used for domain identity. Persistence strategy is still undecided;
  these are domain contracts, not SQLAlchemy mappings.
- `EvidenceEvent` carries a timezone-aware occurrence timestamp, a minimal
  provenance reference, and the untouched raw JSON payload because raw evidence,
  provenance, and timeline ordering must remain authoritative in SQLite later.
- `EvidenceAttachment` retains controlled metadata including attachment type, storage
  reference, MIME type, file size, checksum, and creation time.
- `ContextSnapshot` is associated with the evidence event whose context it describes
  and uses the fixed five historical dimensions defined by the MVP contract.
- Incident/evidence relationship vocabulary is intentionally minimal:
  `RELATED`, `RECURRENCE`, `VERIFICATION`. More specific roles should be added
  only when a business rule requires them.
- The specification names audit actions for owner, severity, due state, and due
  time changes, but does not define owner identity, severity levels, due-state
  values, or audit payload shapes. Those values are therefore not invented here.
- Verification now has an explicit `NO_EVENT` rule contract and persisted absolute
  run timestamps (`started_at`, `window_ends_at`, `completed_at`). Handover, sync
  change, and sync conflict contracts remain minimal until those workflows are
  specified.
- `EvidenceBundle` is a domain contract but is deliberately non-persisted here;
  its construction remains deterministic service logic in a later step.

All Pydantic models reject undeclared fields (`extra="forbid"`) so unsupported
schema assumptions fail visibly rather than silently entering the domain.
