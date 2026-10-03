# MINE-TRACE Global Synchronization Contract

## Scope

This document locks the transport policy used between one MINE-TRACE edge machine and the global backend. The executable contract models live in `app/contracts/sync.py`. Language-neutral generated schemas live in `shared/schema/`. The global runtime imports only the snapshot under `app/`; it has no runtime dependency on a parent `../../shared` directory.

## Versioning

- Current transport version: `1.0.0`.
- Version format is numeric semantic versioning: `MAJOR.MINOR.PATCH`.
- Supported major versions are explicitly enumerated by the backend. Version `1` is currently supported.
- The API reads and validates only top-level `schema_version` before interpreting business fields.
- An unsupported major version is rejected. The server does not guess renamed, deleted, or missing fields.
- Nested `MachineSessionReport` and `EvidenceManifest` versions must equal the envelope version.

## Canonical checksum policy

Algorithm: **SHA-256**.

Wire format: `sha256:<64 lowercase hexadecimal characters>`.

Checksum material is the complete validated `SyncEnvelope` except `sync_metadata.checksum` itself. `checksum_algorithm`, `produced_at`, `producer_version`, `package_id`, identities, report content, incidents, evidence manifest, important text references, and selected raw evidence remain covered.

Canonical serialization is **MINE-TRACE Canonical JSON v1**:

1. Validate values against the contract first.
2. UUIDs are lowercase canonical hyphenated strings.
3. Timestamps are converted to UTC and serialized as RFC3339 with exactly six fractional digits and `Z`.
4. `Decimal` transport values are serialized as normalized decimal strings.
5. Object keys are lexicographically sorted.
6. Array order is preserved.
7. JSON is UTF-8, with no insignificant whitespace and no ASCII escaping requirement (`ensure_ascii=false`).
8. Finite IEEE-754 fractional JSON numbers use a locked shortest-round-trip rule: `-0` becomes `0`; values with absolute magnitude in `[1e-6, 1e21)` use fixed decimal form without redundant trailing zeros; values outside that range use lowercase scientific notation with no exponent leading zero and an explicit `+` for positive exponents.
9. Non-finite numeric values are rejected.
10. `sync_metadata.checksum` is removed before hashing; no other field is removed.

The runtime implementation is `compute_envelope_checksum()` in `app/contracts/sync.py` and is the reference test vector generator for other languages.

## Logical revision fingerprint

The transport checksum intentionally covers `package_id` and sync metadata. A separate SHA-256 **revision fingerprint** detects logically identical report content delivered under a different package ID.

The fingerprint covers the validated envelope except:

- `package_id`
- the entire `sync_metadata` object

It still covers `source_machine_id`, `session_id`, `report_revision`, report content, incident updates, evidence manifest, important text evidence and selected raw evidence.

## Edge authentication boundary

Development/MVP authentication is replaceable through the `EdgeAuthenticator` protocol.

The default mechanism uses:

- `X-Mine-Trace-Node-Id: <machine UUID>`
- `Authorization: Bearer <raw edge token>`
- deployment configuration `MINE_TRACE_EDGE_NODE_TOKEN_HASHES`, a JSON map of machine UUID to `sha256:<digest>`

Only token digests are configured; no plaintext edge token is committed to source control. Authentication hashes the presented token and compares it using `hmac.compare_digest`. After the envelope is parsed, authenticated machine identity must equal `SyncEnvelope.source_machine_id`.

Limitations: this is static bearer authentication. It requires TLS, does not provide per-request signatures, freshness, nonce protection, certificate binding, automatic rotation, or replay prevention by itself. It can later be replaced by mTLS or signed requests without changing `SyncEnvelope`.

## Revision, idempotency and conflict rules

The deterministic policy is:

1. **Exact redelivery:** same authenticated machine + same `package_id` + same checksum returns the previously persisted acknowledgement and makes no canonical writes.
2. **Package ID reuse with changed bytes/content:** same machine + same `package_id` + different checksum creates a `PACKAGE_ID_REUSE` sync conflict. No canonical business state is overwritten.
3. **Same logical revision, identical content:** same machine + session + `report_revision` + identical revision fingerprint is idempotent. If the package ID is new, a `DUPLICATE` receipt is recorded but canonical report/evidence/link/action/verification rows are not duplicated.
4. **Same logical revision, incompatible content:** same machine + session + `report_revision` + different revision fingerprint creates a `SAME_REVISION_CONTENT_MISMATCH` sync conflict. No existing canonical revision is overwritten.
5. **Newer revision:** a revision greater than the latest accepted revision is accepted. The previous `session_reports` rows remain unchanged and auditable; current synchronized incident/session projections may advance to the newer explicit edge state.
6. **Older unseen out-of-order revision:** if a newer revision has already been accepted and the older revision was never accepted before, the package creates an `OUT_OF_ORDER_REVISION` conflict. It does not overwrite current state.
7. **Previously accepted older revision:** redelivery of that exact historical revision follows rules 1 or 3 and is idempotent.
8. Evidence is deduplicated by stable edge evidence UUID and guarded by source identity. The global backend never mints replacement evidence IDs during sync.

Conflict rows retain incoming package/revision/checksum/fingerprint metadata and the identity/metadata of the already accepted revision/receipt where one exists.

## Authority boundary

Synchronization routes records only through explicit IDs supplied by the edge contract. The global ingest path does not use AI to categorize data, relink incidents, infer recurrence, execute verification rules, reassign evidence, or silently merge conflicts. PostgreSQL commits canonical fleet truth before any semantic indexing task is dispatched.

Reference checksum vector: the fixed-ID fixture in `tests/global/test_sync_contract.py::test_checksum_reference_vector_is_locked_for_cross_language_producers` hashes to `sha256:b707ead0358f4ec56e3d8d6d1066c4fd937167946ffd3d3966696589c23cbbd6`.
