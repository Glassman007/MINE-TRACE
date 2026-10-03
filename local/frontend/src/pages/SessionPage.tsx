import { FileText } from 'lucide-react'
import { useOverview } from '../api/overview'
import { useSessionReport } from '../api/sessions'
import { useSyncStatus } from '../api/sync'
import { EmptyState, ErrorState, GlassPanel, LoadingSkeleton, SectionHeader, StatusBadge, TechnicalId } from '../components/primitives'
import { formatDateTime } from '../utils/machineFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

export function SessionPage() {
  const overview = useOverview()
  const sync = useSyncStatus()
  const reportSessionId = sync.data?.latest_package?.session_id ?? ''
  const report = useSessionReport(reportSessionId, Boolean(reportSessionId))

  return <div>
    <PageIntro eyebrow="Operating session" title="Session" description="Current session state and the immutable report behind the most recent synchronization package." />
    <GlassPanel className="page-panel">
      <SectionHeader title="Current session" description="Persisted canonical session state." />
      {overview.isPending ? <LoadingSkeleton width="100%" height={130} label="Session loading" />
        : overview.isError ? <ErrorState title="Session unavailable" description="The local overview could not be loaded." />
        : overview.data.active_session ? <div className="handover-summary-grid">
          <div className="handover-summary-block"><span>State</span><StatusBadge tone="info">{overview.data.active_session.state}</StatusBadge></div>
          <div className="handover-summary-block"><span>Started</span><strong>{formatDateTime(overview.data.active_session.started_at) ?? overview.data.active_session.started_at}</strong></div>
          <div className="handover-summary-block"><span>Session ID</span><TechnicalId value={overview.data.active_session.session_id} /></div>
          <div className="handover-summary-block"><span>Operating hours</span><strong>{overview.data.active_session.operating_hours ?? 'Not authoritatively supplied'}</strong></div>
        </div> : <EmptyState title="No active session" description="The backend reports no currently open operating session." />}
    </GlassPanel>
    <GlassPanel className="page-panel">
      <SectionHeader title="Most recent closed-session report" description="Resolved from the latest durable synchronization package; the report itself remains immutable." />
      {!reportSessionId ? <EmptyState title="No synchronized session package" description="No closed-session package is currently present in the durable outbox." />
        : report.isPending ? <LoadingSkeleton width="100%" height={180} label="Session report loading" />
        : report.isError ? <ErrorState title="Session report unavailable" description="The backend could not load the immutable report referenced by the latest package." />
        : report.data ? <div className="report-summary">
          <div className="record-row"><span className="record-row__icon"><FileText size={18} aria-hidden="true" /></span><div className="record-row__body"><strong>Report</strong><TechnicalId value={report.data.report_id} /><small>Generated {formatDateTime(report.data.generated_at) ?? report.data.generated_at}</small></div></div>
          <div className="handover-summary-grid">
            <div className="handover-summary-block"><span>Manifest entries</span><strong>{report.data.evidence_manifest.entries.length}</strong></div>
            <div className="handover-summary-block"><span>Incidents</span><strong>{report.data.incident_summaries.length}</strong></div>
            <div className="handover-summary-block"><span>Maintenance actions</span><strong>{report.data.maintenance_actions.length}</strong></div>
            <div className="handover-summary-block"><span>Verification results</span><strong>{report.data.verification_results.length}</strong></div>
            <div className="handover-summary-block"><span>Unresolved work</span><strong>{report.data.unresolved_work.length}</strong></div>
          </div>
        </div> : null}
    </GlassPanel>
  </div>
}
