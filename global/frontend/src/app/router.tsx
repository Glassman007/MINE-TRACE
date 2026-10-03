import { createBrowserRouter } from 'react-router-dom'
import { AppShell } from '../components/layout/AppShell'
import { AIPage } from '../pages/AIPage'
import { AnalyticsPage } from '../pages/AnalyticsPage'
import { IncidentDetailPage } from '../pages/IncidentDetailPage'
import { IncidentsPage } from '../pages/IncidentsPage'
import { MachineDetailPage } from '../pages/MachineDetailPage'
import { MachinesPage } from '../pages/MachinesPage'
import { MaintenancePage } from '../pages/MaintenancePage'
import { NotFoundPage } from '../pages/NotFoundPage'
import { OverviewPage } from '../pages/OverviewPage'
import { SearchPage } from '../pages/SearchPage'
import { SyncConflictsPage } from '../pages/SyncConflictsPage'
import { SyncPage } from '../pages/SyncPage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <OverviewPage /> },
      { path: 'machines', element: <MachinesPage /> },
      { path: 'machines/:machineId', element: <MachineDetailPage /> },
      { path: 'incidents', element: <IncidentsPage /> },
      { path: 'incidents/:incidentId', element: <IncidentDetailPage /> },
      { path: 'maintenance', element: <MaintenancePage /> },
      { path: 'search', element: <SearchPage /> },
      { path: 'analytics', element: <AnalyticsPage /> },
      { path: 'sync', element: <SyncPage /> },
      { path: 'sync/conflicts', element: <SyncConflictsPage /> },
      { path: 'ai', element: <AIPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
