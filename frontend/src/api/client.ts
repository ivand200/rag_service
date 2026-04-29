import type {
  ChatExchangeResponse,
  ChatHistoryResponse,
  ChatMessageStreamDoneEvent,
  ChatMessageStreamErrorEvent,
  ChatMessageStreamEvent,
  ChatMessageStreamStartEvent,
  ChatMessageStreamTokenEvent,
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

async function requestNoContent(path: string, init?: RequestInit, authToken?: AuthToken): Promise<void> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      ...(init?.headers ?? {})
    }
  })

  if (!response.ok) {
    throw new ApiError(await readErrorMessage(response), response.status)
  }
}

async function readErrorMessage(response: Response): Promise<string> {
  let message = `Request failed with status ${response.status}`

  try {
    const payload = (await response.json()) as { detail?: string }
    if (payload.detail) {
      message = payload.detail
    }
  } catch {
    // Fall back to the default message when the response is not JSON.
  }

  return message
}

function parseStreamEvent(eventName: string, data: string): ChatMessageStreamEvent {
  switch (eventName) {
    case 'start':
      return {
        event: 'start',
        data: JSON.parse(data) as ChatMessageStreamStartEvent
      }
    case 'token':
      return {
        event: 'token',
        data: JSON.parse(data) as ChatMessageStreamTokenEvent
      }
    case 'done':
      return {
        event: 'done',
        data: JSON.parse(data) as ChatMessageStreamDoneEvent
      }
    case 'error':
      return {
        event: 'error',
        data: JSON.parse(data) as ChatMessageStreamErrorEvent
      }
    default:
      throw new Error(`Unsupported stream event: ${eventName}`)
  }
}

async function consumeSseStream(response: Response, onEvent: (event: ChatMessageStreamEvent) => void) {
  if (response.body === null) {
    throw new Error('Chat response stream is unavailable')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let currentEvent = 'message'
  let currentData: string[] = []

  const emitEvent = () => {
    if (currentData.length === 0) {
      currentEvent = 'message'
      return
    }

    onEvent(parseStreamEvent(currentEvent, currentData.join('\n')))
    currentEvent = 'message'
    currentData = []
  }

  const processBuffer = () => {
    let newlineIndex = buffer.indexOf('\n')

    while (newlineIndex >= 0) {
      let line = buffer.slice(0, newlineIndex)
      buffer = buffer.slice(newlineIndex + 1)

      if (line.endsWith('\r')) {
        line = line.slice(0, -1)
      }

      if (line.length === 0) {
        emitEvent()
      } else if (!line.startsWith(':')) {
        const separatorIndex = line.indexOf(':')
        const field = separatorIndex >= 0 ? line.slice(0, separatorIndex) : line
        const rawValue = separatorIndex >= 0 ? line.slice(separatorIndex + 1) : ''
        const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue

        if (field === 'event') {
          currentEvent = value
        } else if (field === 'data') {
          currentData.push(value)
        }
      }

      newlineIndex = buffer.indexOf('\n')
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
    processBuffer()

    if (done) {
      break
    }
  }

  if (buffer.length > 0) {
    buffer += '\n'
    processBuffer()
  }

  emitEvent()
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

  async streamChatMessage(
    sessionId: number,
    message: string,
    onEvent: (event: ChatMessageStreamEvent) => void,
    authToken?: AuthToken
  ) {
    const response = await fetch(`${API_BASE_URL}/chat/messages/stream`, {
      method: 'POST',
      headers: {
        Accept: 'text/event-stream',
        'Content-Type': 'application/json',
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {})
      },
      body: JSON.stringify({ session_id: sessionId, message })
    })

    if (!response.ok) {
      throw new ApiError(await readErrorMessage(response), response.status)
    }

    await consumeSseStream(response, onEvent)
  },

  async uploadDocument(file: File, authToken?: AuthToken) {
    const formData = new FormData()
    formData.append('file', file)

    return request<DocumentSummary>('/documents', {
      method: 'POST',
      body: formData,
      headers: {}
    }, authToken)
  },

  deleteDocument(documentId: number, authToken?: AuthToken) {
    return requestNoContent(`/documents/${documentId}`, {
      method: 'DELETE'
    }, authToken)
  }
}

export { ApiError }
