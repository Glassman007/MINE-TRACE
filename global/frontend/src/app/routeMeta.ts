interface PageContext {
  eyebrow: string
  title: string
  shortTitle: string
}

const exactRoutes: Record<string, PageContext> = {
  '/': { eyebrow: 'Fleet memory', title: 'Fleet Overview', shortTitle: 'Overview' },
  '/machines': { eyebrow: 'Asset registry', title: 'Machines', shortTitle: 'Machines' },
  '/incidents': { eyebrow: 'Fleet incidents', title: 'Incidents', shortTitle: 'Incidents' },
  '/maintenance': { eyebrow: 'Canonical work', title: 'Maintenance', shortTitle: 'Maintenance' },
  '/search': { eyebrow: 'Semantic recall', title: 'Fleet Search', shortTitle: 'Search' },
  '/analytics': { eyebrow: 'Relational facts', title: 'Analytics', shortTitle: 'Analytics' },
  '/sync': { eyebrow: 'Synchronization', title: 'Sync Status', shortTitle: 'Sync' },
  '/sync/conflicts': { eyebrow: 'Synchronization', title: 'Sync Conflicts', shortTitle: 'Conflicts' },
  '/ai': { eyebrow: 'Evidence-grounded AI', title: 'Fleet AI', shortTitle: 'AI' },
}

export function getPageContext(pathname: string): PageContext {
  const exact = exactRoutes[pathname]
  if (exact) return exact

  if (pathname.startsWith('/machines/')) {
    return { eyebrow: 'Asset memory', title: 'Machine Detail', shortTitle: 'Machine' }
  }
  if (pathname.startsWith('/incidents/')) {
    return { eyebrow: 'Incident memory', title: 'Incident Detail', shortTitle: 'Incident' }
  }

  return { eyebrow: 'MINE-TRACE', title: 'Not Found', shortTitle: 'Not Found' }
}
