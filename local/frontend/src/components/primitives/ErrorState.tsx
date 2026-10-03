import { TriangleAlert } from 'lucide-react'
import { GlassCard } from './GlassCard'

interface ErrorStateProps {
  title?: string
  description: string
}

export function ErrorState({ title = 'Unable to load', description }: ErrorStateProps) {
  return (
    <GlassCard className="error-state" role="alert">
      <div>
        <span className="error-state__icon"><TriangleAlert size={20} aria-hidden="true" /></span>
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
    </GlassCard>
  )
}
