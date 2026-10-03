import { Link, useParams } from 'react-router-dom'
import { useIncident, useIncidentAudit, useIncidentEvidence, useIncidentMaintenanceActions, useIncidentVerifications } from '../api/incidents'
import { useMachine } from '../api/machines'
import { EmptyState, ErrorState, GlassPanel, LoadingSkeleton, SectionHeader, StatusBadge, TechnicalId } from '../components/primitives'
import { formatDateTime, machineIdentity } from '../utils/machineFormatting'
import { prettyJson } from '../utils/incidentFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

export function IncidentDetailPage() {
  const incidentId = useParams().incidentId ?? ''
  const incident = useIncident(incidentId)
  const evidence = useIncidentEvidence(incidentId)
  const maintenance = useIncidentMaintenanceActions(incidentId)
  const verifications = useIncidentVerifications(incidentId)
  const audit = useIncidentAudit(incidentId)
  const machine = useMachine(incident.data?.machine_id ?? '', Boolean(incident.data?.machine_id))

  if (incident.isPending) return <LoadingSkeleton width="100%" height={320} label="Incident loading" />
  if (incident.isError || !incident.data) return <ErrorState title="Incident unavailable" description="The synchronized incident could not be loaded." />
  const item = incident.data

  return <div className="incident-detail-page">
    <PageIntro eyebrow="Read-only synchronized incident" title={`Incident ${item.incident_id.slice(0, 8)}`} description={`Machine: ${machine.data ? machineIdentity(machine.data) : item.machine_id}`} />
    <GlassPanel className="page-panel"><SectionHeader title="Canonical incident" description="Central state synchronized from the edge; no correction, verification execution or return-to-service action is available here." />
      <dl className="incident-overview-grid"><div><dt>Status</dt><dd><StatusBadge>{item.status}</StatusBadge></dd></div><div><dt>Machine</dt><dd><Link to={`/machines/${encodeURIComponent(item.machine_id)}`}><TechnicalId value={item.machine_id} /></Link></dd></div><div><dt>Severity</dt><dd>{item.severity ?? 'Not supplied'}</dd></div><div><dt>Due</dt><dd>{formatDateTime(item.due_time) ?? item.due_state ?? 'Not supplied'}</dd></div><div><dt>Created</dt><dd>{formatDateTime(item.created_at)}</dd></div><div><dt>Updated</dt><dd>{formatDateTime(item.updated_at)}</dd></div></dl>
    </GlassPanel>
    <GlassPanel className="page-panel"><SectionHeader title="Evidence" description="Canonical PostgreSQL evidence with preserved original timestamps and provenance." />
      {evidence.isPending ? <LoadingSkeleton height={140} /> : evidence.data?.length ? evidence.data.map((e) => <article key={e.link_id} className="record-row"><div className="record-row__primary"><strong>{e.canonical_event_type}</strong><TechnicalId value={e.evidence_id} /></div><dl className="record-row__facts"><div><dt>Original time</dt><dd>{formatDateTime(e.original_timestamp)}</dd></div><div><dt>Source</dt><dd>{e.source_type}</dd></div><div><dt>Relationship</dt><dd>{e.relationship_type}</dd></div><div><dt>Component</dt><dd>{e.component_id ? <TechnicalId value={e.component_id} /> : 'Not supplied'}</dd></div></dl><pre>{prettyJson(e.canonical_payload)}</pre><details><summary>Provenance</summary><pre>{prettyJson(e.provenance)}</pre></details></article>) : <EmptyState title="No evidence" description="No synchronized evidence is linked to this incident." />}
    </GlassPanel>
    <GlassPanel className="page-panel"><SectionHeader title="Maintenance history" description="Synchronized maintenance actions in canonical reverse-chronological order." />
      {maintenance.isPending ? <LoadingSkeleton height={120} /> : maintenance.data?.length ? <div className="record-list">{maintenance.data.map((action) => <article key={action.action_id} className="record-row"><div className="record-row__primary"><strong>{action.action_type}</strong><TechnicalId value={action.action_id} /></div><p>{action.description ?? 'No description supplied'}</p><dl className="record-row__facts"><div><dt>Original time</dt><dd>{formatDateTime(action.original_timestamp)}</dd></div><div><dt>Session</dt><dd>{action.session_id ? <TechnicalId value={action.session_id} /> : 'Not supplied'}</dd></div><div><dt>Component</dt><dd>{action.component_id ? <TechnicalId value={action.component_id} /> : 'Not supplied'}</dd></div><div><dt>Report revision</dt><dd>{action.source_report_revision ?? 'Not supplied'}</dd></div></dl><details><summary>Provenance</summary><pre>{prettyJson(action.provenance)}</pre></details></article>)}</div> : <EmptyState title="No maintenance actions" description="No synchronized maintenance actions are linked to this incident." />}
    </GlassPanel>
    <GlassPanel className="page-panel"><SectionHeader title="Verification history" description="Synchronized outcomes are audit information only; this global UI cannot start or evaluate verification." />
      {verifications.isPending ? <LoadingSkeleton height={120} /> : verifications.data?.length ? verifications.data.map((v) => <div key={v.id} className="incident-collection-row"><StatusBadge>{v.result ?? 'PENDING'}</StatusBadge><TechnicalId value={v.id} /><span>{formatDateTime(v.started_at)}</span></div>) : <EmptyState title="No verification history" description="No verification runs are synchronized for this incident." />}
    </GlassPanel>
    <GlassPanel className="page-panel"><SectionHeader title="Provenance and audit" description="Append-only synchronized history; there is no browser-side conflict or evidence reassignment." />
      {audit.isPending ? <LoadingSkeleton height={120} /> : audit.data?.length ? audit.data.map((a) => <div key={a.id} className="record-row"><div className="record-row__primary"><strong>{a.action}</strong><span>{formatDateTime(a.occurred_at)}</span></div><pre>{prettyJson(a.payload)}</pre></div>) : <EmptyState title="No audit events" description="No synchronized incident audit events are stored." />}
    </GlassPanel>
    <div className="inline-links"><Link className="button" to="/incidents">Back to incidents</Link><Link className="button" to={`/ai?incident=${encodeURIComponent(incidentId)}`}>Analyze with Groq</Link></div>
  </div>
}
