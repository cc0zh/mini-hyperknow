import type { ServiceError } from './types'

export class ApiError extends Error {
  readonly code: string
  readonly retryable: boolean
  readonly status: number

  constructor(error: ServiceError, status = 0) {
    super(error.message)
    this.name = 'ApiError'
    this.code = error.code
    this.retryable = error.retryable
    this.status = status
  }
}

// These statuses explicitly reject input before the write commits.
export function isInputRejection(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 400 || error.status === 404 || error.status === 422)
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers },
      signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(30_000)]) : AbortSignal.timeout(30_000),
    })
  } catch (error) {
    if (options.signal?.aborted) throw error
    throw new ApiError({ code: 'CONNECTION_ERROR', message: '无法确认服务器响应。请检查本地后端和网络，再重试同一请求。', retryable: true })
  }
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const error = body && typeof body === 'object' && 'error' in body ? body.error as ServiceError : null
    throw new ApiError(error && typeof error.message === 'string' ? error : {
      code: `HTTP_${response.status}`,
      message: `服务器请求失败（${response.status}），未收到可读的错误详情。`,
      retryable: response.status >= 500,
    }, response.status)
  }
  if (body === null) throw new ApiError({ code: 'INVALID_RESPONSE', message: '服务器返回了无法读取的数据。', retryable: true })
  return body as T
}

export const post = <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) })

export function describeError(error: unknown): string {
  return error instanceof Error ? error.message : '发生未知错误，请重试。'
}
