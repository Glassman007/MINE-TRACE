import type { ReactNode } from 'react'

interface SectionHeaderProps {
  title: string
  description?: string
  action?: ReactNode
}

export function SectionHeader({ title, description, action }: SectionHeaderProps) {
  return (
    <div className="section-header">
      <div className="section-header__copy">
        <h2 className="section-heading">{title}</h2>
        {description ? <p className="section-header__description">{description}</p> : null}
      </div>
      {action}
    </div>
  )
}
