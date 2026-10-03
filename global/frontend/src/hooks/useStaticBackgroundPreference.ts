import { useEffect, useState } from 'react'
import { useReducedMotion } from './useReducedMotion'

type NavigatorWithHints = Navigator & {
  connection?: EventTarget & { saveData?: boolean }
  deviceMemory?: number
}

const compactViewportQuery = '(max-width: 520px)'

function readConstrainedDevicePreference() {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return false

  const runtimeNavigator = navigator as NavigatorWithHints
  const compactViewport = typeof window.matchMedia === 'function'
    ? window.matchMedia(compactViewportQuery).matches
    : false
  const saveData = runtimeNavigator.connection?.saveData === true
  const lowMemory = typeof runtimeNavigator.deviceMemory === 'number' && runtimeNavigator.deviceMemory <= 4

  return compactViewport || saveData || lowMemory
}

export function useStaticBackgroundPreference() {
  const reducedMotion = useReducedMotion()
  const [constrainedDevice, setConstrainedDevice] = useState(readConstrainedDevicePreference)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return

    const viewport = window.matchMedia(compactViewportQuery)
    const runtimeNavigator = navigator as NavigatorWithHints
    const connection = runtimeNavigator.connection
    const update = () => setConstrainedDevice(readConstrainedDevicePreference())

    update()
    viewport.addEventListener('change', update)
    connection?.addEventListener?.('change', update)

    return () => {
      viewport.removeEventListener('change', update)
      connection?.removeEventListener?.('change', update)
    }
  }, [])

  return reducedMotion || constrainedDevice
}
