import type { HTMLAttributes } from 'react'
import { cn } from '../../utils/cn'
import './primitives.css'

export function GlassCard({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('glass-card', className)} {...props} />
}
