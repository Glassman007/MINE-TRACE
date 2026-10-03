import { useStaticBackgroundPreference } from '../../hooks/useStaticBackgroundPreference'
import './AppBackground.css'

export function AppBackground() {
  const staticBackground = useStaticBackgroundPreference()

  return (
    <div className="app-background" aria-hidden="true">
      <div className="app-background__fallback" />
      {!staticBackground ? (
        <video
          className="app-background__video"
          autoPlay
          loop
          muted
          playsInline
          preload="metadata"
          tabIndex={-1}
        >
          <source src="/media/mine-trace-glass-grid.mp4" type="video/mp4" />
        </video>
      ) : null}
      <div className="app-background__readability" />
      <div className="app-background__vignette" />
    </div>
  )
}
