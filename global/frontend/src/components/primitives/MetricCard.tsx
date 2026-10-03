import type { LucideIcon } from 'lucide-react'
import { GlassCard } from './GlassCard'
import { LoadingSkeleton } from './LoadingSkeleton'

interface MetricCardProps {
  label: string
  value?: string | number
  icon?: LucideIcon
  loading?: boolean
  meta?: string
}

export function MetricCard({ label, value, icon: Icon, loading = false, meta }: MetricCardProps) {
  return (
    <GlassCard className="metric-card">
      <div className="metric-card__top">
        <p className="metric-card__label">{label}</p>
        {Icon ? <span className="metric-card__icon"><Icon size={17} aria-hidden="true" /></span> : null}
      </div>
      <div>
        {loading ? <LoadingSkeleton width="58%" height={34} label={`${label} loading`} /> : <div className="metric-text">{value ?? '—'}</div>}
        {meta ? <div className="metadata-text" style={{ marginTop: 8 }}>{meta}</div> : null}
      </div>
    </GlassCard>
  )
}
