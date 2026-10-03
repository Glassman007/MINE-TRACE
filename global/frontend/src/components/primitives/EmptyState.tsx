import { Inbox } from 'lucide-react'
import { GlassCard } from './GlassCard'

interface EmptyStateProps {
  title: string
  description: string
}

export function EmptyState({ title, description }: EmptyStateProps) {
  return (
    <GlassCard className="empty-state">
      <div>
        <span className="empty-state__icon"><Inbox size={20} aria-hidden="true" /></span>
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
    </GlassCard>
  )
}
