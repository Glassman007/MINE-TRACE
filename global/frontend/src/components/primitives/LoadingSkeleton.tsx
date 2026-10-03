import type { CSSProperties } from 'react'

interface LoadingSkeletonProps {
  width?: CSSProperties['width']
  height?: CSSProperties['height']
  radius?: CSSProperties['borderRadius']
  label?: string
}

export function LoadingSkeleton({
  width = '100%',
  height = 16,
  radius,
  label = 'Loading',
}: LoadingSkeletonProps) {
  return (
    <span
      className="loading-skeleton"
      style={{ width, height, borderRadius: radius, display: 'block' }}
      role="status"
      aria-label={label}
    />
  )
}
