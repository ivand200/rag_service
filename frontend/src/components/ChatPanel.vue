<script setup lang="ts">
import { computed, ref } from 'vue'

import CitationList from './CitationList.vue'
import type { ChatMessage, ChatSession, Citation } from '../types/workspace'

const props = defineProps<{
  sessions: ChatSession[]
  activeSessionId: number | null
  activeSessionTitle: string
  messages: ChatMessage[]
  readyCount: number
  totalCount: number
  pendingCount: number
  isLoadingSessions: boolean
  isCreatingSession: boolean
  isSending: boolean
  isLoadingHistory: boolean
  sessionError: string
  sendError: string
}>()

const emit = defineEmits<{
  createSession: []
  selectSession: [sessionId: number]
  send: [message: string]
}>()

const draft = ref('')

const canSend = computed(
  () =>
    draft.value.trim().length > 0 &&
    props.readyCount > 0 &&
    !props.isSending &&
    props.activeSessionId !== null
)
const activeContextLabel = computed(() => `${props.readyCount} of ${props.totalCount} docs active`)

function citationList(message: ChatMessage): Citation[] {
  return message.citations_json ?? []
}

function evidenceLabel(message: ChatMessage) {
  if (message.grounded) {
    return 'Strong evidence'
  }

  return citationList(message).length > 0 ? 'Partial match' : 'Insufficient support'
}

function evidenceTone(message: ChatMessage) {
  return message.grounded ? 'strong' : 'partial'
}

function submit() {
  const message = draft.value.trim()
  if (!message || !canSend.value) {
    return
  }

  emit('send', message)
  draft.value = ''
}
</script>

<template>
  <section class="t-main" aria-label="Conversation">
    <header class="t-session-bar">
      <div class="t-session-bar-copy">
        <span class="t-session-kicker">Sessions</span>
        <h2 class="t-session-heading">{{ activeSessionTitle }}</h2>
      </div>

      <button class="t-session-new" type="button" :disabled="isCreatingSession" @click="emit('createSession')">
        {{ isCreatingSession ? 'Opening...' : 'New session' }}
      </button>
    </header>

    <div class="t-session-strip" role="tablist" aria-label="Chat sessions">
      <button
        v-for="session in sessions"
        :key="session.id"
        class="t-session-chip"
        :class="{ 't-session-chip-active': session.id === activeSessionId }"
        type="button"
        role="tab"
        :aria-selected="session.id === activeSessionId"
        @click="emit('selectSession', session.id)"
      >
        <span class="t-session-chip-title">{{ session.title }}</span>
        <span class="t-session-chip-meta">{{ new Date(session.updated_at).toLocaleDateString() }}</span>
      </button>
    </div>

    <p v-if="sessionError" class="t-inline-callout t-inline-callout-error t-session-callout">{{ sessionError }}</p>

    <div class="t-thread" role="log" aria-live="polite" aria-label="Conversation messages">
      <div class="t-thread-inner">
        <article v-if="isLoadingSessions || isLoadingHistory" class="t-turn t-turn-asst">
          <div class="t-asst-header">
            <div class="t-asst-mark" aria-hidden="true"></div>
            <span class="t-asst-name">Lumen</span>
          </div>
          <div class="pulse-line"></div>
          <div class="pulse-line short"></div>
        </article>

        <article v-else-if="messages.length === 0" class="t-turn t-turn-asst">
          <div class="t-asst-header">
            <div class="t-asst-mark" aria-hidden="true"></div>
            <span class="t-asst-name">Lumen</span>
            <span class="t-badge t-badge-partial">Waiting for your first question</span>
          </div>
          <p class="t-asst-text">
            Ask a question grounded in your uploaded documents and I’ll answer with the strongest evidence
            available from the ready set.
          </p>
        </article>

        <article
          v-for="message in messages"
          v-else
          :key="message.id"
          class="t-turn"
          :class="message.role === 'user' ? 't-turn-user' : 't-turn-asst'"
        >
          <div v-if="message.role === 'user'" class="t-user-bubble">
            <p class="t-user-text">{{ message.content }}</p>
          </div>

          <template v-else>
            <div class="t-asst-header">
              <div class="t-asst-mark" aria-hidden="true"></div>
              <span class="t-asst-name">Lumen</span>
              <span
                class="t-badge"
                :class="evidenceTone(message) === 'strong' ? 't-badge-strong' : 't-badge-partial'"
              >
                {{ evidenceLabel(message) }}
              </span>
            </div>

            <p class="t-asst-text">{{ message.content }}</p>
            <CitationList :citations="citationList(message)" />
          </template>
        </article>
      </div>
    </div>

    <div class="t-composer-wrap">
      <form class="t-composer" @submit.prevent="submit">
        <textarea
          id="chat-message"
          v-model="draft"
          class="t-composer-field"
          rows="2"
          placeholder="Ask a question grounded in your documents..."
          :disabled="isSending || readyCount === 0 || activeSessionId === null"
        ></textarea>

        <p v-if="sendError" class="t-inline-callout t-inline-callout-error t-composer-callout">{{ sendError }}</p>

        <div class="t-composer-footer">
          <span class="t-composer-ctx">{{ activeContextLabel }}</span>

          <button class="t-send" type="submit" :disabled="!canSend">
            <svg viewBox="0 0 20 20" class="t-icon-send" aria-hidden="true">
              <path
                d="m4 10 11.2-4.4c.5-.2 1 .3.8.8L11.6 17c-.2.5-.9.5-1.1 0L8.9 12 4 10Z"
                fill="none"
                stroke="currentColor"
                stroke-linejoin="round"
                stroke-width="1.5"
              />
              <path d="m8.8 12 6.4-6.4" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="1.5" />
            </svg>
            {{ isSending ? 'Asking...' : 'Ask Lumen' }}
          </button>
        </div>

        <p v-if="readyCount === 0" class="t-composer-blocked">
          Upload and finish indexing at least one document to start a grounded conversation.
        </p>
        <p v-else-if="pendingCount > 0" class="t-composer-blocked">
          Some files are still indexing, so answers will use the ready documents for now.
        </p>
      </form>
    </div>
  </section>
</template>
