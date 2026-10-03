export class ApiError extends Error {
  readonly status: number
  readonly code?: string
  readonly details?: unknown

  constructor(message: string, status: number, code?: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

interface ErrorEnvelope {
  error?: {
    code?: string
    message?: string
    details?: unknown
  }
  detail?: string | Array<Record<string, unknown>>
}

async function parseApiError(response: Response): Promise<ApiError> {
  let payload: ErrorEnvelope | undefined
  try {
    payload = await response.json() as ErrorEnvelope
  } catch {
    payload = undefined
  }

  let message = `Request failed with status ${response.status}`
  if (payload?.error?.message) {
    message = payload.error.message
  } else if (typeof payload?.detail === 'string') {
    message = payload.detail
  } else if (Array.isArray(payload?.detail)) {
    const parts = payload.detail
      .map((item) => {
        const msg = typeof item.msg === 'string' ? item.msg : null
        const loc = Array.isArray(item.loc) ? item.loc.join('.') : null
        return msg ? `${loc ? `${loc}: ` : ''}${msg}` : null
      })
      .filter((item): item is string => Boolean(item))
    if (parts.length > 0) message = parts.join('; ')
  }

  return new ApiError(message, response.status, payload?.error?.code, payload?.error?.details ?? payload?.detail)
}

async function requestJson<T>(path: string, init: RequestInit): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body !== undefined && init.body !== null && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(path, { ...init, headers })
  if (!response.ok) throw await parseApiError(response)

  if (response.status === 204) return undefined as T
  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  return requestJson<T>(path, { ...init, method: 'GET' })
}

export function apiPost<TResponse, TBody = unknown>(path: string, body?: TBody, init?: RequestInit): Promise<TResponse> {
  return requestJson<TResponse>(path, {
    ...init,
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}
