import { type FormEvent, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useIncidents, type IncidentCollectionParams } from '../api/incidents'
import { EmptyState, ErrorState, GlassPanel, LoadingSkeleton, SectionHeader, StatusBadge, TechnicalId } from '../components/primitives'
import { formatDateTime } from '../utils/machineFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

const PAGE_SIZE = 25

function numberParam(value: string | null, fallback: number) {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback
}

export function IncidentsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const params: IncidentCollectionParams = {
    offset: numberParam(searchParams.get('offset'), 0),
    limit: PAGE_SIZE,
    machine: searchParams.get('machine') || undefined,
    component: searchParams.get('component') || undefined,
    status: searchParams.get('status') || undefined,
    model: searchParams.get('model') || undefined,
    site: searchParams.get('site') || undefined,
    start: searchParams.get('start') || undefined,
    end: searchParams.get('end') || undefined,
  }
  const [draft, setDraft] = useState({ machine: params.machine ?? '', component: params.component ?? '', status: params.status ?? '', model: params.model ?? '', site: params.site ?? '', start: params.start ?? '', end: params.end ?? '' })
  useEffect(() => setDraft({ machine: params.machine ?? '', component: params.component ?? '', status: params.status ?? '', model: params.model ?? '', site: params.site ?? '', start: params.start ?? '', end: params.end ?? '' }), [params.machine, params.component, params.status, params.model, params.site, params.start, params.end])
  const incidents = useIncidents(params)

  const apply = (event: FormEvent) => {
    event.preventDefault()
    const next = new URLSearchParams()
    Object.entries(draft).forEach(([key, value]) => { if (value.trim()) next.set(key, value.trim()) })
    setSearchParams(next)
  }
  const clear = () => { setDraft({ machine: '', component: '', status: '', model: '', site: '', start: '', end: '' }); setSearchParams(new URLSearchParams()) }
  const move = (offset: number) => { const next = new URLSearchParams(searchParams); if (offset > 0) next.set('offset', String(offset)); else next.delete('offset'); setSearchParams(next) }
  const currentOffset = incidents.data?.offset ?? params.offset ?? 0
  const total = incidents.data?.total ?? 0

  return <div className="incidents-page">
    <PageIntro eyebrow="Fleet incidents" title="Incidents" description="Exact PostgreSQL filtering across machine, component, state, time, model and site." />
    <GlassPanel className="page-panel page-panel--compact"><form className="incident-filters" onSubmit={apply}>
      {(['machine','component','status','model','site','start','end'] as const).map((key) => <label key={key} className="filter-field"><span>{key === 'status' ? 'State / status' : key}</span><input value={draft[key]} onChange={(e) => setDraft((value) => ({ ...value, [key]: e.target.value }))} placeholder={key === 'start' || key === 'end' ? 'ISO timestamp' : 'Optional exact filter'} /></label>)}
      <div className="global-filter-actions"><button className="button button--primary" type="submit">Apply filters</button><button className="button" type="button" onClick={clear}>Clear</button></div>
    </form></GlassPanel>
    <GlassPanel className="page-panel"><SectionHeader title="Incident collection" description={incidents.data ? `${incidents.data.total} synchronized incident${incidents.data.total === 1 ? '' : 's'}` : 'Backend incident collection.'} />
      {incidents.isPending ? <LoadingSkeleton width="100%" height={200} /> : incidents.isError ? <ErrorState description="Incident collection unavailable." /> : incidents.data.items.length === 0 ? <EmptyState title="No incidents" description="No incidents match the current filters." /> : (
        <div className="record-list">{incidents.data.items.map((item) => <Link key={item.incident_id} className="record-row record-row--link" to={`/incidents/${encodeURIComponent(item.incident_id)}`}><div className="record-row__primary"><StatusBadge>{item.status}</StatusBadge><TechnicalId value={item.incident_id} /></div><dl className="record-row__facts"><div><dt>Machine</dt><dd><TechnicalId value={item.machine_id} /></dd></div><div><dt>Component</dt><dd>{item.component_id ? <TechnicalId value={item.component_id} /> : 'Not supplied'}</dd></div><div><dt>Site / model</dt><dd>{[item.site_name, item.machine_model].filter(Boolean).join(' · ') || 'Not supplied'}</dd></div><div><dt>First seen</dt><dd>{formatDateTime(item.first_seen_at) ?? 'Not supplied'}</dd></div><div><dt>Last seen</dt><dd>{formatDateTime(item.last_seen_at) ?? 'Not supplied'}</dd></div><div><dt>Report revision</dt><dd>{item.source_report_revision ?? 'Not supplied'}</dd></div></dl></Link>)}</div>
      )}
      {!incidents.isPending && !incidents.isError && total > 0 ? <div className="pager"><span>Showing {currentOffset + 1}–{Math.min(currentOffset + PAGE_SIZE, total)} of {total}</span><div><button className="button" type="button" disabled={currentOffset === 0} onClick={() => move(Math.max(0, currentOffset - PAGE_SIZE))}>Previous</button><button className="button" type="button" disabled={currentOffset + PAGE_SIZE >= total} onClick={() => move(currentOffset + PAGE_SIZE)}>Next</button></div></div> : null}
    </GlassPanel>
  </div>
}
