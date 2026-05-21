const DEFAULT_BASE_URL = import.meta.env.DEFAULT_BASE_URL

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || DEFAULT_BASE_URL).replace(
  /\/$/,
  '',
)

async function readJsonResponse(response) {
  const text = await response.text()
  if (!text) return null

  try {
    return JSON.parse(text)
  } catch {
    return { message: text }
  }
}

export async function apiRequest(path, { method = 'GET', body } = {}) {
  const url = `${API_BASE_URL}${path}`

  const response = await fetch(url, {
    method,
    headers: {
      Accept: 'application/json',
      ...(body ? { 'Content-Type': 'application/json' } : null),
    },
    body: body ? JSON.stringify(body) : undefined,
  })

  const data = await readJsonResponse(response)

  if (!response.ok) {
    const message =
      (data && (data.detail || data.message)) ||
      `Request failed (${response.status})`
    const error = new Error(message)
    error.status = response.status
    error.data = data
    throw error
  }

  return data
}

export function createOrder(payload) {
  return apiRequest('/orders', { method: 'POST', body: payload })
}

export function scan(payload) {
  return apiRequest('/scan', { method: 'POST', body: payload })
}

export function getTimeline(orderId) {
  return apiRequest(`/orders/${encodeURIComponent(orderId)}/timeline`)
}
