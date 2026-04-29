<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { ApiError, apiClient } from '../api/client'
import ChatPanel from '../components/ChatPanel.vue'
import DocumentRail from '../components/DocumentRail.vue'
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import type {
  ChatDisplayMessage,
  ChatMessage,
  ChatSession,
  DocumentSummary,
  StreamingAssistantMessage,
  WorkspaceResponse
} from '../types/workspace'

const props = defineProps<{
  userLabel: string
  getAccessToken: () => Promise<string | null>
}>()

const workspace = ref<WorkspaceResponse | null>(null)
const documents = ref<DocumentSummary[]>([])
const sessions = ref<ChatSession[]>([])
const messages = ref<ChatDisplayMessage[]>([])
const activeSessionId = ref<number | null>(null)
const isLoading = ref(true)
const isRefreshing = ref(false)
const isUploading = ref(false)
const isCreatingSession = ref(false)
const isLoadingSessions = ref(false)
const isLoadingHistory = ref(false)
const isSending = ref(false)
const deletingDocumentId = ref<number | null>(null)
const loadError = ref('')
const uploadError = ref('')
const uploadSuccess = ref('')
const sendError = ref('')
const sessionError = ref('')
const deleteErrorDocumentId = ref<number | null>(null)
const deleteError = ref('')
const locallyDeletedDocumentIds = ref<Set<number>>(new Set())

let historyRequestId = 0
let streamingAssistantCounter = 0

const POLL_INTERVAL_MS = 3000
let pollingHandle: number | null = null
let sessionMetadataPollingHandle: number | null = null
const streamingAssistantId = ref<string | null>(null)

const readyCount = computed(() => documents.value.filter((document) => document.status === 'ready').length)
const processingCount = computed(
  () =>
    documents.value.filter(
      (document) => document.status === 'pending' || document.status === 'processing'
    ).length
)
const failedCount = computed(() => documents.value.filter((document) => document.status === 'failed').length)
const hasActiveIngestion = computed(() =>
  documents.value.some((document) => document.status === 'pending' || document.status === 'processing')
)

function withoutLocallyDeletedDocuments(nextDocuments: DocumentSummary[]) {
  return nextDocuments.filter((document) => !locallyDeletedDocumentIds.value.has(document.id))
}

function mergeWorkspaceDocuments(payload: WorkspaceResponse) {
  workspace.value = payload
  documents.value = withoutLocallyDeletedDocuments(payload.documents)
}

const activeSession = computed(() =>
  sessions.value.find((session) => session.id === activeSessionId.value) ?? null
)
const shouldRefreshActiveSessionMetadata = computed(() =>
  activeSession.value !== null &&
  activeSession.value.title === 'New session' &&
  messages.value.length > 0
)

async function loadWorkspace() {
  loadError.value = ''

  try {
    const payload = await apiClient.getWorkspace(await props.getAccessToken())
    mergeWorkspaceDocuments(payload)
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : 'Failed to load workspace'
  } finally {
    isLoading.value = false
  }
}

function chooseActiveSessionId(nextSessions: ChatSession[]) {
  if (nextSessions.length === 0) {
    activeSessionId.value = null
    return
  }

  const currentId = activeSessionId.value
  const currentStillExists = currentId !== null && nextSessions.some((session) => session.id === currentId)
  activeSessionId.value = currentStillExists ? currentId : nextSessions[0].id
}

async function loadSessions() {
  isLoadingSessions.value = true
  sessionError.value = ''

  try {
    const payload = await apiClient.listChatSessions(await props.getAccessToken())
    sessions.value = payload.sessions
    chooseActiveSessionId(payload.sessions)
  } catch (error) {
    sessionError.value = error instanceof Error ? error.message : 'Failed to load sessions'
  } finally {
    isLoadingSessions.value = false
  }
}

async function refreshSessionsUntilTitled() {
  await loadSessions()

  if (!shouldRefreshActiveSessionMetadata.value) {
    stopSessionMetadataPolling()
  }
}

async function loadChatHistory(sessionId: number | null) {
  if (sessionId === null) {
    messages.value = []
    streamingAssistantId.value = null
    return
  }

  isLoadingHistory.value = true
  const requestId = ++historyRequestId

  try {
    const payload = await apiClient.getChatHistory(sessionId, await props.getAccessToken())
    if (requestId !== historyRequestId) {
      return
    }

    messages.value = payload.messages
    streamingAssistantId.value = null
    sendError.value = ''
  } catch (error) {
    if (requestId !== historyRequestId) {
      return
    }

    messages.value = []
    streamingAssistantId.value = null
    sendError.value = error instanceof Error ? error.message : 'Failed to load chat history'
  } finally {
    if (requestId === historyRequestId) {
      isLoadingHistory.value = false
    }
  }
}

function stopPolling() {
  if (pollingHandle !== null) {
    window.clearInterval(pollingHandle)
    pollingHandle = null
  }
}

