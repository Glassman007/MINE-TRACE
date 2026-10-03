import { createBrowserRouter } from 'react-router-dom'
import { AppShell } from '../components/layout/AppShell'
import { AddEvidencePage } from '../pages/AddEvidencePage'
import { HandoverDetailPage } from '../pages/HandoverDetailPage'
import { HandoverPage } from '../pages/HandoverPage'
import { IncidentDetailPage } from '../pages/IncidentDetailPage'
import { IncidentsPage } from '../pages/IncidentsPage'
import { MachineDetailPage } from '../pages/MachineDetailPage'
import { NotFoundPage } from '../pages/NotFoundPage'
import { OverviewPage } from '../pages/OverviewPage'
import { ComponentsPage } from '../pages/ComponentsPage'
import { ComponentDetailPage } from '../pages/ComponentDetailPage'
import { HistoryPage } from '../pages/HistoryPage'
import { SearchPage } from '../pages/SearchPage'
import { SessionPage } from '../pages/SessionPage'
import { ReturnToServicePage } from '../pages/ReturnToServicePage'
import { SyncPage } from '../pages/SyncPage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <OverviewPage /> },
      { path: 'machines/:machineId', element: <MachineDetailPage /> },
      { path: 'components', element: <ComponentsPage /> },
      { path: 'components/:componentId', element: <ComponentDetailPage /> },
      { path: 'history', element: <HistoryPage /> },
      { path: 'search', element: <SearchPage /> },
      { path: 'session', element: <SessionPage /> },
      { path: 'return-to-service', element: <ReturnToServicePage /> },
      { path: 'sync', element: <SyncPage /> },
      { path: 'incidents', element: <IncidentsPage /> },
      { path: 'incidents/:incidentId', element: <IncidentDetailPage /> },
      { path: 'evidence/new', element: <AddEvidencePage /> },
      { path: 'handover', element: <HandoverPage /> },
      { path: 'handover/:packetId', element: <HandoverDetailPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
