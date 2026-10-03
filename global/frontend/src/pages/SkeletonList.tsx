import { LoadingSkeleton } from '../components/primitives'

interface SkeletonListProps {
  rows?: number
}

export function SkeletonList({ rows = 5 }: SkeletonListProps) {
  return (
    <div className="skeleton-list" aria-label="Layout placeholder">
      {Array.from({ length: rows }, (_, index) => (
        <div className="skeleton-row" key={index}>
          <LoadingSkeleton width="72%" height={14} label="Content placeholder" />
          <LoadingSkeleton width="64%" height={12} label="Content placeholder" />
          <LoadingSkeleton width="70%" height={12} label="Content placeholder" />
          <LoadingSkeleton width="58%" height={22} radius={999} label="Content placeholder" />
        </div>
      ))}
    </div>
  )
}
