import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, FileClock, History, Wrench } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { useComponent, useComponentTimeline } from '../api/components'
import { ApiError } from '../api/http'
import { getIncidentEvidence, getIncidentVerifications, incidentKeys, useAllMachineIncidents } from '../api/incidents'
import { useCurrentMachine } from '../api/machines'
import { EmptyState, ErrorState, GlassPanel, LoadingSkeleton, MetricCard, SectionHeader, StatusBadge, TechnicalId } from '../components/primitives'
import { formatDateTime, machineIdentity } from '../utils/machineFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

function isMaintenance(sourceType: string, eventType: string) {
  const source = sourceType.toUpperCase()
  const event = eventType.toUpperCase()
  return source.includes('MAINTENANCE') || event.includes('REPAIR') || event.includes('REPLACEMENT')
}

function timestampValue(value: string) {
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed
}

export function ComponentDetailPage() {
  const { componentId = '' } = useParams()
  const component = useComponent(componentId)
  const machine = useCurrentMachine()
  const machineId = machine.data?.id ?? ''
  const timeline = useComponentTimeline(machineId, componentId)
  const incidents = useAllMachineIncidents(machineId, Boolean(machineId))

  const incidentItems = incidents.data ?? []
  const foreignIncident = incidentItems.find((incident) => machineId && incident.machine_id !== machineId)
  const evidenceQueries = useQueries({
    queries: incidentItems.map((incident) => ({
      queryKey: incidentKeys.evidence(incident.id),
      queryFn: () => getIncidentEvidence(incident.id),
      enabled: machineId.length > 0 && componentId.length > 0,
    })),
  })

  const linkedIncidents = useMemo(() => incidentItems.filter((_incident, index) => {
    return (evidenceQueries[index]?.data ?? []).some((evidence) => evidence.is_active && evidence.component_id === componentId)
  }), [componentId, evidenceQueries, incidentItems])

  const verificationQueries = useQueries({
    queries: linkedIncidents.map((incident) => ({
      queryKey: incidentKeys.verifications(incident.id),
      queryFn: () => getIncidentVerifications(incident.id),
      enabled: machineId.length > 0 && componentId.length > 0,
    })),
  })

  const maintenance = useMemo(() => {
    return (timeline.data ?? [])
      .filter((event) => isMaintenance(event.source_type, event.canonical_event_type))
      .slice()
      .sort((a, b) => timestampValue(a.original_timestamp) - timestampValue(b.original_timestamp))
  }, [timeline.data])
  const lastRepair = maintenance.length > 0 ? maintenance[maintenance.length - 1] : null

  const associationLoading = incidents.isPending || evidenceQueries.some((query) => query.isPending)
  const associationError = incidents.isError || evidenceQueries.some((query) => query.isError)
  const recurrenceCount = associationError ? undefined : linkedIncidents.filter((incident) => incident.status === 'RECURRED').length
  const verificationError = verificationQueries.some((query) => query.isError)
  const verificationRows = linkedIncidents.flatMap((incident, index) => {
    return (verificationQueries[index]?.data ?? []).map((run) => ({ incident, run }))
  })

  if (component.isError && component.error instanceof ApiError && component.error.status === 404) {
    return <ErrorState title="Component not found" description="The backend returned 404 for this component identifier." />
  }
  if (component.isError) return <ErrorState title="Component unavailable" description="The component identity could not be loaded from the backend." />
  if (machine.isError) return <ErrorState title="Configured machine unavailable" description="The local machine identity could not be loaded." />
  if (component.data && machine.data && component.data.machine_id !== machine.data.id) {
    return <ErrorState title="Component is not part of This Machine" description="The requested component belongs to a different machine, so the local node will not switch machine context." />
  }
  if (foreignIncident) {
    return <ErrorState title="Machine-scope violation" description="The backend returned an incident for another machine while resolving this component. The local UI will not display that foreign incident." />
  }

  return (
    <div>
      <PageIntro
        eyebrow="Component exact history"
        title={component.data?.display_name ?? component.data?.component_type ?? 'Component'}
        description={machine.data ? `Canonical component context for ${machineIdentity(machine.data)}.` : 'Canonical component context for the configured local machine.'}
      >
        {component.data ? <div className="detail-id-row"><span className="detail-id-row__label">Component ID</span><TechnicalId value={component.data.id} /></div> : null}
      </PageIntro>

      {component.isPending || machine.isPending ? (
        <GlassPanel className="page-panel"><LoadingSkeleton width="100%" height={160} label="Component detail loading" /></GlassPanel>
      ) : component.data ? (
        <>
          <section className="page-grid overview-metrics" aria-label="Canonical component counts">
            <MetricCard label="Evidence" value={timeline.isError ? undefined : (timeline.data?.length ?? 0)} icon={FileClock} loading={timeline.isPending} />
            <MetricCard label="Linked incidents" value={associationError ? undefined : linkedIncidents.length} icon={AlertTriangle} loading={associationLoading} />
            <MetricCard label="Maintenance / repair" value={timeline.isError ? undefined : maintenance.length} icon={Wrench} loading={timeline.isPending} />
            <MetricCard label="Recurrence" value={recurrenceCount} icon={History} loading={associationLoading} />
          </section>

          <GlassPanel className="page-panel">
            <SectionHeader title="Component identity" description="Backend identity metadata only; no frontend status color is invented." />
            <div className="handover-summary-grid">
              <div className="handover-summary-block"><span>Type</span><strong>{component.data.component_type ?? 'Not provided'}</strong></div>
              <div className="handover-summary-block"><span>Manufacturer</span><strong>{component.data.manufacturer ?? 'Not provided'}</strong></div>
              <div className="handover-summary-block"><span>Model</span><strong>{component.data.model ?? 'Not provided'}</strong></div>
              <div className="handover-summary-block"><span>Last repair evidence</span><strong>{lastRepair ? (formatDateTime(lastRepair.original_timestamp) ?? lastRepair.original_timestamp) : 'None derivable from maintenance evidence'}</strong></div>
            </div>
          </GlassPanel>

          <GlassPanel className="page-panel">
            <SectionHeader title="Exact evidence timeline" description="Canonical SQLite history for this component. This section is not semantic similarity." />
            {timeline.isPending ? <LoadingSkeleton width="100%" height={180} label="Component timeline loading" /> : timeline.isError ? <ErrorState title="Timeline unavailable" description="Exact component evidence could not be loaded." /> : (timeline.data?.length ?? 0) === 0 ? <EmptyState title="No component evidence" description="No canonical evidence is currently linked to this component." /> : (
              <div className="overview-incident-list">
                {(timeline.data ?? []).map((event) => (
                  <article className="overview-incident-row" key={event.id}>
                    <div><StatusBadge tone="neutral">{event.source_type}</StatusBadge> <strong>{event.canonical_event_type}</strong></div>
                    <span>{formatDateTime(event.original_timestamp) ?? event.original_timestamp}</span>
                    <TechnicalId value={event.id} />
                  </article>
                ))}
              </div>
            )}
          </GlassPanel>

          <GlassPanel className="page-panel">
            <SectionHeader title="Maintenance and repair history" description="Derived only from canonical component evidence explicitly identified as maintenance, repair, or replacement." />
            {timeline.isPending ? <LoadingSkeleton width="100%" height={120} label="Maintenance history loading" /> : timeline.isError ? <ErrorState title="Maintenance history unavailable" description="Maintenance history cannot be derived while the exact component timeline is unavailable." /> : maintenance.length === 0 ? <EmptyState title="No maintenance or repair evidence" description="No canonical component evidence currently qualifies as maintenance, repair, or replacement." /> : (
              <div className="overview-incident-list">
                {maintenance.map((event) => (
                  <article className="overview-incident-row" key={event.id}>
                    <div><Wrench size={15} aria-hidden="true" /> <strong>{event.canonical_event_type}</strong></div>
                    <span>{formatDateTime(event.original_timestamp) ?? event.original_timestamp}</span>
                    <StatusBadge tone="neutral">{event.source_type}</StatusBadge>
                    <TechnicalId value={event.id} />
                  </article>
                ))}
              </div>
            )}
          </GlassPanel>

          <GlassPanel className="page-panel">
            <SectionHeader title="Linked incidents and recurrence" description="An incident is included only when its active canonical evidence association references this component. All incident pages for This Machine are traversed before counts are shown." />
            {associationLoading ? <LoadingSkeleton width="100%" height={140} label="Linked incidents loading" /> : associationError ? <ErrorState title="Linked incidents unavailable" description="Incident or evidence-association retrieval failed, so the UI will not show a partial count as authoritative." /> : linkedIncidents.length === 0 ? <EmptyState title="No linked incidents" description="No active incident evidence association currently references this component." /> : (
              <div className="overview-incident-list">
                {linkedIncidents.map((incident) => <article className="overview-incident-row" key={incident.id}><StatusBadge tone={incident.status === 'RECURRED' ? 'danger' : incident.status === 'VERIFIED' ? 'success' : 'warning'}>{incident.status}</StatusBadge><TechnicalId value={incident.id} /><Link to={`/incidents/${encodeURIComponent(incident.id)}`}>Open incident</Link></article>)}
              </div>
            )}
          </GlassPanel>

          <GlassPanel className="page-panel">
            <SectionHeader title="Verification state" description="Persisted verification runs for incidents linked to this component." />
            {associationLoading || verificationQueries.some((query) => query.isPending) ? <LoadingSkeleton width="100%" height={120} label="Verification loading" /> : associationError || verificationError ? <ErrorState title="Verification state unavailable" description="The UI will not infer verification state when canonical incident or verification reads fail." /> : verificationRows.length === 0 ? <EmptyState title="No verification runs" description="No persisted verification run is associated with the linked incidents." /> : (
              <div className="overview-incident-list">
                {verificationRows.map(({ incident, run }) => <article className="overview-incident-row" key={run.id}><div><CheckCircle2 size={15} aria-hidden="true" /> <strong>{run.result ?? 'PENDING'}</strong></div><span>Incident {incident.id}</span><span>{formatDateTime(run.started_at) ?? run.started_at}</span><TechnicalId value={run.id} /></article>)}
              </div>
            )}
          </GlassPanel>
        </>
      ) : null}
    </div>
  )
}
