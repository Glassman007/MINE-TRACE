import { type FormEvent, useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, Filter, RotateCcw } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { useCurrentMachine, type MachineSummary } from '../api/machines'
import { useIncidents, type IncidentCollectionParams, type IncidentSummary } from '../api/incidents'
import {
  EmptyState,
  ErrorState,
  GlassPanel,
  LoadingSkeleton,
  SectionHeader,
  StatusBadge,
  TechnicalId,
} from '../components/primitives'
import { formatDateTime, machineIdentity } from '../utils/machineFormatting'
import { severityTone, statusTone } from '../utils/incidentFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

const DEFAULT_LIMIT = 25
const LIMIT_OPTIONS = [10, 25, 50]
const knownStatuses = ['OPEN', 'VERIFYING', 'VERIFIED', 'RECURRED']
const knownDueStates = ['NOT_SET', 'ON_TRACK', 'DUE_SOON', 'OVERDUE']

interface FilterDraft {
  status: string
  severity: string
  owner_ref: string
  due_state: string
  limit: string
}

function numberParam(value: string | null, fallback: number) {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : fallback
}

function readDraft(search: URLSearchParams): FilterDraft {
  return {
    status: search.get('status') ?? '',
    severity: search.get('severity') ?? '',
    owner_ref: search.get('owner_ref') ?? '',
    due_state: search.get('due_state') ?? '',
    limit: String(numberParam(search.get('limit'), DEFAULT_LIMIT)),
  }
}

function IncidentRow({ incident, machine }: { incident: IncidentSummary; machine: MachineSummary }) {
  const created = formatDateTime(incident.created_at)
  const updated = formatDateTime(incident.updated_at)
  const due = formatDateTime(incident.due_time)

  return (
    <Link className="incident-collection-row" to={`/incidents/${encodeURIComponent(incident.id)}`}>
      <div className="incident-collection-row__state">
        <StatusBadge tone={statusTone(incident.status)}>{incident.status}</StatusBadge>
        {incident.severity ? <StatusBadge tone={severityTone(incident.severity)}>{incident.severity}</StatusBadge> : null}
      </div>

      <div className="incident-collection-row__machine">
        <strong>{machineIdentity(machine)}</strong>
        <div className="incident-collection-row__technical">
          <span>Machine</span><TechnicalId value={incident.machine_id} />
        </div>
      </div>

      <dl className="incident-collection-row__facts">
        <div><dt>Owner</dt><dd>{incident.owner_ref ?? 'Not set'}</dd></div>
        <div><dt>Due state</dt><dd>{incident.due_state ?? 'Not set'}</dd></div>
        <div><dt>Due time</dt><dd>{due ?? 'Not set'}</dd></div>
        <div><dt>Created</dt><dd>{created ?? 'Not returned'}</dd></div>
        <div><dt>Updated</dt><dd>{updated ?? incident.updated_at}</dd></div>
      </dl>

      <div className="incident-collection-row__id">
        <span>Incident</span>
        <TechnicalId value={incident.id} />
      </div>
    </Link>
  )
}

