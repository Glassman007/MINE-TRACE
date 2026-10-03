import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  ArrowRightLeft,
  Bot,
  Database,
  Box,
  Braces,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  ClipboardList,
  FileClock,
  History,
  Link2,
  Search,
  Sparkles,
  PlayCircle,
  RefreshCw,
  Scissors,
  ShieldAlert,
  Split,
  Unlink,
  UserRoundCheck,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { ApiError } from '../api/http'
import {
  useEvaluateDueVerifications,
  useIncident,
  useIncidentAudit,
  useIncidentEvidence,
  useIncidents,
  useIncidentVerifications,
  useMoveIncidentEvidence,
  useSplitIncident,
  useStartIncidentVerification,
  useVerificationRun,
  type IncidentAuditEvent,
  type IncidentEvidenceAssociation,
  type VerificationRun,
} from '../api/incidents'
import { useEvidenceBundle, type EvidenceBundleResponse } from '../api/evidenceBundle'
import { useAnalyzeIncidentEvidence, type CitedAIClaim } from '../api/ai'
import { useCurrentMachine } from '../api/machines'
import {
  ConfirmDialog,
  EmptyState,
  ErrorState,
  GlassPanel,
  LoadingSkeleton,
  SectionHeader,
  StatusBadge,
  TechnicalId,
} from '../components/primitives'
import { formatDateTime, machineIdentity, shortId } from '../utils/machineFormatting'
import {
  booleanField,
  nestedRecord,
  prettyJson,
  recordOf,
  severityTone,
  statusTone,
  stringField,
  titleCaseToken,
} from '../utils/incidentFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

type WorkspaceTab = 'overview' | 'evidence' | 'audit' | 'verification' | 'bundle' | 'ai'

const tabs: Array<{ id: WorkspaceTab; label: string }> = [
  { id: 'overview', label: 'Overview' },
  { id: 'evidence', label: 'Evidence' },
  { id: 'audit', label: 'Audit' },
  { id: 'verification', label: 'Verification' },
  { id: 'bundle', label: 'Evidence Bundle' },
  { id: 'ai', label: 'AI Analysis' },
]

const auditPresentation: Record<string, { Icon: typeof History; tone: 'neutral' | 'info' | 'success' | 'warning' | 'danger' }> = {
  INCIDENT_CREATED: { Icon: CircleDot, tone: 'info' },
  EVIDENCE_LINKED: { Icon: Link2, tone: 'success' },
  EVIDENCE_UNLINKED: { Icon: Unlink, tone: 'warning' },
  INCIDENT_SPLIT: { Icon: Split, tone: 'warning' },
  STATUS_CHANGED: { Icon: Activity, tone: 'info' },
  OWNER_CHANGED: { Icon: UserRoundCheck, tone: 'info' },
  SEVERITY_CHANGED: { Icon: ShieldAlert, tone: 'warning' },
  DUE_STATE_CHANGED: { Icon: FileClock, tone: 'info' },
  DUE_TIME_CHANGED: { Icon: FileClock, tone: 'info' },
  RECURRENCE_RECORDED: { Icon: History, tone: 'danger' },
  HANDOVER_ACKNOWLEDGED: { Icon: CheckCircle2, tone: 'success' },
}

const conflictDescriptions: Record<string, string> = {
  VERIFICATION_STATE_CONFLICT: 'The incident verification state changed or is not eligible for this operation. Reloaded server state should be reviewed before trying again.',
  VERIFICATION_CONFIGURATION_CONFLICT: 'The backend verification configuration cannot satisfy this operation in the current state.',
  INCIDENT_CORRECTION_CONFLICT: 'The incident/evidence association changed or conflicts with the requested correction. Review the refreshed authoritative evidence links.',
}

function displayValue(value: string | null | undefined, fallback = 'Not set') {
  return value?.trim() ? value : fallback
}

function evidenceRecord(association: IncidentEvidenceAssociation): Record<string, unknown> {
  return recordOf(association) ?? {}
}

function evidenceId(association: IncidentEvidenceAssociation) {
  return association.evidence_id
}

function evidencePayload(association: IncidentEvidenceAssociation) {
  return association.canonical_payload
}

function evidenceProvenance(association: IncidentEvidenceAssociation) {
  return association.provenance
}

function evidenceRawPayload(association: IncidentEvidenceAssociation) {
  return association.raw_source_payload
}

function auditEvidenceId(event: IncidentAuditEvent) {
  const direct = stringField(event, 'evidence_id')
  if (direct) return direct
  const metadata = nestedRecord(event, 'metadata')
  return stringField(metadata, 'evidence_id')
}

function arrayField(record: Record<string, unknown>, ...keys: string[]): unknown[] {
  for (const key of keys) {
    const value = record[key]
    if (Array.isArray(value)) return value
  }
  return []
}

function primitiveField(record: Record<string, unknown>, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) return value
    if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  }
  return null
}

function extractCreatedIncidentId(payload: unknown, sourceIncidentId: string): string | null {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null
  const root = payload as Record<string, unknown>
  const directKeys = ['new_incident_id', 'created_incident_id', 'target_incident_id', 'incident_id']
  for (const key of directKeys) {
    const value = root[key]
    if (typeof value === 'string' && value && value !== sourceIncidentId) return value
  }
  for (const key of ['new_incident', 'created_incident', 'incident']) {
    const nested = root[key]
    if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
      const id = stringField(nested as Record<string, unknown>, 'id', 'incident_id')
      if (id && id !== sourceIncidentId) return id
    }
  }
  return null
}

function JsonInspector({ label, value }: { label: string; value: unknown }) {
  return (
    <details className="incident-json-inspector">
      <summary><Braces size={14} aria-hidden="true" />{label}</summary>
      <pre>{prettyJson(value)}</pre>
    </details>
  )
}

function MutationMessage({ error, success }: { error: unknown; success?: string | null }) {
  if (error instanceof ApiError) {
    const isConflict = error.status === 409
    const description = (error.code && conflictDescriptions[error.code]) || error.message
    return (
      <div className={`incident-action-message${isConflict ? ' incident-action-message--conflict' : ' incident-action-message--error'}`} role="alert">
        {isConflict ? <AlertTriangle size={16} aria-hidden="true" /> : null}
        <div>
          <strong>{isConflict ? 'State conflict' : 'Action failed'}{error.code ? ` · ${error.code}` : ''}</strong>
          <span>{description}</span>
        </div>
      </div>
    )
  }
  if (error) {
    return <div className="incident-action-message incident-action-message--error" role="alert"><div><strong>Action failed</strong><span>Unexpected request failure. Authoritative state was not changed in the browser.</span></div></div>
  }
  if (success) {
    return <div className="incident-action-message incident-action-message--success" role="status"><CheckCircle2 size={16} aria-hidden="true" /><div><strong>Backend action completed</strong><span>{success}</span></div></div>
  }
  return null
}

