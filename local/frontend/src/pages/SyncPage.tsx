import { useSyncStatus } from '../api/sync'
import { EmptyState, ErrorState, GlassPanel, LoadingSkeleton, SectionHeader, StatusBadge, TechnicalId } from '../components/primitives'
import { formatDateTime } from '../utils/machineFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

function transportLabel(configured: boolean, available: boolean | null | undefined) {
  if (!configured) return 'Not configured'
  if (available === true) return 'Measured reachable'
  if (available === false) return 'Measured unavailable'
  return 'Not yet measured'
}

export function SyncPage() {
  const sync = useSyncStatus()
  return <div>
    <PageIntro eyebrow="Durable outbox" title="Sync" description="Only measured transport and persisted package/acknowledgement/conflict facts are shown." />
    <GlassPanel className="page-panel">
      <SectionHeader title="Synchronization status" description="Qdrant is not used as synchronization transport or package storage." />
      {sync.isPending ? <LoadingSkeleton width="100%" height={180} label="Sync status loading" />
        : sync.isError ? <ErrorState title="Sync status unavailable" description="The local durable outbox status could not be read." />
        : sync.data ? <>
          <div className="handover-summary-grid">
            <div className="handover-summary-block"><span>Transport</span><strong>{transportLabel(sync.data.transport_configured, sync.data.transport_available)}</strong></div>
            <div className="handover-summary-block"><span>Pending</span><strong>{sync.data.pending_item_count}</strong></div>
            <div className="handover-summary-block"><span>Failed</span><strong>{sync.data.failed_item_count}</strong></div>
            <div className="handover-summary-block"><span>Conflicts</span><strong>{sync.data.conflict_count}</strong></div>
            <div className="handover-summary-block"><span>Last attempt</span><strong>{sync.data.last_transmission_attempt ? (formatDateTime(sync.data.last_transmission_attempt) ?? sync.data.last_transmission_attempt) : 'None'}</strong></div>
            <div className="handover-summary-block"><span>Last acknowledgement</span><strong>{sync.data.last_acknowledgement ? (formatDateTime(sync.data.last_acknowledgement) ?? sync.data.last_acknowledgement) : 'None'}</strong></div>
          </div>
          {sync.data.latest_package ? <div className="record-list"><article className="record-row"><div className="record-row__body"><strong>Most recent package</strong><StatusBadge tone={sync.data.latest_package.state === 'CONFLICT' ? 'warning' : 'neutral'}>{sync.data.latest_package.state}</StatusBadge><TechnicalId value={sync.data.latest_package.package_id} /><small>Attempt count {sync.data.latest_package.attempt_count} · local revision {sync.data.latest_package.local_revision}</small></div></article></div> : null}
          {sync.data.conflicts.length === 0 ? <EmptyState title="No sync conflicts" description="No durable revision conflicts are currently recorded." /> : <div className="record-list">
            {sync.data.conflicts.map((conflict) => <article className="record-row" key={conflict.conflict_id}><div className="record-row__body"><strong>Revision conflict</strong><span>Local revision {conflict.local_revision} · central revision {conflict.central_revision}</span><small>{formatDateTime(conflict.detected_at) ?? conflict.detected_at}</small><TechnicalId value={conflict.conflict_id} /></div></article>)}
          </div>}
          {sync.data.last_error ? <p className="attachment-note">Last transport error: {sync.data.last_error}</p> : null}
        </> : null}
    </GlassPanel>
  </div>
}
