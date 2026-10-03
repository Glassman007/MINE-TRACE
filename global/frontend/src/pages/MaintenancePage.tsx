import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMaintenanceQueue } from '../api/maintenance'
import { EmptyState, ErrorState, GlassPanel, LoadingSkeleton, SectionHeader, StatusBadge, TechnicalId } from '../components/primitives'
import { formatDateTime } from '../utils/machineFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

const PAGE_SIZE = 25

export function MaintenancePage() {
  const [offset, setOffset] = useState(0)
  const queue = useMaintenanceQueue({ offset, limit: PAGE_SIZE })
  const total = queue.data?.total ?? 0
  const canPrevious = offset > 0
  const canNext = offset + PAGE_SIZE < total

  return <div className="global-page">
    <PageIntro eyebrow="Canonical work" title="Maintenance queue" description="Read-only maintenance work derived from synchronized incidents, actions and verification state. No predictive priority score is invented." />
    <GlassPanel className="page-panel">
      <SectionHeader title="Maintenance queue" description={queue.data ? `${queue.data.total} canonical queue item${queue.data.total === 1 ? '' : 's'} · ${queue.data.ordering ?? 'deterministic backend ordering'}` : 'Backend-derived maintenance work.'} />
      {queue.isPending ? <LoadingSkeleton width="100%" height={220} label="Maintenance queue loading" /> : queue.isError ? <ErrorState title="Maintenance unavailable" description="The canonical maintenance queue could not be loaded." /> : queue.data.items.length === 0 ? <EmptyState title="No maintenance work" description="No unresolved synchronized work is currently represented in the canonical store." /> : (
        <div className="record-list">
          {queue.data.items.map((item) => <Link key={item.incident_id} className="record-row record-row--link" to={`/incidents/${encodeURIComponent(item.incident_id)}`}>
            <div className="record-row__primary"><StatusBadge>{item.incident_status}</StatusBadge><TechnicalId value={item.incident_id} title="Incident" /></div>
            <dl className="record-row__facts">
              <div><dt>Machine</dt><dd><TechnicalId value={item.machine_id} /></dd></div>
              <div><dt>Component</dt><dd>{item.component_id ? <TechnicalId value={item.component_id} /> : 'Not supplied'}</dd></div>
              <div><dt>Due</dt><dd>{formatDateTime(item.due_time) ?? item.due_state ?? 'Not supplied'}</dd></div>
              <div><dt>Latest maintenance</dt><dd>{item.latest_maintenance_action_type ?? 'None synchronized'}{item.latest_maintenance_at ? ` · ${formatDateTime(item.latest_maintenance_at)}` : ''}</dd></div>
              <div><dt>Verification</dt><dd>{item.latest_verification_result ?? (item.verification_required ? 'Required' : 'No pending requirement')}</dd></div>
              <div><dt>Updated</dt><dd>{formatDateTime(item.updated_at)}</dd></div>
            </dl>
          </Link>)}
        </div>
      )}
      {!queue.isPending && !queue.isError && total > 0 ? <div className="pager"><span>Showing {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}</span><div><button className="button" type="button" disabled={!canPrevious} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button><button className="button" type="button" disabled={!canNext} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button></div></div> : null}
    </GlassPanel>
  </div>
}