function OverviewSection({ incident, machineLabel }: { incident: Record<string, unknown>; machineLabel: string }) {
  const status = stringField(incident, 'status') ?? 'UNKNOWN'
  const severity = stringField(incident, 'severity')
  const machineId = stringField(incident, 'machine_id')
  const owner = stringField(incident, 'owner_ref')
  const dueState = stringField(incident, 'due_state')
  const dueTime = stringField(incident, 'due_time')
  const created = stringField(incident, 'created_at')
  const updated = stringField(incident, 'updated_at')

  return (
    <GlassPanel className="page-panel incident-workspace-panel">
      <SectionHeader title="Incident overview" description="Only authoritative incident fields returned by the backend are shown here." />
      <div className="incident-overview-state">
        <StatusBadge tone={statusTone(status)}>{status}</StatusBadge>
        {severity ? <StatusBadge tone={severityTone(severity)}>{severity}</StatusBadge> : null}
      </div>
      <dl className="incident-overview-grid">
        <div><dt>Machine</dt><dd>{machineLabel}{machineId ? <TechnicalId value={machineId} /> : null}</dd></div>
        <div><dt>Owner</dt><dd>{displayValue(owner)}</dd></div>
        <div><dt>Due state</dt><dd>{displayValue(dueState)}</dd></div>
        <div><dt>Due time</dt><dd>{formatDateTime(dueTime) ?? displayValue(dueTime)}</dd></div>
        <div><dt>Created</dt><dd>{formatDateTime(created) ?? displayValue(created, 'Not returned')}</dd></div>
        <div><dt>Updated</dt><dd>{formatDateTime(updated) ?? displayValue(updated, 'Not returned')}</dd></div>
      </dl>
    </GlassPanel>
  )
}

