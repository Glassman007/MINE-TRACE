interface TechnicalIdProps {
  value: string
  title?: string
}

export function TechnicalId({ value, title }: TechnicalIdProps) {
  return <code className="technical-id" title={title ?? value}>{value}</code>
}