export function IncidentsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const machine = useCurrentMachine()
  const offset = numberParam(searchParams.get('offset'), 0)
  const limit = numberParam(searchParams.get('limit'), DEFAULT_LIMIT) || DEFAULT_LIMIT
  const params: IncidentCollectionParams = {
    offset,
    limit,
    machine_id: machine.data?.id,
    status: searchParams.get('status') || undefined,
    severity: searchParams.get('severity') || undefined,
    owner_ref: searchParams.get('owner_ref') || undefined,
    due_state: searchParams.get('due_state') || undefined,
  }

  const [draft, setDraft] = useState<FilterDraft>(() => readDraft(searchParams))
  useEffect(() => setDraft(readDraft(searchParams)), [searchParams])

  const incidents = useIncidents(params, Boolean(machine.data?.id))
  const foreignIncident = incidents.data?.items.find((incident) => machine.data && incident.machine_id !== machine.data.id)

  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const next = new URLSearchParams()
    next.set('offset', '0')
    next.set('limit', draft.limit || String(DEFAULT_LIMIT))
    ;(['status', 'severity', 'owner_ref', 'due_state'] as const).forEach((key) => {
      const value = draft[key].trim()
      if (value) next.set(key, value)
    })
    setSearchParams(next)
  }

  const resetFilters = () => setSearchParams(new URLSearchParams({ offset: '0', limit: String(DEFAULT_LIMIT) }))
  const pageStart = incidents.data && incidents.data.total > 0 ? incidents.data.offset + 1 : 0
  const pageEnd = incidents.data ? Math.min(incidents.data.offset + incidents.data.items.length, incidents.data.total) : 0
  const canPrevious = offset > 0
  const canNext = incidents.data ? offset + incidents.data.items.length < incidents.data.total : false

  const setOffset = (nextOffset: number) => {
    const next = new URLSearchParams(searchParams)
    next.set('offset', String(Math.max(0, nextOffset)))
    setSearchParams(next)
  }

  return (
    <div className="incidents-page">
      <PageIntro
        eyebrow="This Machine"
        title="Incidents"
        description="Authoritative incidents for the backend-configured local machine. Machine context cannot be selected in the browser."
      />

      {machine.isError ? <ErrorState title="Configured machine unavailable" description="Incident browsing is disabled until the local machine identity is available." /> : null}
      {machine.data ? (
        <GlassPanel className="page-panel">
          <SectionHeader title={machineIdentity(machine.data)} description="Configured machine scope" />
          <TechnicalId value={machine.data.id} />
        </GlassPanel>
      ) : null}

      <GlassPanel className="incident-filter-panel">
        <form className="incident-filters" onSubmit={applyFilters}>
          <label className="filter-field">
            <span>Status</span>
            <input list="incident-status-values" value={draft.status} onChange={(event) => setDraft((current) => ({ ...current, status: event.target.value }))} placeholder="Any status" />
            <datalist id="incident-status-values">{knownStatuses.map((value) => <option value={value} key={value} />)}</datalist>
          </label>
          <label className="filter-field">
            <span>Severity</span>
            <input value={draft.severity} onChange={(event) => setDraft((current) => ({ ...current, severity: event.target.value }))} placeholder="Any severity" />
          </label>
          <label className="filter-field">
            <span>Owner</span>
            <input value={draft.owner_ref} onChange={(event) => setDraft((current) => ({ ...current, owner_ref: event.target.value }))} placeholder="Any owner_ref" />
          </label>
          <label className="filter-field">
            <span>Due state</span>
            <input list="incident-due-values" value={draft.due_state} onChange={(event) => setDraft((current) => ({ ...current, due_state: event.target.value }))} placeholder="Any due state" />
            <datalist id="incident-due-values">{knownDueStates.map((value) => <option value={value} key={value} />)}</datalist>
          </label>
          <label className="filter-field">
            <span>Rows</span>
            <select className="filter-control incident-limit-select" value={draft.limit} onChange={(event) => setDraft((current) => ({ ...current, limit: event.target.value }))}>
              {LIMIT_OPTIONS.map((value) => <option value={value} key={value}>{value}</option>)}
            </select>
          </label>
          <div className="incident-filters__actions">
            <button className="button button--primary" type="submit"><Filter size={15} aria-hidden="true" />Apply</button>
            <button className="button" type="button" onClick={resetFilters}><RotateCcw size={15} aria-hidden="true" />Reset</button>
          </div>
        </form>
      </GlassPanel>

      <GlassPanel className="page-panel incident-collection-panel">
        <SectionHeader title="Incident collection" description="Backend collection filtered to the configured local machine." />
        {machine.isPending || incidents.isPending ? (
          <div className="incident-collection-loading">
            {Array.from({ length: 6 }).map((_, index) => <LoadingSkeleton key={index} width="100%" height={112} label="Incidents loading" />)}
          </div>
        ) : foreignIncident ? (
          <ErrorState title="Machine-scope violation" description="The backend returned an incident for another machine. The local UI will not display or switch to that machine." />
        ) : incidents.isError ? (
          <ErrorState title="Incidents unavailable" description="The incident collection could not be loaded from the backend." />
        ) : incidents.data.items.length === 0 ? (
          <EmptyState title="No incidents found" description="The backend returned no incidents for this machine and filter set." />
        ) : machine.data ? (
          <div className="incident-collection-list">
            {incidents.data.items.map((incident) => <IncidentRow key={incident.id} incident={incident} machine={machine.data} />)}
          </div>
        ) : null}

        {!machine.isPending && !incidents.isPending && !incidents.isError && !foreignIncident ? (
          <div className="machine-pagination">
            <span className="machine-pagination__summary">Showing {pageStart}–{pageEnd} of {incidents.data?.total ?? 0}</span>
            <div className="machine-pagination__actions">
              <button className="button" type="button" disabled={!canPrevious} onClick={() => setOffset(offset - limit)}><ChevronLeft size={15} aria-hidden="true" />Previous</button>
              <button className="button" type="button" disabled={!canNext} onClick={() => setOffset(offset + limit)}>Next<ChevronRight size={15} aria-hidden="true" /></button>
            </div>
          </div>
        ) : null}
      </GlassPanel>
    </div>
  )
}