function EvidenceSection({
  evidence,
  incidentId,
  machineId,
}: {
  evidence: ReturnType<typeof useIncidentEvidence>
  incidentId: string
  machineId: string
}) {
  const [splitMode, setSplitMode] = useState(false)
  const [selectedEvidence, setSelectedEvidence] = useState<Set<string>>(new Set())
  const [splitReason, setSplitReason] = useState('')
  const [splitConfirmOpen, setSplitConfirmOpen] = useState(false)
  const [createdIncidentId, setCreatedIncidentId] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [moveEvidenceId, setMoveEvidenceId] = useState<string | null>(null)
  const [moveTargetId, setMoveTargetId] = useState('')
  const [moveReason, setMoveReason] = useState('')
  const [moveConfirmOpen, setMoveConfirmOpen] = useState(false)

  const targetIncidents = useIncidents({ offset: 0, limit: 100, machine_id: machineId || undefined })
  const moveMutation = useMoveIncidentEvidence()
  const splitMutation = useSplitIncident()

  const activeEvidenceIds = useMemo(() => {
    const ids = new Set<string>()
    for (const association of evidence.data ?? []) {
      const id = evidenceId(association)
      if (id && booleanField(association, 'active') === true) ids.add(id)
    }
    return ids
  }, [evidence.data])

  useEffect(() => {
    setSelectedEvidence((current) => new Set([...current].filter((id) => activeEvidenceIds.has(id))))
  }, [activeEvidenceIds])

  const targetOptions = (targetIncidents.data?.items ?? []).filter((item) => item.id !== incidentId)

  const toggleSelected = (id: string) => {
    setSelectedEvidence((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const openMove = (id: string) => {
    setMoveEvidenceId(id)
    setMoveTargetId('')
    setMoveReason('')
    setSuccessMessage(null)
    moveMutation.reset()
  }

  const cancelMove = () => {
    setMoveEvidenceId(null)
    setMoveTargetId('')
    setMoveReason('')
    setMoveConfirmOpen(false)
    moveMutation.reset()
  }

  const confirmMove = async () => {
    if (!moveEvidenceId || !moveTargetId || !moveReason.trim()) return
    try {
      await moveMutation.mutateAsync({
        sourceIncidentId: incidentId,
        evidenceId: moveEvidenceId,
        targetIncidentId: moveTargetId,
        reason: moveReason.trim(),
      })
      setSuccessMessage('Evidence association changed on the backend. Source and target incident state are being refreshed; the evidence record itself remains authoritative.')
      setMoveConfirmOpen(false)
      setMoveEvidenceId(null)
      setMoveTargetId('')
      setMoveReason('')
    } catch {
      setMoveConfirmOpen(false)
    }
  }

  const confirmSplit = async () => {
    const ids = [...selectedEvidence]
    if (ids.length === 0 || !splitReason.trim()) return
    try {
      const response = await splitMutation.mutateAsync({ sourceIncidentId: incidentId, evidenceIds: ids, reason: splitReason.trim() })
      const returnedId = extractCreatedIncidentId(response, incidentId)
      setCreatedIncidentId(returnedId)
      setSuccessMessage(returnedId
        ? 'Split committed by the backend. Source incident state is being refreshed; the new incident can be opened below.'
        : 'Split committed by the backend. Source incident state is being refreshed. No created incident identifier was recognized in the response payload.')
      setSelectedEvidence(new Set())
      setSplitReason('')
      setSplitMode(false)
      setSplitConfirmOpen(false)
    } catch {
      setSplitConfirmOpen(false)
    }
  }

  if (evidence.isPending) {
    return <div className="incident-section-loading">{Array.from({ length: 4 }).map((_, index) => <LoadingSkeleton key={index} width="100%" height={180} label="Incident evidence loading" />)}</div>
  }
  if (evidence.isError) return <ErrorState title="Evidence unavailable" description="Incident evidence associations could not be loaded from the backend." />
  if (evidence.data.length === 0) return <EmptyState title="No evidence associations" description="The backend returned no historical evidence associations for this incident." />

  return (
    <div className="incident-correction-workspace">
      <div className="incident-correction-toolbar">
        <div>
          <strong>Association corrections</strong>
          <span>Corrections change incident links; source evidence is never visually or locally deleted.</span>
        </div>
        <button
          className={splitMode ? 'button button--primary' : 'button'}
          type="button"
          onClick={() => {
            setSplitMode((value) => !value)
            setSelectedEvidence(new Set())
            setSplitReason('')
            splitMutation.reset()
          }}
        >
          <Scissors size={15} aria-hidden="true" />{splitMode ? 'Cancel split mode' : 'Split evidence'}
        </button>
      </div>

      {splitMode ? (
        <div className="incident-split-panel">
          <div><strong>{selectedEvidence.size}</strong><span> active evidence record{selectedEvidence.size === 1 ? '' : 's'} selected</span></div>
          <label className="filter-field incident-action-reason">
            <span>Reason</span>
            <textarea value={splitReason} onChange={(event) => setSplitReason(event.target.value)} placeholder="Why should these evidence associations become a separate incident?" />
          </label>
          <button className="button button--primary" type="button" disabled={selectedEvidence.size === 0 || !splitReason.trim() || splitMutation.isPending} onClick={() => setSplitConfirmOpen(true)}>
            <Scissors size={15} aria-hidden="true" />Review split
          </button>
        </div>
      ) : null}

      <MutationMessage error={moveMutation.error ?? splitMutation.error} success={successMessage} />
      {createdIncidentId ? (
        <div className="incident-created-link">
          <span>Created incident</span><TechnicalId value={createdIncidentId} /><Link className="button button--primary" to={`/incidents/${encodeURIComponent(createdIncidentId)}`}>Open new incident<ChevronRight size={14} aria-hidden="true" /></Link>
        </div>
      ) : null}

      <div className="incident-evidence-list">
        {evidence.data.map((association, index) => {
          const event = evidenceRecord(association)
          const id = evidenceId(association)
          const relationship = stringField(association, 'relationship_type')
          const linkReason = stringField(association, 'link_reason')
          const ruleIdentifier = stringField(association, 'deterministic_rule_identifier', 'rule_id', 'rule_identifier')
          const active = booleanField(association, 'active')
          const linkedAt = stringField(association, 'linked_at', 'created_at')
          const unlinkedAt = stringField(association, 'unlinked_at', 'deactivated_at')
          const sourceType = stringField(event, 'source_type')
          const sourceRecord = stringField(event, 'original_source_record_id')
          const eventType = stringField(event, 'canonical_event_type', 'event_type')
          const occurred = stringField(event, 'original_timestamp')
          const isMoveOpen = id !== undefined && moveEvidenceId === id

          return (
            <article className={`incident-evidence-card${active === false ? ' incident-evidence-card--inactive' : ''}`} key={`${id ?? 'association'}-${index}`} data-evidence-id={id ?? undefined}>
              <div className="incident-evidence-card__header">
                <div className="incident-evidence-card__selection">
                  {splitMode && active === true && id ? (
                    <label className="incident-evidence-select">
                      <input type="checkbox" checked={selectedEvidence.has(id)} onChange={() => toggleSelected(id)} aria-label={`Select evidence ${id} for split`} />
                      <span>Select</span>
                    </label>
                  ) : null}
                  <div>
                    <div className="incident-evidence-card__badges">
                      <StatusBadge tone={active === false ? 'neutral' : 'info'}>{active === false ? 'INACTIVE' : active === true ? 'ACTIVE' : 'STATE NOT RETURNED'}</StatusBadge>
                      {relationship ? <span className="overview-meta-chip">{relationship}</span> : null}
                      {sourceType ? <span className="overview-meta-chip">{sourceType}</span> : null}
                    </div>
                    <h3>{eventType ?? 'Evidence event'}</h3>
                  </div>
                </div>
                <div className="incident-evidence-card__actions">
                  {active === true && id && !splitMode ? <button className="button" type="button" onClick={() => isMoveOpen ? cancelMove() : openMove(id)}><ArrowRightLeft size={14} aria-hidden="true" />{isMoveOpen ? 'Cancel move' : 'Move evidence'}</button> : null}
                  {id ? <TechnicalId value={id} /> : null}
                </div>
              </div>

              {isMoveOpen ? (
                <div className="incident-move-panel">
                  <div className="incident-move-panel__note">Only real incidents from this machine are offered as targets. The current source incident is excluded.</div>
                  {targetIncidents.isPending ? <LoadingSkeleton width="100%" height={48} label="Move targets loading" /> : targetIncidents.isError ? <ErrorState title="Move targets unavailable" description="Same-machine incidents could not be loaded from the backend." /> : (
                    <>
                      <label className="filter-field">
                        <span>Target incident</span>
                        <select value={moveTargetId} onChange={(event) => setMoveTargetId(event.target.value)}>
                          <option value="">Select target incident</option>
                          {targetOptions.map((target) => <option key={target.id} value={target.id}>{target.status} · {shortId(target.id)}</option>)}
                        </select>
                      </label>
                      {targetOptions.length === 0 ? <p className="incident-action-hint">No other same-machine incidents were returned by the backend.</p> : null}
                      <label className="filter-field incident-action-reason">
                        <span>Reason</span>
                        <textarea value={moveReason} onChange={(event) => setMoveReason(event.target.value)} placeholder="Why is this association incorrect?" />
                      </label>
                      <button className="button button--primary" type="button" disabled={!moveTargetId || !moveReason.trim() || moveMutation.isPending} onClick={() => setMoveConfirmOpen(true)}>Review move</button>
                    </>
                  )}
                </div>
              ) : null}

              <dl className="incident-evidence-card__facts">
                <div><dt>Link reason</dt><dd>{displayValue(linkReason, 'Not returned')}</dd></div>
                <div><dt>Deterministic rule</dt><dd>{displayValue(ruleIdentifier, 'Not returned')}</dd></div>
                <div><dt>Linked</dt><dd>{formatDateTime(linkedAt) ?? displayValue(linkedAt, 'Not returned')}</dd></div>
                <div><dt>Unlinked</dt><dd>{formatDateTime(unlinkedAt) ?? displayValue(unlinkedAt, active === false ? 'Not returned' : '—')}</dd></div>
                <div><dt>Occurred</dt><dd>{formatDateTime(occurred) ?? displayValue(occurred, 'Not returned')}</dd></div>
                <div><dt>Source record</dt><dd>{sourceRecord ? <TechnicalId value={sourceRecord} /> : 'Not returned'}</dd></div>
              </dl>

              <div className="incident-evidence-card__inspectors">
                <JsonInspector label="Canonical payload" value={evidencePayload(association)} />
                <JsonInspector label="Raw source payload" value={evidenceRawPayload(association)} />
                <JsonInspector label="Provenance" value={evidenceProvenance(association)} />
              </div>
            </article>
          )
        })}
      </div>

      <ConfirmDialog
        open={moveConfirmOpen}
        title="Confirm evidence move"
        description={`Move evidence ${moveEvidenceId ?? ''} from source incident ${incidentId} to target incident ${moveTargetId || ''}? Reason: ${moveReason.trim() || 'Not provided'}. The evidence record itself will not be deleted.`}
        confirmLabel={moveMutation.isPending ? 'Moving…' : 'Move association'}
        onConfirm={() => { void confirmMove() }}
        onCancel={() => setMoveConfirmOpen(false)}
      />
      <ConfirmDialog
        open={splitConfirmOpen}
        title="Confirm incident split"
        description={`Source incident: ${incidentId}. Selected evidence records: ${selectedEvidence.size}. Reason: ${splitReason.trim() || 'Not provided'}. The backend will create the new incident and preserve the original evidence records.`}
        confirmLabel={splitMutation.isPending ? 'Splitting…' : 'Split incident'}
        onConfirm={() => { void confirmSplit() }}
        onCancel={() => setSplitConfirmOpen(false)}
      />
    </div>
  )
}

function AuditSection({ audit, openEvidence }: { audit: ReturnType<typeof useIncidentAudit>; openEvidence: (id: string) => void }) {
  if (audit.isPending) return <div className="incident-section-loading">{Array.from({ length: 5 }).map((_, index) => <LoadingSkeleton key={index} width="100%" height={118} label="Incident audit loading" />)}</div>
  if (audit.isError) return <ErrorState title="Audit unavailable" description="The append-only incident audit could not be loaded from the backend." />
  if (audit.data.length === 0) return <EmptyState title="No audit events" description="The backend returned no audit events for this incident." />

  return (
    <div className="incident-audit-list">
      {audit.data.map((event, index) => {
        const action = stringField(event, 'action_type', 'action') ?? 'UNKNOWN_ACTION'
        const presentation = auditPresentation[action] ?? { Icon: ClipboardList, tone: 'neutral' as const }
        const occurredAt = stringField(event, 'occurred_at', 'timestamp', 'created_at')
        const actor = stringField(event, 'actor_ref', 'actor_id')
        const id = stringField(event, 'id')
        const linkedEvidence = auditEvidenceId(event)
        const Icon = presentation.Icon

        return (
          <article className="incident-audit-event" key={id ?? `${action}-${index}`}>
            <div className="incident-audit-event__rail"><span><Icon size={15} aria-hidden="true" /></span></div>
            <div className="incident-audit-event__body">
              <div className="incident-audit-event__header">
                <StatusBadge tone={presentation.tone}>{action}</StatusBadge>
                <time>{formatDateTime(occurredAt) ?? displayValue(occurredAt, 'Timestamp not returned')}</time>
              </div>
              <div className="incident-audit-event__meta">
                {actor ? <span>Actor: <span className="technical-text">{actor}</span></span> : null}
                {id ? <TechnicalId value={id} /> : null}
                {linkedEvidence ? <button className="incident-evidence-link" type="button" onClick={() => openEvidence(linkedEvidence)}>Evidence <TechnicalId value={linkedEvidence} /></button> : null}
              </div>
              <JsonInspector label="Structured audit payload" value={event} />
            </div>
          </article>
        )
      })}
    </div>
  )
}

function VerificationRunCard({ run, index }: { run: VerificationRun; index: number }) {
  const [showDetail, setShowDetail] = useState(false)
  const id = stringField(run, 'id', 'run_id')
  const result = stringField(run, 'result', 'status')
  const ruleName = stringField(run, 'rule_name', 'verification_rule_name')
  const ruleIdentifier = stringField(run, 'rule_identifier', 'verification_rule_id', 'rule_id')
  const ruleType = stringField(run, 'rule_type')
  const windowMinutes = primitiveField(run, 'window_minutes')
  const started = stringField(run, 'started_at')
  const windowEnd = stringField(run, 'window_ends_at', 'window_end')
  const completed = stringField(run, 'completed_at')
  const evidenceIds = arrayField(run, 'evidence_event_ids')
  const detail = useVerificationRun(id ?? '', Boolean(id && showDetail))

  const tone = result === 'SUCCEEDED' ? 'success' : result === 'RECURRENCE_DETECTED' ? 'danger' : result ? statusTone(result) : 'neutral'

  return (
    <article className="verification-run-card" key={id ?? `verification-${index}`}>
      <div className="verification-run-card__header">
        <div>{result ? <StatusBadge tone={tone}>{result}</StatusBadge> : <StatusBadge>RESULT NOT RETURNED</StatusBadge>}</div>
        {id ? <TechnicalId value={id} /> : null}
      </div>
      <div className="verification-window" aria-label="Verification window">
        <span><small>Started</small>{formatDateTime(started) ?? displayValue(started, 'Not returned')}</span>
        <div className="verification-window__line" aria-hidden="true"><i /><i /></div>
        <span><small>Window ends</small>{formatDateTime(windowEnd) ?? displayValue(windowEnd, 'Not returned')}</span>
      </div>
      <dl>
        <div><dt>Rule name</dt><dd>{displayValue(ruleName, 'Not returned')}</dd></div>
        <div><dt>Rule identifier</dt><dd>{displayValue(ruleIdentifier, 'Not returned')}</dd></div>
        <div><dt>Rule type</dt><dd>{displayValue(ruleType, 'Not returned')}</dd></div>
        <div><dt>Window minutes</dt><dd>{displayValue(windowMinutes, 'Not returned')}</dd></div>
        <div><dt>Completed</dt><dd>{formatDateTime(completed) ?? displayValue(completed, 'Pending / not returned')}</dd></div>
        <div><dt>Evidence records</dt><dd>{evidenceIds.length > 0 ? evidenceIds.length : 'None returned'}</dd></div>
      </dl>
      {evidenceIds.length > 0 ? <JsonInspector label="Verification evidence IDs" value={evidenceIds} /> : null}
      <JsonInspector label="Verification list record" value={run} />
      {id ? (
        <div className="verification-run-card__detail-action">
          <button className="button" type="button" onClick={() => setShowDetail((value) => !value)}>{showDetail ? 'Hide persisted run detail' : 'Load persisted run detail'}</button>
          {showDetail && detail.isPending ? <LoadingSkeleton width="100%" height={80} label="Verification run detail loading" /> : null}
          {showDetail && detail.isError ? <ErrorState title="Run detail unavailable" description="The persisted verification run could not be loaded." /> : null}
          {showDetail && detail.data ? <JsonInspector label="Persisted run detail" value={detail.data} /> : null}
        </div>
      ) : null}
    </article>
  )
}

function VerificationSection({
  verifications,
  incidentId,
  incidentStatus,
}: {
  verifications: ReturnType<typeof useIncidentVerifications>
  incidentId: string
  incidentStatus: string
}) {
  const startMutation = useStartIncidentVerification()
  const evaluateMutation = useEvaluateDueVerifications()
  const canStart = incidentStatus === 'OPEN' || incidentStatus === 'RECURRED'
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  const start = async () => {
    setSuccessMessage(null)
    try {
      await startMutation.mutateAsync(incidentId)
      setSuccessMessage('Verification was started by the backend. Incident, audit, verification history, overview and Evidence Bundle are being refreshed from authoritative state.')
    } catch {
      // MutationMessage renders the structured backend error.
    }
  }

  const evaluate = async () => {
    setSuccessMessage(null)
    try {
      await evaluateMutation.mutateAsync()
      setSuccessMessage('Due verification evaluation completed. Only runs evaluated by the backend are represented in the operation response; authoritative incident state is being refreshed.')
    } catch {
      // MutationMessage renders the structured backend error.
    }
  }

  return (
    <div className="verification-workspace">
      <div className="verification-actions">
        <div>
          <strong>Backend-owned lifecycle</strong>
          <span>OPEN → VERIFYING; due evaluation may later produce VERIFIED or RECURRED. The UI never marks an incident VERIFIED directly.</span>
        </div>
        <div className="verification-actions__buttons">
          {canStart ? <button className="button button--primary" type="button" disabled={startMutation.isPending} onClick={() => { void start() }}><PlayCircle size={15} aria-hidden="true" />{startMutation.isPending ? 'Starting…' : 'Start Verification'}</button> : null}
          <button className="button" type="button" disabled={evaluateMutation.isPending} onClick={() => { void evaluate() }}><RefreshCw size={15} aria-hidden="true" />{evaluateMutation.isPending ? 'Evaluating…' : 'Evaluate due verifications'}</button>
        </div>
      </div>

      <MutationMessage error={startMutation.error ?? evaluateMutation.error} success={successMessage} />
      {evaluateMutation.data ? <JsonInspector label="Last evaluate-due response" value={evaluateMutation.data} /> : null}

      {verifications.isPending ? <div className="incident-section-loading">{Array.from({ length: 3 }).map((_, index) => <LoadingSkeleton key={index} width="100%" height={150} label="Verification history loading" />)}</div> : null}
      {verifications.isError ? <ErrorState title="Verification unavailable" description="Verification history could not be loaded from the backend." /> : null}
      {!verifications.isPending && !verifications.isError && verifications.data.length === 0 ? <EmptyState title="No verification runs" description="No persisted verification runs were returned for this incident." /> : null}
      {!verifications.isPending && !verifications.isError && verifications.data.length > 0 ? <div className="verification-run-list">{verifications.data.map((run, index) => <VerificationRunCard key={stringField(run, 'id', 'run_id') ?? index} run={run} index={index} />)}</div> : null}
    </div>
  )
}

function numberField(record: Record<string, unknown>, ...keys: string[]): number | null {
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'number' && Number.isFinite(value)) return value
  }
  return null
}

function bundleEvidenceRecord(value: unknown): Record<string, unknown> | null {
  const record = recordOf(value)
  if (!record) return null
  return nestedRecord(record, 'evidence', 'event', 'evidence_event') ?? record
}

function bundleEvidenceId(value: unknown): string | null {
  const wrapper = recordOf(value)
  const evidence = bundleEvidenceRecord(value)
  if (!evidence) return null
  return stringField(evidence, 'evidence_id', 'id') ?? (wrapper ? stringField(wrapper, 'evidence_id') : null)
}

function bundleSimilarityScore(value: unknown): number | null {
  const wrapper = recordOf(value)
  const evidence = bundleEvidenceRecord(value)
  return (wrapper ? numberField(wrapper, 'similarity_score', 'score') : null) ?? (evidence ? numberField(evidence, 'similarity_score', 'score') : null)
}

function bundleStatusReason(bundle: EvidenceBundleResponse): string | null {
  const completeness = recordOf(bundle.completeness)
  return stringField(bundle, 'reason', 'status_reason') ?? (completeness ? stringField(completeness, 'reason', 'status_reason') : null)
}

function bundleStatusTone(status: string): 'neutral' | 'info' | 'success' | 'warning' | 'danger' {
  if (status === 'READY') return 'success'
  if (status === 'PARTIAL') return 'warning'
  if (status === 'INSUFFICIENT_EVIDENCE') return 'danger'
  return 'neutral'
}

function BundleEvidenceCard({
  item,
  source,
  highlighted,
}: {
  item: unknown
  source: 'PRIMARY' | 'EXACT' | 'SEMANTIC'
  highlighted: boolean
}) {
  const wrapper = recordOf(item)
  const evidence = bundleEvidenceRecord(item)
  if (!evidence) return <JsonInspector label={`${titleCaseToken(source)} evidence record`} value={item} />

  const id = bundleEvidenceId(item)
  const sourceType = stringField(evidence, 'source_type')
  const eventType = stringField(evidence, 'canonical_event_type', 'event_type')
  const occurred = stringField(evidence, 'original_timestamp')
  const componentId = stringField(evidence, 'component_id')
  const similarity = source === 'SEMANTIC' ? bundleSimilarityScore(item) : null
  const payload = evidence.canonical_payload ?? evidence.payload ?? null

  return (
    <article
      className={`bundle-evidence-card bundle-evidence-card--${source.toLowerCase()}${highlighted ? ' bundle-evidence-card--highlighted' : ''}`}
      data-bundle-evidence-id={id ?? undefined}
    >
      <div className="bundle-evidence-card__header">
        <div className="bundle-evidence-card__badges">
          <StatusBadge tone={source === 'PRIMARY' ? 'info' : source === 'EXACT' ? 'success' : 'neutral'}>{source}</StatusBadge>
          {sourceType ? <span className="overview-meta-chip">{sourceType}</span> : null}
          {eventType ? <span className="overview-meta-chip">{eventType}</span> : null}
          {similarity !== null ? <span className="bundle-similarity">Similarity {similarity}</span> : null}
        </div>
        {id ? <TechnicalId value={id} /> : null}
      </div>
      <dl className="bundle-evidence-card__facts">
        <div><dt>Occurred</dt><dd>{formatDateTime(occurred) ?? displayValue(occurred, 'Not returned')}</dd></div>
        <div><dt>Component</dt><dd>{componentId ? <TechnicalId value={componentId} /> : 'Not returned'}</dd></div>
      </dl>
      {payload !== null ? <JsonInspector label="Canonical payload" value={payload} /> : null}
      {wrapper && wrapper !== evidence ? <JsonInspector label="Selection metadata" value={wrapper} /> : null}
    </article>
  )
}

function BundleLane({
  title,
  description,
  priority,
  icon: Icon,
  items,
  source,
  highlightedEvidenceId,
}: {
  title: string
  description: string
  priority: string
  icon: typeof Database
  items: unknown[]
  source: 'PRIMARY' | 'EXACT' | 'SEMANTIC'
  highlightedEvidenceId: string | null
}) {
  return (
    <section className={`bundle-lane bundle-lane--${source.toLowerCase()}`}>
      <header className="bundle-lane__header">
        <span className="bundle-lane__icon"><Icon size={16} aria-hidden="true" /></span>
        <div>
          <div className="bundle-lane__title-row"><h4>{title}</h4><span>{priority}</span></div>
          <p>{description}</p>
        </div>
      </header>
      {items.length === 0 ? (
        <div className="bundle-lane__empty">No evidence records returned in this bundle section.</div>
      ) : (
        <div className="bundle-evidence-list">
          {items.map((item, index) => {
            const id = bundleEvidenceId(item)
            return <BundleEvidenceCard key={id ?? `${source}-${index}`} item={item} source={source} highlighted={Boolean(id && id === highlightedEvidenceId)} />
          })}
        </div>
      )}
    </section>
  )
}

function scrollIntoViewIfSupported(element: Element | null, options: ScrollIntoViewOptions) {
  if (!element) return
  const scrollIntoView = (element as Element & { scrollIntoView?: (options?: ScrollIntoViewOptions | boolean) => void }).scrollIntoView
  if (typeof scrollIntoView === 'function') scrollIntoView.call(element, options)
}

function EvidenceBundleSection({
  incidentId,
  enabled,
  highlightedEvidenceId,
}: {
  incidentId: string
  enabled: boolean
  highlightedEvidenceId: string | null
}) {
  const bundle = useEvidenceBundle(incidentId, enabled)

  useEffect(() => {
    if (!enabled || !highlightedEvidenceId || !bundle.data) return
    const timer = window.setTimeout(() => {
      const escape = typeof CSS !== 'undefined' && typeof CSS.escape === 'function'
        ? CSS.escape(highlightedEvidenceId)
        : highlightedEvidenceId.replace(/"/g, '\\"')
      scrollIntoViewIfSupported(
        document.querySelector(`[data-bundle-evidence-id="${escape}"]`),
        { behavior: 'auto', block: 'center' },
      )
    }, 0)
    return () => window.clearTimeout(timer)
  }, [bundle.data, enabled, highlightedEvidenceId])

  if (!enabled) return null
  if (bundle.isPending) return <div className="incident-section-loading"><LoadingSkeleton width="100%" height={320} label="Evidence bundle loading" /></div>
  if (bundle.isError) return <ErrorState title="Evidence Bundle unavailable" description="The deterministic evidence bundle could not be loaded from the backend." />

  const data = bundle.data
  const status = data.status ?? 'UNKNOWN'
  const reason = bundleStatusReason(data)
  const completeness = recordOf(data.completeness) ?? {}
  const semantic = nestedRecord(completeness, 'semantic_retrieval')
  const semanticConfigured = semantic && typeof semantic.configured === 'boolean' ? semantic.configured : null
  const semanticAttempted = semantic && typeof semantic.attempted === 'boolean' ? semantic.attempted : null
  const semanticFailed = semantic && typeof semantic.failed === 'boolean' ? semantic.failed : null
  const semanticFailures = semantic ? arrayField(semantic, 'failures') : []
  const queriedPrimaryIds = semantic ? arrayField(semantic, 'queried_primary_evidence_ids').filter((value): value is string => typeof value === 'string') : []

  return (
    <div className="evidence-bundle-view">
      <div className="evidence-bundle-view__header">
        <div>
          <span className="page-eyebrow">Deterministic evidence set</span>
          <h3>Evidence Bundle</h3>
          <p>Primary evidence is authoritative incident evidence. Exact history is deterministic historical context. Semantic history is similarity-based enrichment and does not become authoritative because it is similar.</p>
        </div>
        <StatusBadge tone={bundleStatusTone(status)}>{status}</StatusBadge>
      </div>

      <div className={`bundle-status bundle-status--${status.toLowerCase()}`}>
        <strong>Bundle status: {status}</strong>
        <span>Reason: {reason ?? 'No additional reason returned by the backend.'}</span>
      </div>

      {semanticConfigured === false ? (
        <div className="semantic-retrieval-state semantic-retrieval-state--neutral"><Search size={16} aria-hidden="true" /><div><strong>Semantic retrieval not configured for this bundle</strong><span>Primary incident evidence and exact deterministic history remain available.</span></div></div>
      ) : null}
      {semanticFailed === true ? (
        <div className="semantic-retrieval-state semantic-retrieval-state--warning"><AlertTriangle size={16} aria-hidden="true" /><div><strong>Semantic retrieval unavailable; deterministic evidence remains available</strong><span>The bundle remains usable according to its backend status. No global vector-service status is inferred here.</span></div></div>
      ) : null}
      {semanticConfigured === true && semanticAttempted === true && semanticFailed === false ? (
        <div className="semantic-retrieval-state semantic-retrieval-state--info"><Search size={16} aria-hidden="true" /><div><strong>Semantic retrieval attempted for this bundle</strong><span>Any semantic matches below remain similarity-based enrichment.</span></div></div>
      ) : null}

      {semantic ? (
        <details className="bundle-semantic-details">
          <summary>Semantic retrieval details</summary>
          <div className="bundle-semantic-details__grid">
            <div><span>Configured</span><strong>{semanticConfigured === null ? 'Not returned' : semanticConfigured ? 'Yes' : 'No'}</strong></div>
            <div><span>Attempted</span><strong>{semanticAttempted === null ? 'Not returned' : semanticAttempted ? 'Yes' : 'No'}</strong></div>
            <div><span>Failed</span><strong>{semanticFailed === null ? 'Not returned' : semanticFailed ? 'Yes' : 'No'}</strong></div>
          </div>
          {queriedPrimaryIds.length > 0 ? <div className="bundle-semantic-ids"><span>Queried primary evidence IDs</span>{queriedPrimaryIds.map((id) => <TechnicalId key={id} value={id} />)}</div> : null}
          {semanticFailures.length > 0 ? <JsonInspector label="Semantic retrieval failures" value={semanticFailures} /> : null}
        </details>
      ) : null}

      <div className="bundle-priority-note">
        <span>Evidence priority</span><strong>Primary</strong><ChevronRight size={13} aria-hidden="true" /><strong>Exact</strong><ChevronRight size={13} aria-hidden="true" /><strong>Semantic</strong>
      </div>

      <div className="evidence-bundle-lanes">
        <BundleLane
          title="PRIMARY INCIDENT EVIDENCE"
          description="Canonical evidence actively associated with this incident."
          priority="Priority 1"
          icon={CircleDot}
          items={Array.isArray(data.primary_incident_evidence) ? data.primary_incident_evidence : []}
          source="PRIMARY"
          highlightedEvidenceId={highlightedEvidenceId}
        />
        <BundleLane
          title="EXACT HISTORY"
          description="Deterministically selected historical evidence from authoritative storage."
          priority="Priority 2"
          icon={Database}
          items={Array.isArray(data.selected_exact_history) ? data.selected_exact_history : []}
          source="EXACT"
          highlightedEvidenceId={highlightedEvidenceId}
        />
        <BundleLane
          title="SEMANTIC HISTORY"
          description="Similarity-selected historical evidence. Similarity is not proof of equivalence or authority."
          priority="Priority 3"
          icon={Search}
          items={Array.isArray(data.selected_semantic_history) ? data.selected_semantic_history : []}
          source="SEMANTIC"
          highlightedEvidenceId={highlightedEvidenceId}
        />
      </div>

      <div className="bundle-supporting-grid">
        <JsonInspector label="Verification context" value={data.verification_context} />
        <JsonInspector label="Evidence-time context snapshots" value={data.evidence_time_context_snapshots} />
        <JsonInspector label="Provenance index" value={data.provenance_index} />
        <JsonInspector label="Completeness" value={data.completeness} />
      </div>
    </div>
  )
}

const fallbackDescriptions: Record<string, string> = {
  AI_DISABLED: 'AI analysis is disabled by local configuration.',
  AI_PROVIDER_NOT_CONFIGURED: 'No advisory AI provider is configured.',
  AI_PROVIDER_UNAVAILABLE: 'The configured advisory AI provider is unavailable.',
  AI_PROVIDER_ERROR: 'The advisory AI provider returned an operational error.',
  AI_TIMEOUT: 'The advisory AI request exceeded the backend timeout.',
  MALFORMED_OUTPUT: 'The generated response did not satisfy the backend parser.',
  UNKNOWN_CITATION: 'The generated response cited evidence outside the sealed bundle.',
  PROHIBITED_CLAIM: 'The generated response violated the backend claim policy.',
  INSUFFICIENT_EVIDENCE: 'The deterministic Evidence Bundle is insufficient for advisory analysis.',
}

function EvidenceCitation({ id, onOpen }: { id: string; onOpen: (id: string) => void }) {
  return <button className="ai-evidence-citation" type="button" onClick={() => onOpen(id)}><Link2 size={12} aria-hidden="true" /><TechnicalId value={id} /></button>
}

function AiClaim({ title, claim, onCitation }: { title: string; claim: CitedAIClaim; onCitation: (id: string) => void }) {
  return (
    <article className="ai-claim">
      <span className="ai-claim__label">{title}</span>
      <p>{claim.text}</p>
      <div className="ai-claim__citations">
        {claim.evidence_ids.length > 0 ? claim.evidence_ids.map((id) => <EvidenceCitation key={id} id={id} onOpen={onCitation} />) : <span className="ai-claim__no-citation">No evidence IDs returned for this claim.</span>}
      </div>
    </article>
  )
}

function AiSection({ incidentId, onCitation }: { incidentId: string; onCitation: (id: string) => void }) {
  const analysis = useAnalyzeIncidentEvidence()
  const validated = analysis.data?.result_type === 'VALIDATED_AI' ? analysis.data.validated_ai : null
  const fallback = analysis.data?.result_type === 'FALLBACK' ? analysis.data.fallback : null

  return (
    <div className="ai-analysis-workspace">
      <div className="ai-advisory-note">
        <Bot size={18} aria-hidden="true" />
        <div>
          <strong>Advisory, evidence-grounded interpretation</strong>
          <span>AI analysis runs only after this explicit action and cannot change canonical incident, verification, evidence, or return-to-service state.</span>
        </div>
      </div>

      <div className="ai-analysis-action">
        <div><span className="page-eyebrow">Explicit action</span><strong>Analyze the backend-constructed Evidence Bundle</strong></div>
        <button className="button button--primary" type="button" disabled={analysis.isPending} onClick={() => analysis.mutate(incidentId)}>
          <Sparkles size={15} aria-hidden="true" />{analysis.isPending ? 'Analyzing…' : 'Analyze Evidence'}
        </button>
      </div>

      {analysis.isError ? <MutationMessage error={analysis.error} /> : null}
      {!analysis.data && !analysis.isPending && !analysis.isError ? <EmptyState title="No AI analysis requested" description="Press Analyze Evidence to request one advisory analysis. The action is never run automatically." /> : null}
      {analysis.isPending ? <div className="incident-section-loading"><LoadingSkeleton width="100%" height={260} label="AI analysis loading" /></div> : null}

      {fallback ? (
        <div className="ai-fallback-state" role="status">
          <AlertTriangle size={18} aria-hidden="true" />
          <div>
            <strong>AI analysis unavailable. Deterministic evidence remains available.</strong>
            <span>{fallbackDescriptions[fallback.reason] ?? fallback.reason_detail}</span>
            <code>{fallback.reason}</code>
          </div>
        </div>
      ) : null}

      {validated ? (
        <div className="ai-validated-analysis">
          <div className="ai-validated-analysis__header">
            <div><span className="page-eyebrow">Backend validated</span><h3>Evidence-grounded AI analysis</h3></div>
            <StatusBadge tone="success">VALIDATED</StatusBadge>
          </div>
          <section className="ai-claim-group"><h4>Summary</h4><p>{validated.summary}</p></section>
          <section className="ai-claim-group">
            <h4>Validated claims</h4>
            {validated.claims.map((claim, index) => <AiClaim key={`${claim.claim_type}-${index}`} title={claim.claim_type.replaceAll('_', ' ')} claim={claim} onCitation={onCitation} />)}
          </section>
          <section className="ai-claim-group"><h4>Limitations</h4>{validated.limitations.length > 0 ? <ul>{validated.limitations.map((item) => <li key={item}>{item}</li>)}</ul> : <span>No additional limitations returned.</span>}</section>
        </div>
      ) : null}
    </div>
  )
}

export function IncidentDetailPage() {
  const { incidentId = '' } = useParams()
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('overview')
  const [highlightedBundleEvidenceId, setHighlightedBundleEvidenceId] = useState<string | null>(null)
  const evidenceScrollTimerRef = useRef<number | null>(null)
  const incident = useIncident(incidentId)
  const evidence = useIncidentEvidence(incidentId)
  const audit = useIncidentAudit(incidentId)
  const verifications = useIncidentVerifications(incidentId)

  const incidentRecord = recordOf(incident.data)
  const machineId = incidentRecord ? stringField(incidentRecord, 'machine_id') ?? '' : ''
  const machine = useCurrentMachine()
  const machineLabel = machine.data ? machineIdentity(machine.data) : 'Configured machine unavailable'

  const isNotFound = incident.isError && incident.error instanceof ApiError && incident.error.status === 404
  const title = useMemo(() => {
    if (!incidentRecord) return 'Incident'
    const status = stringField(incidentRecord, 'status')
    return status ? `${titleCaseToken(status)} incident` : 'Incident'
  }, [incidentRecord])

  useEffect(() => () => {
    if (evidenceScrollTimerRef.current !== null) {
      window.clearTimeout(evidenceScrollTimerRef.current)
      evidenceScrollTimerRef.current = null
    }
  }, [])

  const openEvidence = (id: string) => {
    setActiveTab('evidence')
    if (evidenceScrollTimerRef.current !== null) window.clearTimeout(evidenceScrollTimerRef.current)
    evidenceScrollTimerRef.current = window.setTimeout(() => {
      const escape = typeof CSS !== 'undefined' && typeof CSS.escape === 'function' ? CSS.escape(id) : id.replace(/"/g, '\\"')
      scrollIntoViewIfSupported(
        document.querySelector(`[data-evidence-id="${escape}"]`),
        { behavior: 'auto', block: 'center' },
      )
      evidenceScrollTimerRef.current = null
    }, 0)
  }

  const openBundleEvidence = (id: string) => {
    setHighlightedBundleEvidenceId(id)
    setActiveTab('bundle')
  }

  if (isNotFound) {
    return <ErrorState title="Incident not found" description="The backend returned 404 for this incident identifier." />
  }

  if (incident.isError) {
    return <ErrorState title="Incident unavailable" description="The requested incident could not be loaded from the backend." />
  }

  if (machine.isError) {
    return <ErrorState title="Configured machine unavailable" description="The local node could not resolve its configured machine identity." />
  }
  if (incidentRecord && machine.data && machineId && machineId !== machine.data.id) {
    return <ErrorState title="Incident is not part of This Machine" description="The requested incident belongs to a different machine. The local node will not switch machine context." />
  }

  return (
    <div className="incident-detail-page">
      <PageIntro
        eyebrow="Incident memory"
        title={title}
        description="One workspace for authoritative incident state, historical evidence, append-only audit, corrections, and verification."
      >
        <div className="detail-id-row"><span className="detail-id-row__label">Incident ID</span><TechnicalId value={incidentId} /></div>
      </PageIntro>

      {incident.isPending || !incidentRecord ? (
        <GlassPanel className="page-panel incident-workspace-panel"><LoadingSkeleton width="100%" height={160} label="Incident detail loading" /></GlassPanel>
      ) : (
        <>
          <GlassPanel className="incident-workspace-nav" role="navigation" aria-label="Incident workspace sections">
            {tabs.map((tab) => (
              <button className={`incident-workspace-nav__tab${activeTab === tab.id ? ' incident-workspace-nav__tab--active' : ''}`} type="button" key={tab.id} aria-pressed={activeTab === tab.id} aria-controls="incident-workspace-content" onClick={() => setActiveTab(tab.id)}>
                {tab.label}<ChevronRight size={13} aria-hidden="true" />
              </button>
            ))}
          </GlassPanel>

          <section id="incident-workspace-content" className="incident-workspace-content" aria-live="polite">
            {activeTab === 'overview' ? <OverviewSection incident={incidentRecord} machineLabel={machineLabel} /> : null}
            {activeTab === 'evidence' ? <GlassPanel className="page-panel incident-workspace-panel"><SectionHeader title="Evidence associations" description="Active associations can be corrected through backend transactions. Inactive links remain visible as historical memory." /><EvidenceSection evidence={evidence} incidentId={incidentId} machineId={machineId} /></GlassPanel> : null}
            {activeTab === 'audit' ? <GlassPanel className="page-panel incident-workspace-panel"><SectionHeader title="Append-only audit" description="Chronology is preserved from the backend response; structured payloads remain structured." /><AuditSection audit={audit} openEvidence={openEvidence} /></GlassPanel> : null}
            {activeTab === 'verification' ? <GlassPanel className="page-panel incident-workspace-panel"><SectionHeader title="Verification" description="Verification actions invoke backend-owned lifecycle logic; completion is never synthesized in the browser." /><VerificationSection verifications={verifications} incidentId={incidentId} incidentStatus={stringField(incidentRecord, 'status') ?? ''} /></GlassPanel> : null}
            {activeTab === 'bundle' ? <GlassPanel className="page-panel incident-workspace-panel"><EvidenceBundleSection incidentId={incidentId} enabled highlightedEvidenceId={highlightedBundleEvidenceId} /></GlassPanel> : null}
            {activeTab === 'ai' ? <GlassPanel className="page-panel incident-workspace-panel"><SectionHeader title="AI Analysis" description="Advisory analysis is never automatic and cannot mutate authoritative state." /><AiSection incidentId={incidentId} onCitation={openBundleEvidence} /></GlassPanel> : null}
          </section>

          {machineId ? (
            <div className="incident-machine-link"><Box size={15} aria-hidden="true" /><span>Machine</span><Link to={`/machines/${encodeURIComponent(machineId)}`}>{machineLabel}</Link><TechnicalId value={machineId} /></div>
          ) : null}
        </>
      )}
    </div>
  )
}
