import { Wrench } from 'lucide-react'
import { useCurrentMachine, useMachineTimeline } from '../api/machines'
import { EmptyState, ErrorState, GlassPanel, LoadingSkeleton, SectionHeader, TechnicalId } from '../components/primitives'
import { formatDateTime } from '../utils/machineFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

function payloadSummary(payload: Record<string, unknown>) {
  const action = payload.action
  if (typeof action === 'string' && action.trim()) return action
  return JSON.stringify(payload)
}

export function HistoryPage() {
  const machine = useCurrentMachine()
  const timeline = useMachineTimeline(machine.data?.id ?? '', {}, Boolean(machine.data?.id))
  const maintenance = (timeline.data ?? []).filter((event) => event.source_type.toUpperCase().includes('MAINTENANCE'))

  return <div>
    <PageIntro eyebrow="Canonical history" title="History" description="Maintenance history comes from canonical SQLite evidence. Semantic matches are intentionally excluded from this exact-history view." />
    <GlassPanel className="page-panel">
      <SectionHeader title="Maintenance actions" description="Recorded maintenance evidence for the configured machine." />
      {machine.isPending || timeline.isPending ? <LoadingSkeleton width="100%" height={180} label="History loading" />
        : machine.isError || timeline.isError ? <ErrorState title="History unavailable" description="The local backend could not provide the configured machine timeline." />
        : maintenance.length === 0 ? <EmptyState title="No maintenance evidence" description="No canonical maintenance records are currently stored for this machine." />
        : <div className="record-list">{maintenance.map((event) => <article className="record-row" key={event.id}>
            <span className="record-row__icon"><Wrench size={18} aria-hidden="true" /></span>
            <div className="record-row__body">
              <strong>{event.canonical_event_type}</strong>
              <span>{payloadSummary(event.canonical_payload as Record<string, unknown>)}</span>
              <small>{formatDateTime(event.original_timestamp) ?? event.original_timestamp} · {event.source_type}</small>
              <TechnicalId value={event.id} />
            </div>
          </article>)}</div>}
    </GlassPanel>
  </div>
}
