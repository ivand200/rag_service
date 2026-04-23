import type {
  ChatExchangeResponse,
  ChatHistoryResponse,
  ChatSession,
  ChatSessionsResponse,
  DocumentListResponse,
  DocumentSummary,
  WorkspaceResponse
} from '../types/workspace'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? ''
type AuthToken = string | null | undefined

class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit, authToken?: AuthToken): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      ...(init?.headers ?? {})
    }
  })

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`

    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload.detail) {
        message = payload.detail
      }
    } catch {
      // Fall back to the default message when the response is not JSON.
    }

    throw new ApiError(message, response.status)
  }

  return (await response.json()) as T
}

export const apiClient = {
  getWorkspace(authToken?: AuthToken) {
    return request<WorkspaceResponse>('/workspace', undefined, authToken)
  },

  listDocuments(authToken?: AuthToken) {
    return request<DocumentListResponse>('/documents', undefined, authToken)
  },

  listChatSessions(authToken?: AuthToken) {
    return request<ChatSessionsResponse>('/chat/sessions', undefined, authToken)
  },

  createChatSession(authToken?: AuthToken) {
    return request<ChatSession>('/chat/sessions', {
      method: 'POST'
    }, authToken)
  },

  getChatHistory(sessionId: number, authToken?: AuthToken) {
    return request<ChatHistoryResponse>(`/chat/messages?session_id=${sessionId}`, undefined, authToken)
  },

  sendChatMessage(sessionId: number, message: string, authToken?: AuthToken) {
    return request<ChatExchangeResponse>('/chat/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ session_id: sessionId, message })
    }, authToken)
  },

  async uploadDocument(file: File, authToken?: AuthToken) {
    const formData = new FormData()
    formData.append('file', file)

    return request<DocumentSummary>('/documents', {
      method: 'POST',
      body: formData,
      headers: {}
    }, authToken)
  }
}

export { ApiError }
