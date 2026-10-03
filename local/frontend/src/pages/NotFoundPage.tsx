import { Link } from 'react-router-dom'
import { GlassPanel } from '../components/primitives'

export function NotFoundPage() {
  return (
    <div className="not-found-page">
      <GlassPanel className="not-found-page__panel">
        <span className="not-found-page__code">404 / ROUTE_NOT_FOUND</span>
        <h1>Workspace route not found</h1>
        <p>The requested frontend route is not part of the accepted MINE-TRACE route architecture.</p>
        <Link className="button button--primary" to="/">Return to overview</Link>
      </GlassPanel>
    </div>
  )
}
