<script setup lang="ts">
import { computed, ref } from 'vue'

import type { DocumentSummary } from '../types/workspace'

type StatusKey = 'ready' | 'processing' | 'pending' | 'failed'

const props = defineProps<{
  documents: DocumentSummary[]
  isLoading: boolean
  isUploading: boolean
  uploadError: string
  uploadSuccess: string
}>()

const emit = defineEmits<{
  upload: [file: File]
  refresh: []
}>()

const fileInput = ref<HTMLInputElement | null>(null)
const expandedDocumentId = ref<number | null>(null)

const statusConfig: Record<
  StatusKey,
  {
    label: string
    textColor: string
    bgColor: string
    borderColor: string
  }
> = {
  ready: {
    label: 'Ready',
    textColor: '#2a5c3f',
    bgColor: '#eaf4ee',
    borderColor: '#afd9be'
  },
  processing: {
    label: 'Indexing',
    textColor: '#7a5318',
    bgColor: '#fef6e4',
    borderColor: '#ecd48a'
  },
  pending: {
    label: 'Queued',
    textColor: '#5a5450',
    bgColor: '#f2f0ec',
    borderColor: '#d4cfc8'
  },
  failed: {
    label: 'Failed',
    textColor: '#8a2828',
    bgColor: '#fdf0f0',
    borderColor: '#f0b8b8'
  }
}

const sortedDocuments = computed(() =>
  [...props.documents].sort(
    (left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime()
  )
)

function openFilePicker() {
  if (!props.isUploading) {
    fileInput.value?.click()
  }
}

function onUploadZoneKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    openFilePicker()
  }
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const [file] = input.files ?? []

  if (file) {
    emit('upload', file)
  }

  input.value = ''
}

function toStatusKey(status: string): StatusKey {
  if (status === 'ready' || status === 'processing' || status === 'failed') {
    return status
  }

  return 'pending'
}

function statusFor(document: DocumentSummary) {
  return statusConfig[toStatusKey(document.status)]
}

function toggleDocument(documentId: number) {
  expandedDocumentId.value = expandedDocumentId.value === documentId ? null : documentId
}

function formatRelativeAge(value: string) {
  const timestamp = new Date(value).getTime()
  const elapsedMinutes = Math.max(0, Math.round((Date.now() - timestamp) / 60000))

  if (elapsedMinutes < 1) {
    return 'just now'
  }

  if (elapsedMinutes < 60) {
    return `${elapsedMinutes}m ago`
  }

  const elapsedHours = Math.round(elapsedMinutes / 60)
  if (elapsedHours < 24) {
    return `${elapsedHours}h ago`
  }

  const elapsedDays = Math.round(elapsedHours / 24)
  return `${elapsedDays}d ago`
}

function formatTimestamp(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit'
  }).format(new Date(value))
}
</script>

