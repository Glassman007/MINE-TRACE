import type { HTMLAttributes } from 'react'
import { cn } from '../../utils/cn'

type StatusTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger'

interface StatusBadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: StatusTone
  showDot?: boolean
}

export function StatusBadge({ tone = 'neutral', showDot = true, className, children, ...props }: StatusBadgeProps) {
  return (
    <span className={cn('status-badge', `status-badge--${tone}`, className)} {...props}>
      {showDot ? <span className="status-badge__dot" aria-hidden="true" /> : null}
      {children}
    </span>
  )
}
