import { useEffect, useState, type FormEvent } from 'react'
import { Search } from 'lucide-react'
import { useOverview } from '../api/overview'
import { useSemanticSearch } from '../api/semanticSearch'
import { EmptyState, ErrorState, GlassPanel, LoadingSkeleton, SectionHeader, TechnicalId } from '../components/primitives'
import { demoSemanticQuery } from '../demo/demoScenario'
import { formatDateTime } from '../utils/machineFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

export function SearchPage() {
  const overview = useOverview()
  const search = useSemanticSearch()
  const [query, setQuery] = useState('')

  useEffect(() => {
    if (overview.data?.demo_mode && query === '') setQuery(demoSemanticQuery)
  }, [overview.data?.demo_mode, query])

  function submit(event: FormEvent) {
    event.preventDefault()
    const trimmed = query.trim()
    if (trimmed) search.mutate({ query: trimmed, limit: 8 })
  }

  return <div>
    <PageIntro eyebrow="Derived semantic recall" title="Search" description="Semantic results are ranking candidates only. Every result is rehydrated from canonical SQLite evidence and does not prove a shared root cause." />
    <GlassPanel className="page-panel">
      <SectionHeader title="Natural-language evidence search" description="Search is scoped automatically to the configured local machine." />
      <form className="semantic-search-form" onSubmit={submit}>
        <label htmlFor="semantic-query">Query</label>
        <div className="semantic-search-form__row">
          <input id="semantic-query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Describe the evidence you want to recall" />
          <button type="submit" disabled={!query.trim() || search.isPending}><Search size={16} aria-hidden="true" /> Search</button>
        </div>
      </form>
      {search.isPending ? <LoadingSkeleton width="100%" height={180} label="Semantic search running" /> : null}
      {search.isError ? <ErrorState title="Semantic search unavailable" description="The semantic request could not be completed. Canonical local workflows remain available." /> : null}
      {search.data && !search.data.available ? <ErrorState title="Semantic capability degraded" description={`${search.data.failure ?? 'UNAVAILABLE'}${search.data.reason ? `: ${search.data.reason}` : ''}`} /> : null}
      {search.data?.available && (search.data.results?.length ?? 0) === 0 ? <EmptyState title="No semantic candidates" description="The derived index returned no canonical evidence candidates for this query." /> : null}
      {search.data?.available && search.data.results?.length ? <div className="record-list" aria-label="Semantic results">
        {search.data.results.map((result) => <article className="record-row" key={result.evidence_id}>
          <span className="semantic-label">Semantic</span>
          <div className="record-row__body">
            <strong>{result.canonical_event_type}</strong>
            <span>{JSON.stringify(result.canonical_payload)}</span>
            <small>{formatDateTime(result.original_timestamp) ?? result.original_timestamp} · similarity ranking score {result.similarity_score.toFixed(4)}</small>
            <TechnicalId value={result.evidence_id} />
          </div>
        </article>)}
      </div> : null}
    </GlassPanel>
  </div>
}
