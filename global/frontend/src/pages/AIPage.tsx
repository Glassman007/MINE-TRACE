import { type FormEvent, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAnalyzeFleet } from '../api/ai'
import { GlassPanel, SectionHeader, StatusBadge, TechnicalId } from '../components/primitives'
import { prettyJson } from '../utils/incidentFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

function ids(value: string) { return value.split(',').map((item) => item.trim()).filter(Boolean) }

export function AIPage() {
  const ai = useAnalyzeFleet()
  const [searchParams] = useSearchParams()
  const [form, setForm] = useState(() => ({ prompt: '', machine_ids: searchParams.get('machine') ?? '', incident_ids: searchParams.get('incident') ?? '', session_ids: searchParams.get('session') ?? '', semantic_query: '', semantic_top_k: '5' }))
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!form.prompt.trim()) return
    ai.mutate({
      prompt: form.prompt.trim(),
      machine_ids: ids(form.machine_ids),
      incident_ids: ids(form.incident_ids),
      session_ids: ids(form.session_ids),
      semantic_query: form.semantic_query.trim() || undefined,
      semantic_top_k: Math.max(1, Math.min(20, Number(form.semantic_top_k) || 5)),
    })
  }

  return <div className="global-page">
    <PageIntro eyebrow="Evidence-grounded AI" title="Groq fleet analysis" description="Groq runs only after an explicit request. Backend-supplied canonical context and optional hydrated semantic evidence remain read-only." />
    <GlassPanel className="page-panel page-panel--compact">
      <form className="ai-form" onSubmit={submit}>
        <label className="filter-field ai-form__wide"><span>Analysis request</span><textarea aria-label="Analysis request" rows={5} value={form.prompt} onChange={(e) => setForm((v) => ({ ...v, prompt: e.target.value }))} placeholder="Summarize or compare synchronized fleet evidence…" /></label>
        <label className="filter-field"><span>Machine IDs</span><input value={form.machine_ids} onChange={(e) => setForm((v) => ({ ...v, machine_ids: e.target.value }))} placeholder="Comma-separated, optional" /></label>
        <label className="filter-field"><span>Incident IDs</span><input value={form.incident_ids} onChange={(e) => setForm((v) => ({ ...v, incident_ids: e.target.value }))} placeholder="Comma-separated, optional" /></label>
        <label className="filter-field"><span>Session IDs</span><input value={form.session_ids} onChange={(e) => setForm((v) => ({ ...v, session_ids: e.target.value }))} placeholder="Comma-separated, optional" /></label>
        <label className="filter-field"><span>Optional semantic context</span><input value={form.semantic_query} onChange={(e) => setForm((v) => ({ ...v, semantic_query: e.target.value }))} placeholder="Hydrate similar canonical evidence" /></label>
        <label className="filter-field"><span>Semantic top K</span><input type="number" min="1" max="20" value={form.semantic_top_k} onChange={(e) => setForm((v) => ({ ...v, semantic_top_k: e.target.value }))} /></label>
        <div className="global-filter-actions"><button className="button button--primary" type="submit" disabled={ai.isPending || !form.prompt.trim()}>{ai.isPending ? 'Running…' : 'Run Analysis'}</button></div>
      </form>
    </GlassPanel>
    <GlassPanel className="page-panel">
      <SectionHeader title="Analysis result" description="Claims are validated against evidence IDs before being returned by the backend." />
      {!ai.data && !ai.isError ? <p className="muted-copy">No AI request has been sent. Canonical fleet data is unaffected until and after you choose to run analysis.</p> : null}
      {ai.isError ? <div className="capability-banner capability-banner--danger" role="alert"><strong>AI request failed</strong><span>Groq is unavailable. Canonical PostgreSQL and fleet pages remain operational.</span></div> : null}
      {ai.data ? <div className="ai-result"><StatusBadge tone={ai.data.state === 'AVAILABLE' ? 'success' : 'warning'}>{ai.data.state}</StatusBadge>{ai.data.state === 'DEGRADED' ? <p>{ai.data.reason ?? 'Groq is unavailable or unconfigured.'}</p> : <><h3>Summary</h3><p>{ai.data.summary}</p><h3>Claims</h3><div className="record-list">{(ai.data.claims ?? []).map((claim, index) => <article key={`${claim.claim_type}-${index}`} className="record-row"><strong>{claim.claim_type}</strong><p>{claim.text}</p><div className="inline-links">{claim.evidence_ids.map((id) => <TechnicalId key={id} value={id} />)}</div></article>)}</div><h3>Evidence references</h3>{(ai.data.citations ?? []).map((citation) => <details key={citation.evidence_id}><summary><TechnicalId value={citation.evidence_id} /></summary><pre>{prettyJson(citation.provenance)}</pre></details>)}{ai.data.limitations?.length ? <><h3>Limitations</h3><ul>{ai.data.limitations.map((item) => <li key={item}>{item}</li>)}</ul></> : null}</>}</div> : null}
    </GlassPanel>
  </div>
}
