import { Boxes, ChevronRight, Truck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useComponents } from '../api/components'
import { useCurrentMachine } from '../api/machines'
import { useOverview } from '../api/overview'
import { ApiError } from '../api/http'
import { EmptyState, ErrorState, GlassPanel, LoadingSkeleton, SectionHeader, TechnicalId } from '../components/primitives'
import { artworkForMachineType } from '../presentation/machineArtwork'
import { demoComponentSchematic } from '../demo/demoScenario'
import { machineIdentity, machineProduct } from '../utils/machineFormatting'
import { PageIntro } from './PageIntro'
import './pages.css'

function errorDescription(error: unknown) {
  if (error instanceof ApiError) return error.code ? `${error.code}: ${error.message}` : error.message
  return 'The local backend could not provide component identity data.'
}

export function ComponentsPage() {
  const machine = useCurrentMachine()
  const components = useComponents()
  const overview = useOverview()

  if (machine.isError) return <ErrorState title="Configured machine unavailable" description={errorDescription(machine.error)} />

  const artwork = machine.data ? artworkForMachineType(machine.data.machine_type) : null
  const foreignComponent = (components.data ?? []).find((component) => machine.data && component.machine_id !== machine.data.id)
  const demoSchematicReady = Boolean(overview.data?.demo_mode && artwork && (components.data ?? []).every((component) => component.component_type && demoComponentSchematic[component.component_type]))

  return (
    <div>
      <PageIntro eyebrow="This Machine" title="Components" description="Schematic component navigation using backend-returned component identities. No physical coordinates or component status are fabricated." />

      <GlassPanel className="page-panel component-navigation-panel">
        {machine.isPending ? <LoadingSkeleton width="100%" height={120} label="Configured machine loading" /> : machine.data ? (
          <div className="component-machine-context">
            <div className="component-machine-context__artwork">
              {artwork ? <img src={artwork.src} alt="" /> : <Truck size={72} strokeWidth={1.2} aria-hidden="true" />}
            </div>
            <div>
              <span className="page-eyebrow">Configured machine</span>
              <h2>{machineIdentity(machine.data)}</h2>
              <p>{machineProduct(machine.data) ?? 'Machine model metadata not provided'}</p>
              <TechnicalId value={machine.data.id} />
            </div>
          </div>
        ) : null}
      </GlassPanel>

      <GlassPanel className="page-panel">
        <SectionHeader title="Schematic component map" description="Component cards are navigation/context objects only. Their layout does not claim physically accurate placement." />
        {foreignComponent ? (
          <ErrorState title="Machine-scope violation" description="The backend returned a component for another machine. The local UI will not expose that foreign component context." />
        ) : components.isPending ? (
          <div className="component-card-grid"><LoadingSkeleton width="100%" height={130} label="Components loading" /><LoadingSkeleton width="100%" height={130} label="Components loading" /></div>
        ) : components.isError ? (
          <ErrorState title="Components unavailable" description={errorDescription(components.error)} />
        ) : (components.data?.length ?? 0) === 0 ? (
          <EmptyState title="No components returned" description="The backend has no component identity records for the configured machine." />
        ) : demoSchematicReady ? (
          <div className="demo-schematic" aria-label="Demo schematic component navigation">
            <div className="demo-schematic__machine">{artwork ? <img src={artwork.src} alt="" /> : null}</div>
            {(components.data ?? []).map((component) => {
              const point = demoComponentSchematic[component.component_type ?? '']
              return <Link
                className="demo-schematic__node"
                to={`/components/${encodeURIComponent(component.id)}`}
                key={component.id}
                style={{ left: `${point.x}%`, top: `${point.y}%` }}
              >
                <strong>{component.display_name ?? component.component_type ?? 'Unnamed component'}</strong>
                <span>{component.component_type}</span>
              </Link>
            })}
          </div>
        ) : (
          <div className="component-card-grid" aria-label="Configured machine components">
            {(components.data ?? []).map((component) => (
              <Link className="component-nav-card" to={`/components/${encodeURIComponent(component.id)}`} key={component.id}>
                <span className="component-nav-card__icon"><Boxes size={20} aria-hidden="true" /></span>
                <div className="component-nav-card__copy">
                  <strong>{component.display_name ?? component.component_type ?? 'Unnamed component'}</strong>
                  <span>{component.component_type ?? 'Component type not provided'}</span>
                  <TechnicalId value={component.id} />
                </div>
                <ChevronRight size={18} aria-hidden="true" />
              </Link>
            ))}
          </div>
        )}
      </GlassPanel>
    </div>
  )
}
