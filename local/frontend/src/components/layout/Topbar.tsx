import { Menu } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { useBackendHealth } from '../../api/health'
import { getPageContext } from '../../app/routeMeta'
import { StatusBadge } from '../primitives'

interface TopbarProps {
  mobileMenuOpen: boolean
  onOpenMenu: () => void
}

export function Topbar({ mobileMenuOpen, onOpenMenu }: TopbarProps) {
  const location = useLocation()
  const context = getPageContext(location.pathname)
  const health = useBackendHealth()

  const healthPresentation = health.isPending
    ? { label: 'Backend checking', tone: 'neutral' as const }
    : health.isError || health.data.status !== 'ok' || health.data.database !== 'ok'
      ? { label: 'Backend unavailable', tone: 'danger' as const }
      : { label: 'Backend available', tone: 'success' as const }

  return (
    <header className="topbar">
      <div className="topbar__left">
        <button className="mobile-menu-button" type="button" onClick={onOpenMenu} aria-label="Open navigation" aria-controls="primary-navigation" aria-expanded={mobileMenuOpen}>
          <Menu size={19} aria-hidden="true" />
        </button>
        <div className="topbar__context">
          <span className="topbar__eyebrow">{context.eyebrow}</span>
          <span className="topbar__title">{context.shortTitle}</span>
        </div>
      </div>

      <div className="topbar__right">
        <StatusBadge tone={healthPresentation.tone} aria-live="polite">{healthPresentation.label}</StatusBadge>
        <span className="topbar__brand" aria-label="MINE-TRACE">
          <img src="/brand/mine-trace-logo.png" alt="" />
          <span>MINE-TRACE</span>
        </span>
      </div>
    </header>
  )
}