function stopSessionMetadataPolling() {
  if (sessionMetadataPollingHandle !== null) {
    window.clearInterval(sessionMetadataPollingHandle)
    sessionMetadataPollingHandle = null
  }
}

function ensurePolling() {
  if (pollingHandle !== null || !hasActiveIngestion.value) {
    return
  }

  pollingHandle = window.setInterval(() => {
    void refreshDocuments({ silent: true })
  }, POLL_INTERVAL_MS)
}

function ensureSessionMetadataPolling() {
  if (sessionMetadataPollingHandle !== null || !shouldRefreshActiveSessionMetadata.value) {
    return
  }

  sessionMetadataPollingHandle = window.setInterval(() => {
    void refreshSessionsUntilTitled()
  }, POLL_INTERVAL_MS)
}

async function refreshDocuments(options: { silent?: boolean } = {}) {
  if (isLoading.value) {
    return
  }

  if (!options.silent) {
    isRefreshing.value = true
  }

  try {
    const payload = await apiClient.listDocuments(await props.getAccessToken())
    const nextDocuments = withoutLocallyDeletedDocuments(payload.documents)
    documents.value = nextDocuments
    uploadError.value = ''

    if (nextDocuments.some((document) => document.status === 'pending' || document.status === 'processing')) {
      ensurePolling()
    } else {
      stopPolling()
    }
  } catch (error) {
    uploadError.value = error instanceof Error ? error.message : 'Failed to refresh documents'
  } finally {
    if (!options.silent) {
      isRefreshing.value = false
    }
  }
}

async function onUpload(file: File) {
  uploadError.value = ''
  uploadSuccess.value = ''
  deleteError.value = ''
  deleteErrorDocumentId.value = null
  isUploading.value = true

  try {
    const created = await apiClient.uploadDocument(file, await props.getAccessToken())
    uploadSuccess.value = `${created.filename} uploaded and queued for ingestion.`
    documents.value = withoutLocallyDeletedDocuments([
      created,
      ...documents.value.filter((document) => document.id !== created.id)
    ])
    ensurePolling()
    await refreshDocuments()
  } catch (error) {
    if (error instanceof ApiError) {
      uploadError.value = error.message
    } else {
      uploadError.value = error instanceof Error ? error.message : 'Upload failed'
    }
  } finally {
    isUploading.value = false
  }
}

async function onDeleteDocument(documentId: number) {
  if (deletingDocumentId.value !== null) {
    return
  }

  deletingDocumentId.value = documentId
  deleteErrorDocumentId.value = null
  deleteError.value = ''

  try {
    await apiClient.deleteDocument(documentId, await props.getAccessToken())
    locallyDeletedDocumentIds.value = new Set([...locallyDeletedDocumentIds.value, documentId])
    documents.value = withoutLocallyDeletedDocuments(documents.value)

    if (!hasActiveIngestion.value) {
      stopPolling()
    }
  } catch (error) {
    deleteErrorDocumentId.value = documentId
    deleteError.value = error instanceof Error ? error.message : 'Failed to delete document'
  } finally {
    deletingDocumentId.value = null
  }
}

async function onSend(message: string) {
  if (activeSessionId.value === null) {
    sendError.value = 'Select or create a session before sending a message'
    return
  }

  const sessionId = activeSessionId.value
  sendError.value = ''
  isSending.value = true
  let streamFailed = false

  try {
    await apiClient.streamChatMessage(
      sessionId,
      message,
      (event) => {
        if (event.event === 'start') {
          applyStreamStart(sessionId, event.data.user_message)
          return
        }

        if (event.event === 'token') {
          appendStreamToken(sessionId, event.data.text)
          return
        }

        if (event.event === 'done') {
          finalizeStreamSuccess(sessionId, event.data.assistant_message)
          return
        }

        streamFailed = true
        finalizeStreamFailure(sessionId, event.data.detail)
      },
      await props.getAccessToken()
    )
    await loadSessions()
    ensureSessionMetadataPolling()
  } catch (error) {
    streamFailed = true
    if (error instanceof ApiError) {
      finalizeStreamFailure(sessionId, error.message)
    } else {
      finalizeStreamFailure(
        sessionId,
        error instanceof Error ? error.message : 'Failed to send message'
      )
    }
  } finally {
    if (!streamFailed && activeSessionId.value === sessionId && streamingAssistantId.value !== null) {
      streamingAssistantId.value = null
    }
    isSending.value = false
  }
}

