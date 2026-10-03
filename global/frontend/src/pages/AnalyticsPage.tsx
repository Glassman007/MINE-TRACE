import { useAnalyticsSummary, useIncidentTrend, useIncidentsBySite, useIncidentsByStatus } from '../api/analytics'
import { ErrorState, GlassPanel, LoadingSkeleton, MetricCard, SectionHeader } from '../components/primitives'
import { PageIntro } from './PageIntro'
import './pages.css'

export function AnalyticsPage() {
  const summary = useAnalyticsSummary()
  const statuses = useIncidentsByStatus()
  const sites = useIncidentsBySite()
  const trend = useIncidentTrend()
  const failed = summary.isError || statuses.isError || sites.isError || trend.isError

  return <div className="global-page">
    <PageIntro eyebrow="Relational facts" title="Fleet analytics" description="Counts and trends are computed from canonical PostgreSQL relations. Qdrant similarity and Groq output are not analytics inputs." />
    {failed ? <ErrorState title="Analytics unavailable" description="One or more relational analytics queries could not be loaded." /> : null}
    <div className="page-grid page-grid--metrics">
      <MetricCard label="Machines" value={summary.data?.machines} loading={summary.isPending} />
      <MetricCard label="Incidents" value={summary.data?.incidents} loading={summary.isPending} />
      <MetricCard label="Unresolved incidents" value={summary.data?.unresolved_incidents} loading={summary.isPending} />
      <MetricCard label="Evidence records" value={summary.data?.evidence} loading={summary.isPending} />
      <MetricCard label="Sessions" value={summary.data?.sessions} loading={summary.isPending} />
      <MetricCard label="Maintenance actions" value={summary.data?.maintenance_actions} loading={summary.isPending} />
      <MetricCard label="Verification runs" value={summary.data?.verification_runs} loading={summary.isPending} />
      <MetricCard label="Unresolved sync conflicts" value={summary.data?.sync_conflicts_unresolved} loading={summary.isPending} />
    </div>
    <div className="page-grid page-grid--split">
      <GlassPanel className="page-panel"><SectionHeader title="Incidents by status" description="Canonical incident state distribution." />{statuses.isPending ? <LoadingSkeleton height={180} /> : <div className="analytics-bars">{statuses.data?.items.map((item) => <div key={item.key}><span>{item.key}</span><strong>{item.count}</strong></div>)}</div>}</GlassPanel>
      <GlassPanel className="page-panel"><SectionHeader title="Incidents by site" description="Site grouping from machine metadata." />{sites.isPending ? <LoadingSkeleton height={180} /> : <div className="analytics-bars">{sites.data?.items.map((item) => <div key={item.key}><span>{item.key}</span><strong>{item.count}</strong></div>)}</div>}</GlassPanel>
    </div>
    <GlassPanel className="page-panel"><SectionHeader title="Incident trend" description="Daily incident counts from relational timestamps." />{trend.isPending ? <LoadingSkeleton height={160} /> : <div className="trend-list">{trend.data?.items.map((item) => <div key={item.day}><time>{item.day}</time><strong>{item.count}</strong></div>)}</div>}</GlassPanel>
  </div>
}
