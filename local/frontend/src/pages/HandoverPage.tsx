import { ClipboardList, Info, LoaderCircle, ShieldCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../api/http'
import { useCreateHandover } from '../api/handover'
import { ErrorState, GlassPanel, SectionHeader } from '../components/primitives'
import { PageIntro } from './PageIntro'
import './pages.css'

function createErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    return error.code ? `${error.code}: ${error.message}` : error.message
  }
  return 'The handover packet could not be created. No frontend fallback packet was generated.'
}

export function HandoverPage() {
  const navigate = useNavigate()
  const create = useCreateHandover()

  const generate = () => {
    create.mutate(undefined, {
      onSuccess: (packet) => navigate(`/handover/${encodeURIComponent(packet.id)}`),
    })
  }

  return (
    <div className="handover-page">
      <PageIntro
        eyebrow="Shift continuity"
        title="Shift Handover"
        description="Create a persisted backend snapshot of the unresolved incidents applicable to the next shift."
      />

      <section className="handover-landing-grid">
        <GlassPanel className="page-panel handover-create-panel">
          <SectionHeader
            title="Create shift briefing"
            description="The backend decides which incidents belong in the packet. The frontend does not calculate handover membership."
          />

          <div className="handover-create-callout">
            <span className="handover-create-callout__icon"><ClipboardList size={22} aria-hidden="true" /></span>
            <div>
              <strong>Persist the current handover snapshot</strong>
              <p>Creation stores the packet and its incident snapshot so the returned packet URL can be reopened safely later.</p>
            </div>
          </div>

          {create.isError ? <ErrorState title="Handover creation failed" description={createErrorMessage(create.error)} /> : null}

          <button className="button button--primary handover-primary-action" type="button" disabled={create.isPending} onClick={generate}>
            {create.isPending ? <LoaderCircle className="spin" size={16} aria-hidden="true" /> : <ClipboardList size={16} aria-hidden="true" />}
            {create.isPending ? 'Creating handover…' : 'Create handover'}
          </button>
        </GlassPanel>

        <GlassPanel className="page-panel handover-rule-panel">
          <SectionHeader title="Acknowledgement semantics" description="Receipt is not resolution." />
          <div className="handover-semantics">
            <ShieldCheck size={20} aria-hidden="true" />
            <div>
              <strong>Acknowledgement means the next shift received the briefing.</strong>
              <p>It does not repair, verify, resolve, close, or otherwise change the status of any represented incident.</p>
            </div>
          </div>
          <div className="foundation-note">
            <Info size={16} aria-hidden="true" />
            <span>No handover history table is shown because the backend does not expose a handover collection endpoint.</span>
          </div>
        </GlassPanel>
      </section>
    </div>
  )
}
