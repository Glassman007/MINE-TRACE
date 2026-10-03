import { useEffect, useRef, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { AppBackground } from '../background/AppBackground'
import { PageContainer } from './PageContainer'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import { cn } from '../../utils/cn'
import './layout.css'

export function AppShell() {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const wasMobileOpen = useRef(false)
  const location = useLocation()

  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  useEffect(() => {
    const frame = document.querySelector<HTMLElement>('.app-shell__frame')

    if (!mobileOpen) {
      frame?.removeAttribute('inert')
      if (wasMobileOpen.current) {
        document.querySelector<HTMLButtonElement>('.mobile-menu-button')?.focus()
      }
      wasMobileOpen.current = false
      return
    }

    wasMobileOpen.current = true
    const previous = document.body.style.overflow
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMobileOpen(false)
    }

    document.body.style.overflow = 'hidden'
    frame?.setAttribute('inert', '')
    window.addEventListener('keydown', handleKeyDown)
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLAnchorElement>('#primary-navigation .sidebar-nav__item')?.focus()
    })

    return () => {
      document.body.style.overflow = previous
      frame?.removeAttribute('inert')
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [mobileOpen])

  return (
    <div className={cn('app-shell', collapsed && 'app-shell--collapsed')}>
      <AppBackground />
      {mobileOpen ? (
        <button
          className="mobile-drawer-backdrop"
          type="button"
          onClick={() => setMobileOpen(false)}
          aria-label="Close navigation"
        />
      ) : null}
      <Sidebar
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onToggleCollapse={() => setCollapsed((value) => !value)}
        onNavigate={() => setMobileOpen(false)}
      />
      <div className="app-shell__frame">
        <Topbar mobileMenuOpen={mobileOpen} onOpenMenu={() => setMobileOpen(true)} />
        <PageContainer>
          <Outlet />
        </PageContainer>
      </div>
    </div>
  )
}
