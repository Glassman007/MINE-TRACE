import { Link } from 'react-router-dom'
import { useReturnToService } from '../api/returnToService'
import { EmptyState, ErrorState, GlassPanel, LoadingSkeleton, SectionHeader, StatusBadge, TechnicalId } from '../components/primitives'
import { PageIntro } from './PageIntro'
import './pages.css'

function tone(state: string): 'success' | 'warning' | 'danger' | 'neutral' {
  if (state === 'CLEARED') return 'success'
  if (state === 'VERIFICATION_REQUIRED') return 'warning'
  if (state === 'DO_NOT_RETURN') return 'danger'
  return 'neutral'
}

export function ReturnToServicePage() {
  const result = useReturnToService()
  return <div>
    <PageIntro eyebrow="Deterministic policy" title="Return to Service" description="This decision comes only from typed backend incident/verification rules. AI and semantic scores cannot set it." />
    <GlassPanel className="page-panel">
      {result.isPending ? <LoadingSkeleton width="100%" height={170} label="Return-to-service loading" />
        : result.isError ? <ErrorState title="Return-to-service unavailable" description="The deterministic backend policy could not be evaluated." />
        : result.data ? <>
          <SectionHeader title="Current decision" description={`${result.data.policy_identifier} · revision ${result.data.policy_revision}`} />
          <StatusBadge tone={tone(result.data.state)}>{result.data.state}</StatusBadge>
          {(result.data.blocking_reasons ?? []).length === 0 ? <EmptyState title="No blocking reasons" description="The active backend policy returned no blocking reasons." /> : <div className="record-list">
            {(result.data.blocking_reasons ?? []).map((reason, index) => <article className="record-row" key={`${reason.code}-${index}`}>
              <div className="record-row__body"><strong>{reason.code}</strong><span>{reason.message}</span>
                {reason.incident_id ? <Link to={`/incidents/${encodeURIComponent(reason.incident_id)}`}>Open incident</Link> : null}
                {reason.verification_id ? <TechnicalId value={reason.verification_id} /> : null}
                {reason.evidence_ids?.map((id) => <TechnicalId key={id} value={id} />)}
              </div>
            </article>)}
          </div>}
        </> : null}
    </GlassPanel>
  </div>
}
