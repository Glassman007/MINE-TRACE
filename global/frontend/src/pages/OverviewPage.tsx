import { Link } from 'react-router-dom'
import { useOverview } from '../api/overview'
import { EmptyState, ErrorState, GlassPanel, LoadingSkeleton, SectionHeader, StatusBadge, TechnicalId } from '../components/primitives'
import { formatDateTime } from '../utils/machineFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

export function OverviewPage() {
  const overview = useOverview()
  return (
    <div className="overview-page">
      <PageIntro eyebrow="Fleet memory" title="Fleet overview" description="Exact synchronized fleet state from the canonical PostgreSQL store." />
      {overview.isPending ? <LoadingSkeleton width="100%" height={220} label="Fleet overview loading" /> : overview.isError ? (
        <ErrorState title="Fleet overview unavailable" description="The canonical fleet overview could not be loaded." />
      ) : (
        <>
          <div className="metric-grid">
            <GlassPanel><strong>{overview.data.fleet_machine_count}</strong><p>Machines</p></GlassPanel>
            <GlassPanel><strong>{overview.data.unresolved_incident_count}</strong><p>Unresolved incidents</p></GlassPanel>
            <GlassPanel><strong>{overview.data.unresolved_sync_conflicts}</strong><p>Sync conflicts</p></GlassPanel>
            <GlassPanel><strong>{formatDateTime(overview.data.latest_sync_received_at) ?? 'No receipt'}</strong><p>Latest synchronization</p></GlassPanel>
          </div>
          <GlassPanel className="page-panel">
            <SectionHeader title="Recent synchronized sessions" description="Newest session records supplied by edge machines." />
            {overview.data.recent_sessions.length === 0 ? <EmptyState title="No sessions" description="No synchronized sessions are stored yet." /> : (
              <div className="incident-list">
                {overview.data.recent_sessions.map((session) => (
                  <Link key={session.session_id} to={`/machines/${encodeURIComponent(session.machine_id)}`} className="incident-collection-row">
                    <div><StatusBadge>{session.state}</StatusBadge></div>
                    <div><strong>{formatDateTime(session.started_at) ?? session.started_at}</strong><TechnicalId value={session.machine_id} title="Machine" /></div>
                    <div><span>Revision {session.latest_report_revision}</span></div>
                  </Link>
                ))}
              </div>
            )}
          </GlassPanel>
        </>
      )}
    </div>
  )
}
