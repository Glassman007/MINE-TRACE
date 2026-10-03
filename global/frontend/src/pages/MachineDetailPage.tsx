import { Link, useParams } from 'react-router-dom'
import { useMachine, useMachineComponents, useMachineIncidents, useMachineSessions } from '../api/machines'
import { EmptyState, ErrorState, GlassPanel, LoadingSkeleton, SectionHeader, StatusBadge, TechnicalId } from '../components/primitives'
import { formatDateTime, machineIdentity, machineProduct, machineSite } from '../utils/machineFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

export function MachineDetailPage() {
  const machineId = useParams().machineId ?? ''
  const machine = useMachine(machineId)
  const components = useMachineComponents(machineId)
  const sessions = useMachineSessions(machineId, { limit: 25 })
  const incidents = useMachineIncidents(machineId, { limit: 25 })

  if (machine.isPending) return <LoadingSkeleton width="100%" height={320} label="Machine loading" />
  if (machine.isError || !machine.data) return <ErrorState title="Machine unavailable" description="The synchronized machine record could not be loaded." />

  return (
    <div className="machine-detail-page">
      <PageIntro eyebrow="Synchronized machine" title={machineIdentity(machine.data)} description="Central read-only view of identity, sessions, components and incidents." />
      <GlassPanel className="page-panel">
        <SectionHeader title="Machine identity" description="Canonical synchronized machine metadata." />
        <dl className="incident-overview-grid">
          <div><dt>ID</dt><dd><TechnicalId value={machine.data.id} /></dd></div>
          <div><dt>Product</dt><dd>{machineProduct(machine.data) ?? 'Not supplied'}</dd></div>
          <div><dt>Type</dt><dd>{machine.data.machine_type ?? 'Not supplied'}</dd></div>
          <div><dt>Site</dt><dd>{machineSite(machine.data) ?? 'Not supplied'}</dd></div>
          <div><dt>Last sync</dt><dd>{formatDateTime(machine.data.latest_sync_received_at) ?? 'No receipt'}</dd></div>
          <div><dt>Report revision</dt><dd>{machine.data.latest_report_revision ?? 'Not supplied'}</dd></div>
        </dl>
      </GlassPanel>
      <GlassPanel className="page-panel">
        <SectionHeader title="Components" description="Known synchronized components." />
        {components.isPending ? <LoadingSkeleton width="100%" height={120} /> : components.isError ? <ErrorState description="Components could not be loaded." /> : components.data.length === 0 ? <EmptyState title="No components" description="No components are synchronized for this machine." /> : (
          <div className="incident-list">{components.data.map((c) => <div key={c.id} className="incident-collection-row"><strong>{c.display_name ?? c.component_type ?? c.id}</strong><TechnicalId value={c.id} /></div>)}</div>
        )}
      </GlassPanel>
      <GlassPanel className="page-panel">
        <SectionHeader title="Sessions" description="Newest synchronized operating sessions first." />
        {sessions.data?.items.map((s) => <div key={s.session_id} className="incident-collection-row"><StatusBadge>{s.state}</StatusBadge><div>{formatDateTime(s.started_at)} → {formatDateTime(s.ended_at) ?? 'Open'}</div><span>Revision {s.latest_report_revision}</span></div>)}
      </GlassPanel>
      <GlassPanel className="page-panel">
        <SectionHeader title="Incidents" description="Synchronized incident records for this machine." />
        {incidents.data?.items.map((i) => <Link key={i.incident_id} to={`/incidents/${encodeURIComponent(i.incident_id)}`} className="incident-collection-row"><StatusBadge>{i.status}</StatusBadge><TechnicalId value={i.incident_id} /><span>{formatDateTime(i.last_seen_at) ?? 'No last-seen time'}</span></Link>)}
      </GlassPanel>
    </div>
  )
}
