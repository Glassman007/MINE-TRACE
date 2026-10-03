import { useMemo, useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, LoaderCircle, UserRoundCheck } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { useAcknowledgeHandover, useHandover, type HandoverItem } from '../api/handover'
import { ApiError } from '../api/http'
import { getIncident, incidentKeys, type IncidentDetail } from '../api/incidents'
import { useCurrentMachine, type MachineSummary } from '../api/machines'
import {
  ConfirmDialog,
  EmptyState,
  ErrorState,
  GlassPanel,
  LoadingSkeleton,
  SectionHeader,
  StatusBadge,
  TechnicalId,
} from '../components/primitives'
import { severityTone, statusTone } from '../utils/incidentFormatting'
import { formatDateTime, machineIdentity, shortId } from '../utils/machineFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

function packetError(error: unknown) {
  if (error instanceof ApiError) {
    return error.code ? `${error.code}: ${error.message}` : error.message
  }
  return 'The packet could not be loaded from the backend.'
}

function acknowledgementError(error: unknown) {
  if (!(error instanceof ApiError)) return null
  if (error.status === 409 && error.code === 'HANDOVER_ALREADY_ACKNOWLEDGED') {
    return {
      title: 'Already acknowledged',
      description: 'This persisted handover was acknowledged previously. Refreshing the packet preserves the backend state rather than applying a second acknowledgement.',
    }
  }
  if (error.status === 409) {
    return {
      title: 'Acknowledgement conflict',
      description: error.code ? `${error.code}: ${error.message}` : error.message,
    }
  }
  return { title: 'Acknowledgement failed', description: error.code ? `${error.code}: ${error.message}` : error.message }
}

function currentContextMap(incidents: Array<IncidentDetail | undefined>) {
  const map = new Map<string, IncidentDetail>()
  incidents.forEach((incident) => {
    if (incident) map.set(incident.id, incident)
  })
  return map
}

function HandoverIncidentCard({
  item,
  incident,
  machine,
}: {
  item: HandoverItem
  incident?: IncidentDetail
  machine?: MachineSummary
}) {
  const due = formatDateTime(item.due_time)
  const currentMachineId = incident?.machine_id ?? null
  const primaryLabel = machine ? machineIdentity(machine) : currentMachineId ? shortId(currentMachineId) : 'Machine context unavailable'

  return (
    <article className="handover-incident-card">
      <div className="handover-incident-card__header">
        <div className="handover-incident-card__badges">
          <StatusBadge tone={statusTone(item.status)}>{item.status}</StatusBadge>
          {item.severity ? <StatusBadge tone={severityTone(item.severity)}>{item.severity}</StatusBadge> : null}
        </div>
        <Link className="button button--compact" to={`/incidents/${encodeURIComponent(item.incident_id)}`}>Open incident</Link>
      </div>

      <div className="handover-incident-card__identity">
        <strong>{primaryLabel}</strong>
        <div><span>Incident</span><TechnicalId value={item.incident_id} /></div>
        {currentMachineId ? <div><span>Machine</span><TechnicalId value={currentMachineId} /></div> : null}
      </div>

      <dl className="handover-incident-card__facts">
        <div><dt>Owner</dt><dd>{item.owner_ref ?? 'Not set'}</dd></div>
        <div><dt>Due state</dt><dd>{item.due_state ?? 'Not set'}</dd></div>
        <div><dt>Due time</dt><dd>{due ?? 'Not set'}</dd></div>
      </dl>

      <div className="handover-snapshot-note">
        Packet values are a handover-time snapshot. Open the incident workspace for current authoritative incident state.
      </div>
    </article>
  )
}

