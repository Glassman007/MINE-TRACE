import type { ReactNode } from 'react'

interface PageIntroProps {
  eyebrow: string
  title: string
  description: string
  aside?: ReactNode
  children?: ReactNode
}

export function PageIntro({ eyebrow, title, description, aside, children }: PageIntroProps) {
  return (
    <header className="page-intro">
      <div className="page-intro__copy">
        <p className="page-eyebrow">{eyebrow}</p>
        <h1 className="page-title">{title}</h1>
        <p className="page-intro__description">{description}</p>
        {children}
      </div>
      {aside}
    </header>
  )
}
