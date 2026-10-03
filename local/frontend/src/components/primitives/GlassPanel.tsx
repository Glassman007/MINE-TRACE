import type { HTMLAttributes } from 'react'
import { cn } from '../../utils/cn'
import './primitives.css'

export function GlassPanel({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('glass-panel', className)} {...props} />
}
