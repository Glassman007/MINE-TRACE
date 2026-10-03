import { Link } from 'react-router-dom'
import { useBackendHealth } from '../api/health'
import { useSyncHealth } from '../api/sync'
import { ErrorState, GlassPanel, LoadingSkeleton, SectionHeader, StatusBadge, TechnicalId } from '../components/primitives'
import { formatDateTime } from '../utils/machineFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

function capabilityTone(status: string) {
  if (status === 'AVAILABLE') return 'success' as const
  if (status === 'DISABLED') return 'neutral' as const
  return 'warning' as const
}

export function SyncPage() {
  const backend = useBackendHealth()
  const sync = useSyncHealth(24)

  return <div className="global-page">
    <PageIntro eyebrow="Synchronization" title="Sync status" description="Canonical ingestion health is shown separately from optional semantic and Groq capabilities." />
    <div className="capability-grid">
      <GlassPanel className="capability-card"><span>Canonical PostgreSQL</span><StatusBadge tone={backend.isSuccess && backend.data.status === 'ok' ? 'success' : 'danger'}>{backend.isPending ? 'CHECKING' : backend.isSuccess ? 'AVAILABLE' : 'UNAVAILABLE'}</StatusBadge><small>{backend.data?.database_role ?? 'canonical_postgresql'}</small></GlassPanel>
      <GlassPanel className="capability-card"><span>Qdrant semantic</span><StatusBadge tone={capabilityTone(sync.data?.semantic.status ?? 'UNAVAILABLE')}>{sync.data?.semantic.status ?? 'CHECKING'}</StatusBadge><small>{sync.data?.semantic.reason ?? 'Derived retrieval capability'}</small></GlassPanel>
      <GlassPanel className="capability-card"><span>Local embeddings</span><StatusBadge tone={capabilityTone(sync.data?.embeddings.status ?? 'UNAVAILABLE')}>{sync.data?.embeddings.status ?? 'CHECKING'}</StatusBadge><small>{sync.data?.embeddings.reason ?? 'FastEmbed capability'}</small></GlassPanel>
      <GlassPanel className="capability-card"><span>Groq AI</span><StatusBadge tone={capabilityTone(sync.data?.ai.status ?? 'DISABLED')}>{sync.data?.ai.status ?? 'CHECKING'}</StatusBadge><small>{sync.data?.ai.reason ?? 'Explicit analysis only'}</small></GlassPanel>
    </div>
    {sync.isPending ? <LoadingSkeleton width="100%" height={260} label="Synchronization status loading" /> : sync.isError ? <ErrorState title="Sync status unavailable" description="Synchronization health could not be loaded. Other canonical pages can still be used independently." /> : <>
      <GlassPanel className="page-panel">
        <SectionHeader title="Machine acknowledgements" description={`Staleness display uses an explicit 24-hour view threshold. ${sync.data.unresolved_conflicts} unresolved conflict${sync.data.unresolved_conflicts === 1 ? '' : 's'}.`} action={<Link className="button" to="/sync/conflicts">View conflicts</Link>} />
        {sync.data.machines.length === 0 ? <p className="muted-copy">No synchronized machines are stored yet.</p> : <div className="record-list">
          {sync.data.machines.map((item) => <article key={item.machine_id} className="record-row">
            <div className="record-row__primary"><StatusBadge tone={item.stale ? 'warning' : 'success'}>{item.acknowledgement_status ?? 'NO RECEIPT'}</StatusBadge><Link to={`/machines/${encodeURIComponent(item.machine_id)}`}><TechnicalId value={item.machine_id} /></Link></div>
            <dl className="record-row__facts"><div><dt>Last sync</dt><dd>{formatDateTime(item.latest_received_at) ?? 'Never'}</dd></div><div><dt>Acknowledged</dt><dd>{formatDateTime(item.latest_acknowledged_at) ?? 'Not acknowledged'}</dd></div><div><dt>Revision</dt><dd>{item.latest_report_revision ?? 'None'}</dd></div><div><dt>Session</dt><dd>{item.latest_session_id ? <TechnicalId value={item.latest_session_id} /> : 'None'}</dd></div><div><dt>Unresolved conflicts</dt><dd>{item.unresolved_conflicts}</dd></div><div><dt>Recency</dt><dd>{item.stale === null || item.stale === undefined ? 'Not evaluated' : item.stale ? 'Stale for this view' : 'Within 24 hours'}</dd></div></dl>
          </article>)}
        </div>}
      </GlassPanel>
    </>}
  </div>
}
