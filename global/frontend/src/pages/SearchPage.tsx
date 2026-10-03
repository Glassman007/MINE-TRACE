import { type FormEvent, useState } from 'react'
import { Link } from 'react-router-dom'
import { useFleetSemanticSearch } from '../api/semanticSearch'
import { EmptyState, GlassPanel, SectionHeader, StatusBadge, TechnicalId } from '../components/primitives'
import { formatDateTime } from '../utils/machineFormatting'
import { prettyJson } from '../utils/incidentFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

function optional(value: string) { return value.trim() || undefined }

export function SearchPage() {
  const search = useFleetSemanticSearch()
  const [form, setForm] = useState({ query: '', machine_id: '', component_id: '', model: '', site: '', start: '', end: '', top_k: '10' })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!form.query.trim()) return
    search.mutate({
      query: form.query.trim(),
      machine_id: optional(form.machine_id),
      component_id: optional(form.component_id),
      model: optional(form.model),
      site: optional(form.site),
      start: optional(form.start),
      end: optional(form.end),
      top_k: Math.max(1, Math.min(100, Number(form.top_k) || 10)),
    })
  }
  const results = search.data?.results ?? []
  const degraded = search.data && search.data.state !== 'AVAILABLE'

  return <div className="global-page">
    <PageIntro eyebrow="Semantic recall" title="Fleet semantic search" description="Similarity retrieval uses local FastEmbed and Qdrant only to find candidates; every displayed record is hydrated from canonical PostgreSQL." />
    <GlassPanel className="page-panel page-panel--compact">
      <form className="global-filter-grid" onSubmit={submit}>
        <label className="filter-field global-filter-grid__wide"><span>Query</span><input aria-label="Semantic query" value={form.query} onChange={(e) => setForm((v) => ({ ...v, query: e.target.value }))} placeholder="e.g. hydraulic pump whine after repair" /></label>
        {(['machine_id','component_id','model','site','start','end'] as const).map((key) => <label key={key} className="filter-field"><span>{key.replace('_',' ')}</span><input value={form[key]} onChange={(e) => setForm((v) => ({ ...v, [key]: e.target.value }))} placeholder={key === 'start' || key === 'end' ? 'ISO timestamp' : 'Optional exact filter'} /></label>)}
        <label className="filter-field"><span>Top K</span><input type="number" min="1" max="100" value={form.top_k} onChange={(e) => setForm((v) => ({ ...v, top_k: e.target.value }))} /></label>
        <div className="global-filter-actions"><button className="button button--primary" type="submit" disabled={search.isPending || !form.query.trim()}>{search.isPending ? 'Searching…' : 'Search similar evidence'}</button></div>
      </form>
    </GlassPanel>
    {search.isError ? <GlassPanel className="capability-banner capability-banner--danger" role="alert"><strong>Semantic search unavailable</strong><span>The search request failed. Canonical fleet pages remain usable.</span></GlassPanel> : null}
    {degraded ? <GlassPanel className="capability-banner capability-banner--warning" role="status"><strong>Semantic capability degraded</strong><span>{search.data?.reason ?? 'Qdrant or embeddings are unavailable.'}</span></GlassPanel> : null}
    <GlassPanel className="page-panel">
      <SectionHeader title="Similar results" description="Similarity scores rank semantic proximity; they are not confidence or incident probability." />
      {!search.data ? <EmptyState title="Run a semantic search" description="Enter a query to retrieve hydrated canonical evidence from across the fleet." /> : results.length === 0 ? <EmptyState title="No similar results" description={degraded ? 'Semantic retrieval is currently degraded.' : 'Qdrant returned no canonical candidates for this query.'} /> : <div className="record-list">
        {results.map((result) => <article key={result.evidence_id} className="record-row">
          <div className="record-row__primary"><StatusBadge tone="info">Similar result · {result.similarity_score.toFixed(3)}</StatusBadge><TechnicalId value={result.evidence_id} title="Evidence" /></div>
          <dl className="record-row__facts"><div><dt>Machine</dt><dd><Link to={`/machines/${encodeURIComponent(result.machine_id)}`}><TechnicalId value={result.machine_id} /></Link></dd></div><div><dt>Component</dt><dd>{result.component_id ? <TechnicalId value={result.component_id} /> : 'Not supplied'}</dd></div><div><dt>Original time</dt><dd>{formatDateTime(result.original_timestamp)}</dd></div><div><dt>Session</dt><dd>{result.session_id ? <TechnicalId value={result.session_id} /> : 'Not supplied'}</dd></div><div><dt>Site / model</dt><dd>{[result.site, result.model].filter(Boolean).join(' · ') || 'Not supplied'}</dd></div><div><dt>Incident links</dt><dd>{result.incident_ids.length || 'None'}</dd></div></dl>
          <div className="canonical-payload"><strong>{result.canonical_event_type}</strong><pre>{prettyJson(result.canonical_payload)}</pre><details><summary>Provenance</summary><pre>{prettyJson(result.provenance)}</pre></details></div>
          {result.incident_ids.length ? <div className="inline-links">{result.incident_ids.map((id) => <Link key={id} to={`/incidents/${encodeURIComponent(id)}`}>Incident {id.slice(0, 8)}</Link>)}</div> : null}
        </article>)}
      </div>}
    </GlassPanel>
  </div>
}
