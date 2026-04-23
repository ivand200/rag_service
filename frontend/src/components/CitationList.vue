<script setup lang="ts">
import type { Citation } from '../types/workspace'

defineProps<{
  citations: Citation[]
}>()
</script>

<template>
  <section v-if="citations.length > 0" class="t-cites" aria-label="Source citations">
    <div class="t-cites-label">Sources</div>

    <div
      v-for="(citation, index) in citations"
      :key="`${citation.document_id}-${citation.chunk_id}-${index}`"
      class="t-cite"
    >
      <div class="t-cite-left" aria-hidden="true">
        <span class="t-cite-num">{{ index + 1 }}</span>
        <span v-if="index < citations.length - 1" class="t-cite-thread"></span>
      </div>

      <div class="t-cite-body">
        <div class="t-cite-source">
          <svg viewBox="0 0 20 20" class="t-icon-file" aria-hidden="true">
            <path
              d="M6 2.75h5.5L15.25 6.5V16a1.25 1.25 0 0 1-1.25 1.25h-8A1.25 1.25 0 0 1 4.75 16V4A1.25 1.25 0 0 1 6 2.75Z"
              fill="none"
              stroke="currentColor"
              stroke-linejoin="round"
              stroke-width="1.5"
            />
            <path d="M11.5 2.75V6.5h3.75" fill="none" stroke="currentColor" stroke-linejoin="round" stroke-width="1.5" />
          </svg>
          <span class="t-cite-docname">{{ citation.document_name }}</span>
          <span class="t-cite-page">
            {{ citation.page_number !== null ? `p.${citation.page_number}` : citation.section_label ?? 'Snippet' }}
          </span>
          <span class="t-cite-open" aria-hidden="true">↗</span>
        </div>

        <blockquote class="t-cite-excerpt">{{ citation.snippet }}</blockquote>
      </div>
    </div>
  </section>
</template>
