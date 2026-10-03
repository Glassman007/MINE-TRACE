import type { HTMLAttributes } from 'react'
import { cn } from '../../utils/cn'

export function PageContainer({ className, ...props }: HTMLAttributes<HTMLElement>) {
  return <main className={cn('page-container', className)} {...props} />
}
