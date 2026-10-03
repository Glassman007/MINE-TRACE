import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import {
  CalendarClock,
  ClipboardList,
  FileClock,
  HardHat,
  Info,
  Paperclip,
  Settings2,
  Truck,
  UserRound,
  Wrench,
} from 'lucide-react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import {
  useCurrentMachine,
  useCurrentMachineComponents,
  useMachineTimeline,
  type ComponentSummary,
  type ContextDimension,
  type EvidenceContextSnapshot,
  type MachineSummary,
  type TimelineEvent,
} from '../api/machines'
import { useIncidents } from '../api/incidents'
import {
  EmptyState,
  ErrorState,
  GlassPanel,
  LoadingSkeleton,
  SectionHeader,
  StatusBadge,
  TechnicalId,
} from '../components/primitives'
import { artworkForMachineType } from '../presentation/machineArtwork'
import {
  formatBytes,
  formatDateTime,
  isoToLocalInput,
  localInputToIso,
  machineIdentity,
  machineProduct,
  machineSite,
} from '../utils/machineFormatting'
import { PageIntro } from './PageIntro'

const INCIDENT_LIMIT = 50
const contextDimensions = ['shift', 'location', 'machine_operating_state', 'workload', 'environment'] as const

type StatusTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger'

function statusTone(status: string): StatusTone {
  switch (status) {
    case 'OPEN': return 'warning'
    case 'VERIFYING': return 'info'
    case 'VERIFIED': return 'success'
    case 'RECURRED': return 'danger'
    default: return 'neutral'
  }
}

function sourcePresentation(sourceType: string) {
  const normalized = sourceType.toUpperCase()
  if (normalized.includes('MAINTENANCE')) return { Icon: Wrench, label: 'Maintenance record', tone: 'warning' as const }
  if (normalized.includes('HUMAN') || normalized.includes('OBSERVATION')) return { Icon: UserRound, label: 'Human observation', tone: 'info' as const }
  if (normalized.includes('MACHINE') || normalized.includes('ECU')) return { Icon: Settings2, label: 'Machine event', tone: 'neutral' as const }
  return { Icon: FileClock, label: sourceType, tone: 'neutral' as const }
}