async function onCreateSession() {
  isCreatingSession.value = true
  sessionError.value = ''

  try {
    const chatSession = await apiClient.createChatSession(await props.getAccessToken())
    const existing = sessions.value.find((session) => session.id === chatSession.id)
    const nextSessions = existing
      ? sessions.value.map((session) => (session.id === chatSession.id ? chatSession : session))
      : [chatSession, ...sessions.value]

    sessions.value = nextSessions.sort(
      (left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime()
    )
    activeSessionId.value = chatSession.id
  } catch (error) {
    sessionError.value = error instanceof Error ? error.message : 'Failed to create a session'
  } finally {
    isCreatingSession.value = false
  }
}

function onSelectSession(sessionId: number) {
  if (sessionId === activeSessionId.value) {
    return
  }

  activeSessionId.value = sessionId
}

function createStreamingAssistantMessage(): StreamingAssistantMessage {
  streamingAssistantCounter += 1
  return {
    client_id: `stream-${Date.now()}-${streamingAssistantCounter}`,
    role: 'assistant',
    content: '',
    grounded: false,
    citations_json: null,
    created_at: new Date().toISOString(),
    failed: false,
    error_detail: null
  }
}

function isStreamingAssistantMessage(message: ChatDisplayMessage): message is StreamingAssistantMessage {
  return 'client_id' in message
}

function applyStreamStart(sessionId: number, userMessage: ChatMessage) {
  if (activeSessionId.value !== sessionId) {
    return
  }

  const streamingAssistant = createStreamingAssistantMessage()
  streamingAssistantId.value = streamingAssistant.client_id
  messages.value = [...messages.value, userMessage, streamingAssistant]
}

function appendStreamToken(sessionId: number, text: string) {
  if (activeSessionId.value !== sessionId || streamingAssistantId.value === null) {
    return
  }

  messages.value = messages.value.map((message) => {
    if (!isStreamingAssistantMessage(message) || message.client_id !== streamingAssistantId.value) {
      return message
    }

    return {
      ...message,
      content: `${message.content}${text}`
    }
  })
}

function finalizeStreamSuccess(sessionId: number, assistantMessage: ChatMessage) {
  if (activeSessionId.value !== sessionId) {
    streamingAssistantId.value = null
    return
  }

  if (streamingAssistantId.value === null) {
    const alreadyPresent = messages.value.some((message) =>
      !isStreamingAssistantMessage(message) && message.id === assistantMessage.id
    )
    if (!alreadyPresent) {
      messages.value = [...messages.value, assistantMessage]
    }
    return
  }

  messages.value = messages.value.map((message) =>
    isStreamingAssistantMessage(message) && message.client_id === streamingAssistantId.value
      ? assistantMessage
      : message
  )
  streamingAssistantId.value = null
}

function finalizeStreamFailure(sessionId: number, detail: string) {
  sendError.value = detail

  if (activeSessionId.value !== sessionId || streamingAssistantId.value === null) {
    return
  }

  messages.value = messages.value.map((message) => {
    if (!isStreamingAssistantMessage(message) || message.client_id !== streamingAssistantId.value) {
      return message
    }

    return {
      ...message,
      failed: true,
      error_detail: detail
    }
  })
  streamingAssistantId.value = null
}

onMounted(async () => {
  await loadWorkspace()
  await loadSessions()

  if (hasActiveIngestion.value) {
    ensurePolling()
  }
})

watch(activeSessionId, async (sessionId) => {
  await loadChatHistory(sessionId)
}, { immediate: true })

watch(shouldRefreshActiveSessionMetadata, (shouldRefresh) => {
  if (shouldRefresh) {
    ensureSessionMetadataPolling()
    return
  }

  stopSessionMetadataPolling()
}, { immediate: true })

onBeforeUnmount(() => {
  stopPolling()
  stopSessionMetadataPolling()
})
</script>

<template>
  <div class="shell">
    <main class="workspace">
      <WorkspaceHeader
        :ready-count="readyCount"
        :processing-count="processingCount"
        :failed-count="failedCount"
        :user-label="userLabel"
      />

      <p v-if="loadError" class="page-error">{{ loadError }}</p>

      <section class="t-body">
        <DocumentRail
          :documents="documents"
          :is-loading="isLoading || isRefreshing"
          :is-uploading="isUploading"
          :deleting-document-id="deletingDocumentId"
          :upload-error="uploadError"
          :upload-success="uploadSuccess"
          :delete-error-document-id="deleteErrorDocumentId"
          :delete-error="deleteError"
          @upload="onUpload"
          @refresh="refreshDocuments"
          @delete-document="onDeleteDocument"
        />

        <ChatPanel
          :sessions="sessions"
          :active-session-id="activeSessionId"
          :active-session-title="activeSession?.title ?? 'New session'"
          :messages="messages"
          :streaming-assistant-id="streamingAssistantId"
          :ready-count="readyCount"
          :total-count="documents.length"
          :pending-count="processingCount"
          :is-loading-sessions="isLoadingSessions"
          :is-creating-session="isCreatingSession"
          :is-sending="isSending"
          :is-loading-history="isLoadingHistory"
          :send-error="sendError"
          :session-error="sessionError"
          @create-session="onCreateSession"
          @select-session="onSelectSession"
          @send="onSend"
        />
      </section>
    </main>
  </div>
</template>