export function HandoverDetailPage() {
  const { packetId = '' } = useParams()
  const packet = useHandover(packetId)
  const machine = useCurrentMachine()
  const acknowledge = useAcknowledgeHandover()
  const [confirmOpen, setConfirmOpen] = useState(false)

  const incidentIds = useMemo(() => [...new Set((packet.data?.items ?? []).map((item) => item.incident_id))], [packet.data?.items])
  const incidentQueries = useQueries({
    queries: incidentIds.map((incidentId) => ({
      queryKey: incidentKeys.detail(incidentId),
      queryFn: () => getIncident(incidentId),
      enabled: packet.isSuccess,
      staleTime: 15_000,
    })),
  })
  const incidents = incidentQueries.map((query) => query.data)
  const incidentMap = useMemo(() => currentContextMap(incidents), [incidents])
  const foreignIncident = incidents.find((incident) => incident && machine.data && incident.machine_id !== machine.data.id)


  const isNotFound = packet.isError && packet.error instanceof ApiError && packet.error.status === 404
  const ackConflict = acknowledge.isError ? acknowledgementError(acknowledge.error) : null

  const confirmAcknowledge = () => {
    if (!packet.data) return
    setConfirmOpen(false)
    acknowledge.mutate({ packetId: packet.data.id, incidentIds: packet.data.items.map((item) => item.incident_id) })
  }

  if (isNotFound) {
    return <ErrorState title="Handover packet not found" description="The backend returned 404 for this handover packet identifier." />
  }

  if (packet.isError) {
    return <ErrorState title="Handover unavailable" description={packetError(packet.error)} />
  }

  if (machine.isError) {
    return <ErrorState title="Configured machine unavailable" description="The local node could not resolve its configured machine identity." />
  }
  if (foreignIncident) {
    return <ErrorState title="Handover contains another machine" description="A packet incident belongs to a different machine. The local node will not resolve or display that foreign machine context." />
  }

  return (
    <div className="handover-detail-page">
      <PageIntro
        eyebrow="Shift-transition briefing"
        title="Handover Packet"
        description="A persisted snapshot of unresolved incident continuity for shift transfer."
      >
        <div className="detail-id-row"><span className="detail-id-row__label">Packet ID</span><TechnicalId value={packetId} /></div>
      </PageIntro>

      {packet.isPending || !packet.data ? (
        <GlassPanel className="page-panel"><LoadingSkeleton width="100%" height={180} label="Handover packet loading" /></GlassPanel>
      ) : (
        <>
          <GlassPanel className="page-panel handover-summary-panel">
            <div className="handover-summary-grid">
              <div className="handover-summary-block">
                <span>Created</span>
                <strong>{formatDateTime(packet.data.created_at) ?? packet.data.created_at}</strong>
              </div>
              <div className="handover-summary-block">
                <span>Acknowledgement</span>
                <strong>{packet.data.acknowledged_at ? 'Acknowledged' : 'Pending receipt'}</strong>
                {packet.data.acknowledged_at ? <small>{formatDateTime(packet.data.acknowledged_at) ?? packet.data.acknowledged_at}</small> : null}
              </div>
              <div className="handover-summary-block">
                <span>Snapshot incidents</span>
                <strong>{packet.data.items.length}</strong>
              </div>
            </div>

            <div className="handover-ack-rule">
              <AlertTriangle size={17} aria-hidden="true" />
              <span>Acknowledging confirms receipt only. It does not resolve, verify, close, or change the status of any incident.</span>
            </div>

            {ackConflict ? (
              <div className="incident-action-message incident-action-message--conflict" role="alert">
                <AlertTriangle size={16} aria-hidden="true" />
                <div><strong>{ackConflict.title}</strong><span>{ackConflict.description}</span></div>
              </div>
            ) : null}

            {acknowledge.isSuccess ? (
              <div className="incident-action-message incident-action-message--success" role="status">
                <CheckCircle2 size={16} aria-hidden="true" />
                <div><strong>Handover acknowledged</strong><span>The packet is being refreshed from the backend to show the persisted acknowledgement time.</span></div>
              </div>
            ) : null}

            {!packet.data.acknowledged_at ? (
              <button className="button button--primary handover-primary-action" type="button" disabled={acknowledge.isPending} onClick={() => setConfirmOpen(true)}>
                {acknowledge.isPending ? <LoaderCircle className="spin" size={16} aria-hidden="true" /> : <UserRoundCheck size={16} aria-hidden="true" />}
                {acknowledge.isPending ? 'Acknowledging…' : 'Acknowledge handover'}
              </button>
            ) : (
              <div className="handover-acknowledged-banner"><CheckCircle2 size={17} aria-hidden="true" /><span>Acknowledged at {formatDateTime(packet.data.acknowledged_at) ?? packet.data.acknowledged_at}</span></div>
            )}
          </GlassPanel>

          <GlassPanel className="page-panel handover-items-panel">
            <SectionHeader
              title="Unresolved incident briefing"
              description="Membership and snapshot values come directly from the persisted handover packet returned by the backend."
            />
            {packet.data.items.length === 0 ? (
              <EmptyState title="No handover items" description="The backend created this packet without applicable unresolved incident snapshots." />
            ) : (
              <div className="handover-incident-list">
                {packet.data.items.map((item) => {
                  const incident = incidentMap.get(item.incident_id)
                  return <HandoverIncidentCard key={item.incident_id} item={item} incident={incident} machine={machine.data} />
                })}
              </div>
            )}
          </GlassPanel>
        </>
      )}

      <ConfirmDialog
        open={confirmOpen}
        title="Acknowledge this handover?"
        description="This records receipt of the shift briefing. It does not resolve, verify, close, or otherwise change any represented incident."
        confirmLabel="Acknowledge receipt"
        onCancel={() => setConfirmOpen(false)}
        onConfirm={confirmAcknowledge}
      />
    </div>
  )
}