function prettyJson(value: unknown) {
  if (value === undefined) return 'Not provided'
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function payloadSummary(value: unknown) {
  if (value === null || value === undefined) return 'No canonical payload returned'
  if (typeof value === 'string') return value.length > 180 ? `${value.slice(0, 177)}…` : value
  try {
    const compact = JSON.stringify(value)
    return compact.length > 180 ? `${compact.slice(0, 177)}…` : compact
  } catch {
    return String(value)
  }
}

function contextSnapshots(event: TimelineEvent) {
  return event.context_snapshots
}

function rawPayload(event: TimelineEvent) {
  return event.raw_source_payload
}

function valueText(value: unknown) {
  if (value === null || value === undefined || value === '') return 'UNKNOWN'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  return prettyJson(value)
}

function qualityTone(quality: string): StatusTone {
  if (quality === 'KNOWN') return 'success'
  if (quality === 'STALE') return 'warning'
  return 'neutral'
}

function ContextDimensionView({ label, dimension }: { label: string; dimension: ContextDimension | undefined }) {
  const quality = dimension?.quality ?? 'UNKNOWN'
  return (
    <div className="context-dimension">
      <div className="context-dimension__header">
        <span>{label}</span>
        <StatusBadge tone={qualityTone(quality)}>{quality}</StatusBadge>
      </div>
      <strong>{valueText(dimension?.value)}</strong>
      <span className="context-dimension__freshness">Freshness: {dimension?.freshness_basis ?? 'Not provided'}</span>
    </div>
  )
}

function ContextSnapshotView({ snapshot, index }: { snapshot: EvidenceContextSnapshot; index: number }) {
  return (
    <section className="timeline-inspector__section">
      <h4>Evidence-time context{index > 0 ? ` · Snapshot ${index + 1}` : ''}</h4>
      <div className="context-grid">
        {contextDimensions.map((key) => (
          <ContextDimensionView key={key} label={key.replaceAll('_', ' ')} dimension={snapshot[key]} />
        ))}
      </div>
    </section>
  )
}

function EvidenceInspector({ event }: { event: TimelineEvent }) {
  const snapshots = contextSnapshots(event)
  const attachments = event.attachments ?? []

  return (
    <div className="timeline-inspector">
      <section className="timeline-inspector__section timeline-inspector__section--two">
        <div>
          <h4>Canonical payload</h4>
          <pre>{prettyJson(event.canonical_payload)}</pre>
        </div>
        <div>
          <h4>Raw source payload</h4>
          <pre>{prettyJson(rawPayload(event))}</pre>
        </div>
      </section>

      <section className="timeline-inspector__section">
        <h4>Provenance</h4>
        <pre>{prettyJson(event.provenance)}</pre>
      </section>

      {snapshots.length === 0 ? (
        <section className="timeline-inspector__section">
          <h4>Evidence-time context</h4>
          <p className="timeline-inspector__empty">No context snapshot was returned for this evidence event.</p>
        </section>
      ) : snapshots.map((snapshot, index) => <ContextSnapshotView key={index} snapshot={snapshot} index={index} />)}

      <section className="timeline-inspector__section">
        <h4>Attachment metadata</h4>
        {attachments.length === 0 ? (
          <p className="timeline-inspector__empty">No attachment metadata was returned.</p>
        ) : (
          <div className="attachment-list">
            {attachments.map((attachment) => (
              <dl className="attachment-metadata" key={attachment.id}>
                <div><dt>Type</dt><dd>{attachment.attachment_type}</dd></div>
                <div><dt>Storage reference</dt><dd className="technical-text">{attachment.storage_reference}</dd></div>
                <div><dt>MIME type</dt><dd>{attachment.mime_type}</dd></div>
                <div><dt>File size</dt><dd>{attachment.file_size === null ? 'Not provided' : formatBytes(attachment.file_size)}</dd></div>
                <div><dt>Checksum</dt><dd className="technical-text">{attachment.checksum}</dd></div>
                <div><dt>Created</dt><dd>{formatDateTime(attachment.created_at) ?? attachment.created_at}</dd></div>
              </dl>
            ))}
          </div>
        )}
        <p className="attachment-note"><Info size={14} aria-hidden="true" />Attachments are metadata references only. No binary upload, playback, transcription, or download capability is implied.</p>
      </section>
    </div>
  )
}

function TimelineItem({ event, component }: { event: TimelineEvent; component?: ComponentSummary }) {
  const source = sourcePresentation(event.source_type)
  const snapshots = contextSnapshots(event)
  const attachments = event.attachments ?? []

  return (
    <article className="evidence-timeline__item" id={`evidence-${event.id}`}>
      <div className="evidence-timeline__rail" aria-hidden="true">
        <span className="evidence-timeline__node"><source.Icon size={16} /></span>
      </div>
      <div className="evidence-event-card">
        <div className="evidence-event-card__header">
          <div>
            <div className="evidence-event-card__badges">
              <StatusBadge tone={source.tone}>{event.source_type}</StatusBadge>
              <span className="overview-meta-chip">{event.canonical_event_type}</span>
            </div>
            <h3>{component?.display_name ?? component?.component_type ?? (event.component_id ? 'Component' : 'Machine-level evidence')}</h3>
          </div>
          <div className="evidence-event-card__ids"><TechnicalId value={event.id} /><TechnicalId value={event.original_source_record_id} />{event.component_id ? <TechnicalId value={event.component_id} /> : null}</div>
        </div>

        <div className="evidence-event-card__time-grid">
          <div>
            <span>Occurred</span>
            <strong>{formatDateTime(event.original_timestamp) ?? event.original_timestamp}</strong>
          </div>
          <div>
            <span>Ingested</span>
            <strong>{formatDateTime(event.ingestion_timestamp) ?? event.ingestion_timestamp}</strong>
          </div>
        </div>

        <p className="evidence-event-card__summary">{payloadSummary(event.canonical_payload)}</p>

        <div className="evidence-event-card__signals">
          {event.component_id ? <span><Settings2 size={14} aria-hidden="true" />Component linked</span> : null}
          {snapshots.length > 0 ? <span><CalendarClock size={14} aria-hidden="true" />Context snapshot</span> : null}
          {attachments.length > 0 ? <span><Paperclip size={14} aria-hidden="true" />{attachments.length} attachment metadata</span> : null}
          <span><ClipboardList size={14} aria-hidden="true" />Provenance available</span>
        </div>

        <details className="evidence-event-card__details">
          <summary>Inspect evidence</summary>
          <EvidenceInspector event={event} />
        </details>
      </div>
    </article>
  )
}

function MachineArtwork({ machine }: { machine: MachineSummary }) {
  const artwork = artworkForMachineType(machine.machine_type)
  if (!artwork) {
    return <div className="machine-detail-hero__artwork machine-detail-hero__artwork--generic"><Truck size={76} strokeWidth={1.15} aria-hidden="true" /></div>
  }
  return <div className="machine-detail-hero__artwork"><img src={artwork.src} alt="" /></div>
}

export function MachineDetailPage() {
  const { machineId = '' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedComponent = searchParams.get('component_id') ?? ''
  const from = searchParams.get('from') ?? ''
  const to = searchParams.get('to') ?? ''

  const [draftFrom, setDraftFrom] = useState(() => isoToLocalInput(from))
  const [draftTo, setDraftTo] = useState(() => isoToLocalInput(to))
  const [dateError, setDateError] = useState<string | null>(null)

  useEffect(() => {
    setDraftFrom(isoToLocalInput(from))
    setDraftTo(isoToLocalInput(to))
  }, [from, to])

  const machine = useCurrentMachine()
  const components = useCurrentMachineComponents()
  const configuredMachineId = machine.data?.id ?? ''
  const timeline = useMachineTimeline(configuredMachineId, {
    component_id: selectedComponent || undefined,
    from: from || undefined,
    to: to || undefined,
  })
  const incidents = useIncidents({ machine_id: configuredMachineId || undefined, offset: 0, limit: INCIDENT_LIMIT }, configuredMachineId.length > 0)

  const componentMap = useMemo(
    () => new Map((components.data ?? []).map((component) => [component.id, component])),
    [components.data],
  )

  useEffect(() => {
    if (!timeline.data?.length || typeof window === 'undefined' || !window.location.hash) return
    const targetId = decodeURIComponent(window.location.hash.slice(1))
    if (!targetId.startsWith('evidence-')) return
    document.getElementById(targetId)?.scrollIntoView({ block: 'center' })
  }, [timeline.data])

  const selectComponent = (componentId: string) => {
    const next = new URLSearchParams(searchParams)
    if (componentId) next.set('component_id', componentId)
    else next.delete('component_id')
    setSearchParams(next)
  }

  const applyTimeRange = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const fromIso = localInputToIso(draftFrom)
    const toIso = localInputToIso(draftTo)
    if (fromIso && toIso && new Date(fromIso).getTime() > new Date(toIso).getTime()) {
      setDateError('From time must be earlier than or equal to To time.')
      return
    }
    setDateError(null)
    const next = new URLSearchParams(searchParams)
    if (fromIso) next.set('from', fromIso)
    else next.delete('from')
    if (toIso) next.set('to', toIso)
    else next.delete('to')
    setSearchParams(next)
  }

  const clearTimelineFilters = () => {
    setDraftFrom('')
    setDraftTo('')
    setDateError(null)
    const next = new URLSearchParams(searchParams)
    next.delete('component_id')
    next.delete('from')
    next.delete('to')
    setSearchParams(next)
  }

  if (machine.isError) {
    return <ErrorState title="Configured machine unavailable" description="The local machine identity could not be loaded from the backend." />
  }
  if (machine.data && machineId && machineId !== machine.data.id) {
    return <ErrorState title="Machine is not This Machine" description="The requested route identifies a different machine. The local node will not switch machine context." />
  }

  const machineData = machine.data
  const product = machineData ? machineProduct(machineData) : null
  const site = machineData ? machineSite(machineData) : null

  return (
    <div className="machine-detail-page">
      <PageIntro
        eyebrow="Asset memory"
        title={machineData ? machineIdentity(machineData) : 'Machine'}
        description="Exact machine evidence, components, and related incidents from the authoritative backend."
      >
        <div className="detail-id-row"><span className="detail-id-row__label">Machine ID</span><TechnicalId value={configuredMachineId || machineId} /></div>
      </PageIntro>

      <GlassPanel className="machine-detail-hero">
        {machine.isPending || !machineData ? (
          <div className="machine-detail-hero__loading">
            <LoadingSkeleton width="42%" height={160} label="Machine identity loading" />
            <LoadingSkeleton width="100%" height={160} label="Machine metadata loading" />
          </div>
        ) : (
          <>
            <MachineArtwork machine={machineData} />
            <div className="machine-detail-hero__identity">
              <span className="page-eyebrow">{machineData.machine_type ?? 'Machine type not provided'}</span>
              <h1>{machineIdentity(machineData)}</h1>
              {machineData.asset_code ? <span className="machine-detail-hero__asset">{machineData.asset_code}</span> : null}
              <dl>
                <div><dt>Manufacturer / model</dt><dd>{product ?? 'Not provided'}</dd></div>
                <div><dt>Site / area</dt><dd>{site ?? 'Not provided'}</dd></div>
              </dl>
            </div>
          </>
        )}
      </GlassPanel>

      <section className="machine-detail-section">
        <SectionHeader title="Components" description="Select a component to filter the exact machine timeline." />
        {components.isPending ? (
          <div className="component-grid">{Array.from({ length: 4 }).map((_, index) => <LoadingSkeleton key={index} width="100%" height={116} label="Components loading" />)}</div>
        ) : components.isError ? (
          <ErrorState title="Components unavailable" description="Components could not be loaded for this machine." />
        ) : (components.data?.length ?? 0) === 0 ? (
          <EmptyState title="No components" description="The backend returned no components for this machine." />
        ) : (
          <div className="component-grid">
            <button className={`component-card ${selectedComponent === '' ? 'component-card--selected' : ''}`} type="button" aria-pressed={selectedComponent === ''} onClick={() => selectComponent('')}>
              <HardHat size={19} aria-hidden="true" />
              <strong>All components</strong>
              <span>Show complete machine chronology</span>
            </button>
            {(components.data ?? []).map((component) => (
              <button
                className={`component-card ${selectedComponent === component.id ? 'component-card--selected' : ''}`}
                type="button"
                key={component.id}
                aria-pressed={selectedComponent === component.id}
                onClick={() => selectComponent(component.id)}
              >
                <Settings2 size={19} aria-hidden="true" />
                <strong>{component.display_name ?? component.component_type ?? 'Unnamed component'}</strong>
                <span>{[component.manufacturer, component.model].filter(Boolean).join(' · ') || 'Manufacturer / model not provided'}</span>
                <TechnicalId value={component.id} />
              </button>
            ))}
          </div>
        )}
      </section>

      <GlassPanel className="page-panel machine-timeline-panel">
        <SectionHeader
          title="Machine evidence timeline"
          description="Backend chronology ordered by original source time. Ingestion time is shown separately for traceability."
        />

        <form className="timeline-filters" onSubmit={applyTimeRange}>
          <label className="filter-field">
            <span>From · local time</span>
            <input type="datetime-local" value={draftFrom} onChange={(event) => setDraftFrom(event.target.value)} />
          </label>
          <label className="filter-field">
            <span>To · local time</span>
            <input type="datetime-local" value={draftTo} onChange={(event) => setDraftTo(event.target.value)} />
          </label>
          <div className="machine-filters__actions">
            <button className="button button--primary" type="submit">Apply time range</button>
            <button className="button" type="button" onClick={clearTimelineFilters}>Clear timeline filters</button>
          </div>
          {dateError ? <p className="timeline-filters__error" role="alert">{dateError}</p> : null}
        </form>

        {selectedComponent ? (
          <div className="timeline-active-filter">
            <span>Component filter</span>
            <strong>{componentMap.get(selectedComponent)?.display_name ?? componentMap.get(selectedComponent)?.component_type ?? selectedComponent}</strong>
          </div>
        ) : null}

        {timeline.isPending ? (
          <div className="timeline-loading">
            <LoadingSkeleton width="100%" height={150} label="Timeline loading" />
            <LoadingSkeleton width="100%" height={150} label="Timeline loading" />
            <LoadingSkeleton width="100%" height={150} label="Timeline loading" />
          </div>
        ) : timeline.isError ? (
          <ErrorState title="Timeline unavailable" description="The exact machine timeline could not be loaded with the current filters." />
        ) : (timeline.data?.length ?? 0) === 0 ? (
          <EmptyState title="No evidence in this range" description="The backend returned no timeline evidence for the selected machine and filters." />
        ) : (
          <div className="evidence-timeline">
            {(timeline.data ?? []).map((event) => <TimelineItem key={event.id} event={event} component={event.component_id ? componentMap.get(event.component_id) : undefined} />)}
          </div>
        )}
      </GlassPanel>

      <GlassPanel className="page-panel machine-incidents-panel">
        <SectionHeader title="Related incidents" description="Incidents filtered by this machine through the backend collection endpoint." />
        {incidents.isPending ? (
          <div className="related-incident-list"><LoadingSkeleton width="100%" height={84} label="Related incidents loading" /><LoadingSkeleton width="100%" height={84} label="Related incidents loading" /></div>
        ) : incidents.isError ? (
          <ErrorState title="Related incidents unavailable" description="Incidents for this machine could not be loaded." />
        ) : incidents.data.items.length === 0 ? (
          <EmptyState title="No related incidents" description="The backend returned no incidents associated with this machine." />
        ) : (
          <div className="related-incident-list">
            {incidents.data.items.map((incident) => (
              <Link className="related-incident" key={incident.id} to={`/incidents/${encodeURIComponent(incident.id)}`}>
                <div>
                  <StatusBadge tone={statusTone(incident.status)}>{incident.status}</StatusBadge>
                  <strong>{incident.severity ?? 'Severity not provided'}</strong>
                </div>
                <div className="related-incident__meta">
                  {incident.owner_ref ? <span>Owner · {incident.owner_ref}</span> : null}
                  {incident.due_state ? <span>Due · {incident.due_state}</span> : null}
                  <span>Updated · {formatDateTime(incident.updated_at) ?? incident.updated_at}</span>
                </div>
                <TechnicalId value={incident.id} />
              </Link>
            ))}
          </div>
        )}
      </GlassPanel>
    </div>
  )
}
