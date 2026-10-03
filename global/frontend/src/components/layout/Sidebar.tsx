import {
  Activity,
  BarChart3,
  Bot,
  ChevronLeft,
  ChevronRight,
  Factory,
  Gauge,
  RefreshCw,
  Search,
  ShieldAlert,
  Wrench,
} from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { cn } from '../../utils/cn'

const navigation = [
  { to: '/', label: 'Overview', icon: Gauge, end: true },
  { to: '/machines', label: 'Machines', icon: Factory },
  { to: '/incidents', label: 'Incidents', icon: ShieldAlert },
  { to: '/maintenance', label: 'Maintenance', icon: Wrench },
  { to: '/search', label: 'Semantic search', icon: Search },
  { to: '/analytics', label: 'Analytics', icon: BarChart3 },
  { to: '/sync', label: 'Synchronization', icon: RefreshCw },
  { to: '/ai', label: 'Fleet AI', icon: Bot },
]

interface SidebarProps {
  collapsed: boolean
  mobileOpen: boolean
  onToggleCollapse: () => void
  onNavigate: () => void
}

export function Sidebar({ collapsed, mobileOpen, onToggleCollapse, onNavigate }: SidebarProps) {
  return (
    <aside id="primary-navigation" className={cn('sidebar', mobileOpen && 'sidebar--open')} aria-label="Primary navigation">
      <button
        className="sidebar-collapse"
        type="button"
        onClick={onToggleCollapse}
        aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
      >
        {collapsed ? <ChevronRight size={16} aria-hidden="true" /> : <ChevronLeft size={16} aria-hidden="true" />}
      </button>

      <div className="sidebar__inner">
        <div className="brand-lockup">
          <img className="brand-lockup__mark" src="/brand/mine-trace-logo.png" alt="" />
          <div className="brand-lockup__copy">
            <span className="brand-lockup__name">MINE-TRACE</span>
            <span className="brand-lockup__tagline">Fleet memory command center</span>
          </div>
        </div>

        <div className="sidebar__section-label">Global workspace</div>
        <nav className="sidebar-nav">
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={onNavigate}
              className={({ isActive }) => cn('sidebar-nav__item', isActive && 'active')}
              title={collapsed ? label : undefined}
            >
              <Icon className="sidebar-nav__icon" size={19} aria-hidden="true" />
              <span className="sidebar-nav__label">{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar__footer">
          <span className="sidebar__footer-icon"><Activity size={16} aria-hidden="true" /></span>
          <span className="sidebar__footer-copy">Canonical state remains PostgreSQL-owned.</span>
        </div>
      </div>
    </aside>
  )
}
