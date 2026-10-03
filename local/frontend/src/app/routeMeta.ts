interface PageContext {
  eyebrow: string
  title: string
  shortTitle: string
}

const exactRoutes: Record<string, PageContext> = {
  '/': { eyebrow: 'Local node', title: 'This Machine', shortTitle: 'This Machine' },
  '/components': { eyebrow: 'This Machine', title: 'Components', shortTitle: 'Components' },
  '/history': { eyebrow: 'Canonical history', title: 'History', shortTitle: 'History' },
  '/search': { eyebrow: 'Derived semantic recall', title: 'Search', shortTitle: 'Search' },
  '/session': { eyebrow: 'Operating session', title: 'Session', shortTitle: 'Session' },
  '/return-to-service': { eyebrow: 'Deterministic policy', title: 'Return to Service', shortTitle: 'Return to Service' },
  '/sync': { eyebrow: 'Durable outbox', title: 'Sync', shortTitle: 'Sync' },
  '/incidents': { eyebrow: 'Evidence threads', title: 'Incidents', shortTitle: 'Incidents' },
  '/evidence/new': { eyebrow: 'Controlled ingestion', title: 'Add Evidence', shortTitle: 'Add Evidence' },
  '/handover': { eyebrow: 'Shift continuity', title: 'Handover', shortTitle: 'Handover' },
}

export function getPageContext(pathname: string): PageContext {
  const exact = exactRoutes[pathname]
  if (exact) return exact

  if (pathname.startsWith('/components/')) {
    return { eyebrow: 'Component exact history', title: 'Component Detail', shortTitle: 'Component' }
  }
  if (pathname.startsWith('/machines/')) {
    return { eyebrow: 'Local compatibility view', title: 'Machine Detail', shortTitle: 'Machine' }
  }
  if (pathname.startsWith('/incidents/')) {
    return { eyebrow: 'Incident memory', title: 'Incident Detail', shortTitle: 'Incident' }
  }
  if (pathname.startsWith('/handover/')) {
    return { eyebrow: 'Shift continuity', title: 'Handover Packet', shortTitle: 'Handover' }
  }

  return { eyebrow: 'MINE-TRACE', title: 'Not Found', shortTitle: 'Not Found' }
}
