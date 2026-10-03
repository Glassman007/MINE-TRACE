import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useSyncConflicts } from '../api/sync'
import { EmptyState, ErrorState, GlassPanel, LoadingSkeleton, SectionHeader, StatusBadge, TechnicalId } from '../components/primitives'
import { formatDateTime } from '../utils/machineFormatting'
import { prettyJson } from '../utils/incidentFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

const PAGE_SIZE = 20

export function SyncConflictsPage() {
  const [offset, setOffset] = useState(0)
  const [unresolvedOnly, setUnresolvedOnly] = useState(true)
  const conflicts = useSyncConflicts({ offset, limit: PAGE_SIZE, unresolved_only: unresolvedOnly })
  const total = conflicts.data?.total ?? 0

  return <div className="global-page">
    <PageIntro eyebrow="Synchronization" title="Sync conflicts" description="Both incompatible revision identities and metadata are displayed. The browser never merges them automatically." />
    <GlassPanel className="page-panel">
      <SectionHeader title="Conflict records" description="Canonical conflict rows created by deterministic revision policy." action={<label className="toggle-field"><input type="checkbox" checked={unresolvedOnly} onChange={(e) => { setUnresolvedOnly(e.target.checked); setOffset(0) }} /><span>Unresolved only</span></label>} />
      {conflicts.isPending ? <LoadingSkeleton height={240} /> : conflicts.isError ? <ErrorState title="Conflicts unavailable" description="Sync conflicts could not be loaded." /> : conflicts.data.items.length === 0 ? <EmptyState title="No conflicts" description="No synchronization conflicts match the current view." /> : <div className="record-list">
        {conflicts.data.items.map((item) => <article key={item.conflict_id} className="record-row conflict-row">
          <div className="record-row__primary"><StatusBadge tone={item.resolution_status === 'UNRESOLVED' ? 'warning' : 'success'}>{item.resolution_status}</StatusBadge><TechnicalId value={item.conflict_id} title="Conflict" /><span>{item.conflict_type}</span></div>
          <dl className="record-row__facts"><div><dt>Machine</dt><dd><Link to={`/machines/${encodeURIComponent(item.source_machine_id)}`}><TechnicalId value={item.source_machine_id} /></Link></dd></div><div><dt>Session</dt><dd><TechnicalId value={item.session_id} /></dd></div><div><dt>Incoming revision</dt><dd>{item.incoming_report_revision}</dd></div><div><dt>Existing revision</dt><dd>{item.existing_report_revision ?? 'None'}</dd></div><div><dt>Detected</dt><dd>{formatDateTime(item.detected_at)}</dd></div><div><dt>Incoming package</dt><dd><TechnicalId value={item.incoming_package_id} /></dd></div></dl>
          <div className="conflict-comparison"><div><h3>Existing revision metadata</h3><code>{item.existing_checksum ?? 'No checksum'}</code><pre>{prettyJson(item.existing_metadata)}</pre></div><div><h3>Incoming revision metadata</h3><code>{item.incoming_checksum ?? 'No checksum'}</code><pre>{prettyJson(item.incoming_metadata)}</pre></div></div>
          {item.resolution_notes ? <p className="muted-copy">Resolution note: {item.resolution_notes}</p> : null}
        </article>)}
      </div>}
      {!conflicts.isPending && !conflicts.isError && total > PAGE_SIZE ? <div className="pager"><span>{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}</span><div><button className="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button><button className="button" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button></div></div> : null}
    </GlassPanel>
  </div>
}
