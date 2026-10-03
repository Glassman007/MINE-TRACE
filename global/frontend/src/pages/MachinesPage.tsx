import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ChevronLeft, ChevronRight, FilterX, Search, Truck } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMachines, type MachineSummary } from '../api/machines'
import { EmptyState, ErrorState, GlassPanel, LoadingSkeleton, SectionHeader, TechnicalId } from '../components/primitives'
import { artworkForMachineType } from '../presentation/machineArtwork'
import { machineIdentity, machineProduct, machineSite } from '../utils/machineFormatting'
import { PageIntro } from './PageIntro'

const PAGE_SIZE = 12

function parseOffset(value: string | null) {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : 0
}

function MachineArtwork({ machine }: { machine: MachineSummary }) {
  const artwork = artworkForMachineType(machine.machine_type)
  if (!artwork) {
    return (
      <div className="machine-card__artwork machine-card__artwork--generic" aria-hidden="true">
        <Truck size={42} strokeWidth={1.35} />
      </div>
    )
  }

  return (
    <div className="machine-card__artwork" aria-hidden="true">
      <img src={artwork.src} alt="" />
    </div>
  )
}

function MachineCard({ machine }: { machine: MachineSummary }) {
  const product = machineProduct(machine)
  const site = machineSite(machine)

  return (
    <Link to={`/machines/${encodeURIComponent(machine.id)}`} className="machine-card">
      <MachineArtwork machine={machine} />
      <div className="machine-card__body">
        <div className="machine-card__topline">
          <span className="machine-card__type">{machine.machine_type ?? 'Machine type not provided'}</span>
          {machine.asset_code ? <span className="machine-card__asset">{machine.asset_code}</span> : null}
        </div>
        <h2 className="machine-card__name">{machineIdentity(machine)}</h2>
        <dl className="machine-card__facts">
          <div>
            <dt>Make / model</dt>
            <dd>{product ?? 'Not provided'}</dd>
          </div>
          <div>
            <dt>Site</dt>
            <dd>{site ?? 'Not provided'}</dd>
          </div>
          <div>
            <dt>Last sync</dt>
            <dd>{machine.latest_sync_received_at ? new Date(machine.latest_sync_received_at).toLocaleString() : 'No receipt'}</dd>
          </div>
        </dl>
        <TechnicalId value={machine.id} />
      </div>
    </Link>
  )
}

export function MachinesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const offset = parseOffset(searchParams.get('offset'))
  const search = searchParams.get('search') ?? ''
  const siteName = searchParams.get('site') ?? ''
  const machineType = searchParams.get('machine_type') ?? ''
  const model = searchParams.get('model') ?? ''

  const [draftSearch, setDraftSearch] = useState(search)
  const [draftSite, setDraftSite] = useState(siteName)
  const [draftType, setDraftType] = useState(machineType)
  const [draftModel, setDraftModel] = useState(model)

  useEffect(() => {
    setDraftSearch(search)
    setDraftSite(siteName)
    setDraftType(machineType)
    setDraftModel(model)
  }, [search, siteName, machineType, model])

  const machines = useMachines({
    offset,
    limit: PAGE_SIZE,
    search: search || undefined,
    site: siteName || undefined,
    machine_type: machineType || undefined,
    model: model || undefined,
  })

  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const next = new URLSearchParams()
    if (draftSearch.trim()) next.set('search', draftSearch.trim())
    if (draftSite.trim()) next.set('site', draftSite.trim())
    if (draftType.trim()) next.set('machine_type', draftType.trim())
    if (draftModel.trim()) next.set('model', draftModel.trim())
    setSearchParams(next)
  }

  const clearFilters = () => {
    setDraftSearch('')
    setDraftSite('')
    setDraftType('')
    setDraftModel('')
    setSearchParams(new URLSearchParams())
  }

  const total = machines.data?.total ?? 0
  const returnedLimit = machines.data?.limit ?? PAGE_SIZE
  const currentOffset = machines.data?.offset ?? offset
  const page = Math.floor(currentOffset / Math.max(returnedLimit, 1)) + 1
  const totalPages = total === 0 ? 1 : Math.ceil(total / Math.max(returnedLimit, 1))
  const canPrevious = currentOffset > 0
  const canNext = currentOffset + returnedLimit < total

  const movePage = (nextOffset: number) => {
    const next = new URLSearchParams(searchParams)
    if (nextOffset > 0) next.set('offset', String(nextOffset))
    else next.delete('offset')
    setSearchParams(next)
  }

  return (
    <div className="machines-page">
      <PageIntro
        eyebrow="Asset registry"
        title="Machines"
        description="Browse the backend machine collection with server-side search, site, type, model and pagination filters."
      />

      <GlassPanel className="machine-filter-panel">
        <form className="machine-filters" onSubmit={applyFilters}>
          <label className="filter-field filter-field--search">
            <span>Search</span>
            <div className="filter-control">
              <Search size={16} aria-hidden="true" />
              <input value={draftSearch} onChange={(event) => setDraftSearch(event.target.value)} placeholder="Name, asset code, metadata…" />
            </div>
          </label>
          <label className="filter-field">
            <span>Machine type</span>
            <input value={draftType} onChange={(event) => setDraftType(event.target.value)} placeholder="Exact backend type" />
          </label>
          <label className="filter-field">
            <span>Model</span>
            <input value={draftModel} onChange={(event) => setDraftModel(event.target.value)} placeholder="Exact model" />
          </label>
          <label className="filter-field">
            <span>Site</span>
            <input value={draftSite} onChange={(event) => setDraftSite(event.target.value)} placeholder="Site name" />
          </label>
          <div className="machine-filters__actions">
            <button className="button button--primary" type="submit">Apply filters</button>
            <button className="button" type="button" onClick={clearFilters}><FilterX size={15} aria-hidden="true" />Clear</button>
          </div>
        </form>
      </GlassPanel>

      <GlassPanel className="page-panel machine-collection-panel">
        <SectionHeader
          title="Machine collection"
          description={machines.data ? `${machines.data.total} machine${machines.data.total === 1 ? '' : 's'} returned by the backend collection.` : 'Backend machine collection.'}
        />

        {machines.isPending ? (
          <div className="machine-card-grid" aria-label="Machines loading">
            {Array.from({ length: 6 }).map((_, index) => <LoadingSkeleton key={index} width="100%" height={255} label="Machine loading" />)}
          </div>
        ) : machines.isError ? (
          <ErrorState title="Machines unavailable" description="The machine collection could not be loaded from the backend." />
        ) : machines.data.items.length === 0 ? (
          <EmptyState title="No machines found" description="The backend returned no machines for the current filter combination." />
        ) : (
          <div className="machine-card-grid">
            {machines.data.items.map((machine) => <MachineCard key={machine.id} machine={machine} />)}
          </div>
        )}

        {!machines.isPending && !machines.isError ? (
          <nav className="machine-pagination" aria-label="Machine collection pagination">
            <span className="machine-pagination__summary">Page {page} of {totalPages}</span>
            <div className="machine-pagination__actions">
              <button className="button" type="button" disabled={!canPrevious} onClick={() => movePage(Math.max(0, currentOffset - returnedLimit))}>
                <ChevronLeft size={15} aria-hidden="true" /> Previous
              </button>
              <button className="button" type="button" disabled={!canNext} onClick={() => movePage(currentOffset + returnedLimit)}>
                Next <ChevronRight size={15} aria-hidden="true" />
              </button>
            </div>
          </nav>
        ) : null}
      </GlassPanel>
    </div>
  )
}