<template>
  <aside class="t-rail" aria-label="Document library">
    <div class="t-rail-head">
      <span class="t-rail-title">Documents</span>
      <button
        class="t-rail-add"
        type="button"
        aria-label="Upload a document"
        :disabled="isUploading"
        @click="openFilePicker"
      >
        <svg viewBox="0 0 20 20" class="t-icon-plus" aria-hidden="true">
          <path d="M10 4.5v11M4.5 10h11" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="1.8" />
        </svg>
      </button>
    </div>

    <input
      ref="fileInput"
      class="sr-only"
      type="file"
      accept=".txt,.md,.pdf,text/plain,text/markdown,application/pdf"
      @change="onFileChange"
    />

    <div
      class="t-upload"
      role="button"
      tabindex="0"
      :aria-disabled="isUploading"
      aria-label="Drag files here or click to upload"
      @click="openFilePicker"
      @keydown="onUploadZoneKeydown"
    >
      <div class="t-upload-icon" aria-hidden="true">
        <svg viewBox="0 0 20 20" class="t-icon-plus">
          <path d="M10 4.5v11M4.5 10h11" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="1.8" />
        </svg>
      </div>
      <div>
        <div class="t-upload-label">{{ isUploading ? 'Uploading...' : 'Add files' }}</div>
        <div class="t-upload-hint">.pdf · .md · .txt</div>
      </div>
    </div>

    <p v-if="uploadError" class="t-inline-callout t-inline-callout-error">{{ uploadError }}</p>
    <p v-else-if="uploadSuccess" class="t-inline-callout t-inline-callout-success">{{ uploadSuccess }}</p>

    <div v-if="isLoading" class="t-empty-state" aria-live="polite">
      <div class="pulse-line"></div>
      <div class="pulse-line short"></div>
      <div class="pulse-line"></div>
    </div>

    <ul v-else-if="sortedDocuments.length > 0" class="t-doc-list" role="list">
      <li v-for="document in sortedDocuments" :key="document.id" class="t-doc-item">
        <button
          class="t-doc-btn"
          type="button"
          :aria-expanded="expandedDocumentId === document.id"
          :aria-controls="`doc-detail-${document.id}`"
          @click="toggleDocument(document.id)"
        >
          <div
            class="t-doc-swatch"
            :style="{
              background: statusFor(document).bgColor,
              borderColor: statusFor(document).borderColor,
              color: statusFor(document).textColor
            }"
            aria-hidden="true"
          >
            <svg viewBox="0 0 20 20" class="t-icon-file">
              <path
                d="M6 2.75h5.5L15.25 6.5V16a1.25 1.25 0 0 1-1.25 1.25h-8A1.25 1.25 0 0 1 4.75 16V4A1.25 1.25 0 0 1 6 2.75Z"
                fill="none"
                stroke="currentColor"
                stroke-linejoin="round"
                stroke-width="1.5"
              />
              <path d="M11.5 2.75V6.5h3.75" fill="none" stroke="currentColor" stroke-linejoin="round" stroke-width="1.5" />
            </svg>
          </div>

          <div class="t-doc-info">
            <span class="t-doc-name">{{ document.filename }}</span>
            <div class="t-doc-meta">
              <span
                class="t-status-tag"
                :style="{
                  color: statusFor(document).textColor,
                  background: statusFor(document).bgColor,
                  borderColor: statusFor(document).borderColor
                }"
              >
                <svg
                  v-if="document.status === 'processing'"
                  viewBox="0 0 20 20"
                  class="t-icon-spinner t-spin"
                  aria-hidden="true"
                >
                  <path
                    d="M10 3.25A6.75 6.75 0 1 0 16.75 10"
                    fill="none"
                    stroke="currentColor"
                    stroke-linecap="round"
                    stroke-width="1.8"
                  />
                </svg>
                {{ statusFor(document).label }}
              </span>
              <span class="t-doc-age">{{ formatRelativeAge(document.updated_at) }}</span>
            </div>
          </div>

          <svg
            viewBox="0 0 20 20"
            class="t-doc-chevron"
            :class="{ 't-doc-chevron-open': expandedDocumentId === document.id }"
            aria-hidden="true"
          >
            <path d="m6 8 4 4 4-4" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.7" />
          </svg>
        </button>

        <div
          v-if="expandedDocumentId === document.id"
          :id="`doc-detail-${document.id}`"
          class="t-doc-detail"
        >
          <dl class="t-detail-grid">
            <dt>Type</dt>
            <dd>{{ document.content_type ?? 'Unknown' }}</dd>
            <dt>Added</dt>
            <dd>{{ formatTimestamp(document.created_at) }}</dd>
            <dt>Updated</dt>
            <dd>{{ formatTimestamp(document.updated_at) }}</dd>
            <dt>Status</dt>
            <dd :style="{ color: statusFor(document).textColor, fontWeight: '600' }">
              {{ statusFor(document).label }}
            </dd>
          </dl>

          <p v-if="document.error_summary" class="t-detail-note">{{ document.error_summary }}</p>

          <button
            v-if="document.status === 'failed'"
            class="t-retry"
            type="button"
            @click.stop="emit('refresh')"
          >
            <svg viewBox="0 0 20 20" class="t-icon-retry" aria-hidden="true">
              <path
                d="M15.4 7.4V4.6h-2.8M4.6 12.6v2.8h2.8M14.8 5.2A6.5 6.5 0 0 0 4.8 8.1M5.2 14.8a6.5 6.5 0 0 0 10-2.9"
                fill="none"
                stroke="currentColor"
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="1.6"
              />
            </svg>
            Refresh status
          </button>
        </div>
      </li>
    </ul>

    <div v-else class="t-empty-state">
      <p class="t-empty-title">No documents yet</p>
      <p class="t-empty-copy">Add a `.pdf`, `.md`, or `.txt` file to start grounding answers.</p>
    </div>
  </aside>
</template>
