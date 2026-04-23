export type DocumentStatus = 'pending' | 'processing' | 'ready' | 'failed' | string

export interface DocumentSummary {
  id: number
  filename: string
  status: DocumentStatus
  content_type: string | null
  error_summary: string | null
  created_at: string
  updated_at: string
}

export interface Citation {
  document_id: number
  document_name: string
  chunk_id: number
  snippet: string
  page_number: number | null
  section_label: string | null
}

export interface ChatMessage {
  id: number
  role: string
  content: string
  grounded: boolean
  citations_json: Citation[] | null
  created_at: string
}

export interface ChatSession {
  id: number
  title: string
  created_at: string
  updated_at: string
}

export interface ChatSessionsResponse {
  sessions: ChatSession[]
}

export interface ChatHistoryResponse {
  messages: ChatMessage[]
}

export interface ChatExchangeResponse {
  user_message: ChatMessage
  assistant_message: ChatMessage
  citations: Citation[]
  grounded: boolean
}

export interface WorkspaceResponse {
  id: number
  name: string
  documents: DocumentSummary[]
  messages: ChatMessage[]
}

export interface DocumentListResponse {
  documents: DocumentSummary[]
}
