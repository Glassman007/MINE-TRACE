import { Clock3, Database, Layers3, Link2, ShieldAlert, Wrench } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useOverview } from '../api/overview'
import {
  EmptyState,
  ErrorState,
  GlassPanel,
  LoadingSkeleton,
  MetricCard,
  SectionHeader,
  StatusBadge,
  TechnicalId,
} from '../components/primitives'
import { formatDateTime, machineIdentity, machineProduct, machineSite } from '../utils/machineFormatting'
import './pages.css'

type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger'

function returnTone(state: string): Tone {
  if (state === 'CLEARED') return 'success'
  if (state === 'VERIFICATION_REQUIRED') return 'warning'
  if (state === 'DO_NOT_RETURN') return 'danger'
  return 'neutral'
}

function transportLabel(configured: boolean, available: boolean | null | undefined) {
  if (!configured) return 'Not configured'
  if (available === true) return 'Measured reachable'
  if (available === false) return 'Measured unavailable'
  return 'Not yet measured'
}

export function OverviewPage() {
  const overview = useOverview()

  if (overview.isPending) {
    return (
      <div className="overview-page">
        <header className="overview-command-header">
          <p className="page-eyebrow">Local node</p>
          <h1 className="overview-command-header__brand">This Machine</h1>
        </header>
        <GlassPanel className="page-panel"><LoadingSkeleton width="100%" height={220} label="Local machine overview loading" /></GlassPanel>
      </div>
    )
  }

  if (overview.isError) {
    return <ErrorState title="This Machine unavailable" description="The configured-machine overview could not be loaded from the local backend." />
  }

  const data = overview.data
  const machine = data.machine
  const activeSession = data.active_session
  const sync = data.sync
  const clearance = data.return_to_service

  return (
    <div className="overview-page">
      <header className="overview-command-header">
        <p className="page-eyebrow">Local node</p>
        <h1 className="overview-command-header__brand">This Machine</h1>
        <p className="overview-command-header__subtitle">Canonical local state for {machineIdentity(machine)}</p>
        {data.demo_mode ? <StatusBadge tone="info">Demo mode</StatusBadge> : null}
      </header>

      <GlassPanel className="page-panel">
        <SectionHeader title={machineIdentity(machine)} description={[machineProduct(machine), machineSite(machine)].filter(Boolean).join(' · ') || 'Configured local machine'} />
        <div className="detail-id-row"><span className="detail-id-row__label">Machine ID</span><TechnicalId value={machine.id} /></div>
        <div className="overview-lifecycle">
          <div className="overview-lifecycle__state"><span>Operating state</span><strong>{data.operating_state ?? 'No active session'}</strong></div>
          <div className="overview-lifecycle__state"><span>Return to service</span><StatusBadge tone={returnTone(clearance.state)}>{clearance.state}</StatusBadge></div>
          <div className="overview-lifecycle__state"><span>Sync transport</span><strong>{transportLabel(sync.transport_configured, sync.transport_available)}</strong></div>
        </div>
      </GlassPanel>

      <section className="page-grid overview-metrics" aria-label="Authoritative local counts">
        <MetricCard label="Components" value={data.counts.components} icon={Layers3} />
        <MetricCard label="Evidence" value={data.counts.evidence} icon={Database} />
        <MetricCard label="Incidents" value={data.counts.incidents} icon={ShieldAlert} />
        <MetricCard label="Unresolved" value={data.unresolved_incident_count} icon={Wrench} />
      </section>

      <section className="overview-primary-grid">
        <GlassPanel className="page-panel">
          <SectionHeader title="Active session" description="Persisted operating-session state from SQLite." />
          {activeSession ? (
            <div className="handover-summary-grid">
              <div className="handover-summary-block"><span>Session</span><TechnicalId value={activeSession.session_id} /></div>
              <div className="handover-summary-block"><span>Started</span><strong>{formatDateTime(activeSession.started_at) ?? activeSession.started_at}</strong></div>
              <div className="handover-summary-block"><span>State</span><strong>{activeSession.state}</strong></div>
              {activeSession.operating_hours !== null && activeSession.operating_hours !== undefined ? (
                <div className="handover-summary-block"><span>Authoritative operating hours</span><strong>{activeSession.operating_hours}</strong></div>
              ) : null}
            </div>
          ) : <EmptyState title="No active session" description="The backend did not report an open operating session." />}
        </GlassPanel>

        <GlassPanel className="page-panel">
          <SectionHeader title="Return-to-service" description={`${clearance.policy_identifier} · revision ${clearance.policy_revision}`} />
          <StatusBadge tone={returnTone(clearance.state)}>{clearance.state}</StatusBadge>
          {clearance.blocking_reasons.length > 0 ? (
            <div className="overview-incident-list">
              {clearance.blocking_reasons.map((reason, index) => (
                <article className="overview-incident-row" key={`${reason.code}-${index}`}>
                  <strong>{reason.code}</strong>
                  <span>{reason.message}</span>
                  {reason.incident_id ? <Link to={`/incidents/${encodeURIComponent(reason.incident_id)}`}><Link2 size={14} aria-hidden="true" /> Open incident</Link> : null}
                </article>
              ))}
            </div>
          ) : <EmptyState title="No blocking reasons" description="The backend policy returned no blocking reason for the current state." />}
        </GlassPanel>
      </section>

      <GlassPanel className="page-panel">
        <SectionHeader title="Synchronization transport" description="Connectivity is shown only when the backend has actually measured it." />
        <div className="handover-summary-grid">
          <div className="handover-summary-block"><span>Configuration</span><strong>{sync.transport_configured ? 'Configured' : 'Not configured'}</strong></div>
          <div className="handover-summary-block"><span>Measured state</span><strong>{transportLabel(sync.transport_configured, sync.transport_available)}</strong></div>
          <div className="handover-summary-block"><span>Latest package state</span><strong>{sync.latest_package_state ?? 'No package state'}</strong></div>
          <div className="handover-summary-block"><span>Last check</span><strong>{sync.transport_checked_at ? (formatDateTime(sync.transport_checked_at) ?? sync.transport_checked_at) : 'Not measured'}</strong></div>
          <div className="handover-summary-block"><span>Last acknowledgement</span><strong>{sync.last_acknowledgement ? (formatDateTime(sync.last_acknowledgement) ?? sync.last_acknowledgement) : 'None recorded'}</strong></div>
        </div>
        {sync.last_error ? <p className="attachment-note"><Clock3 size={14} aria-hidden="true" />Last transport error: {sync.last_error}</p> : null}
      </GlassPanel>
    </div>
  )
}
