<script setup lang="ts">
import { UserButton } from '@clerk/vue'

import { isE2EApp } from '../auth/e2e'

defineProps<{
  readyCount: number
  processingCount: number
  failedCount: number
  userLabel: string
}>()
</script>

<template>
  <header class="t-header" aria-label="Workspace header">
    <div class="t-header-left">
      <div class="t-logo" aria-hidden="true">
        <svg viewBox="0 0 24 24" class="t-icon-leaf">
          <path
            d="M15.6 4.2c-3.7 0-7 2.1-8.7 5.2-.9 1.7-1.3 3.5-1.2 5.4.1.7.7 1.1 1.3.9 1.8-.5 3.5-1.5 4.8-3 1.2-1.4 2-3.2 2.2-5.1-.8 2.8-2.7 5.2-5.1 6.6 1.9-.4 3.7-1.3 5.1-2.8 1.9-2 2.9-4.7 2.8-7.2-.1 0-.7 0-1.2 0z"
            fill="currentColor"
          />
        </svg>
      </div>
      <span class="t-brand">Lumen</span>
      <div class="t-header-divider" aria-hidden="true"></div>
      <span class="t-workspace">Research Workspace</span>
    </div>

    <div class="t-header-right">
      <div class="t-doc-summary" aria-label="Document status summary">
        <span class="t-dot t-dot-green" aria-hidden="true"></span>
        <span class="t-summary-text">{{ readyCount }} ready</span>

        <template v-if="processingCount > 0">
          <span class="t-dot t-dot-amber" aria-hidden="true"></span>
          <span class="t-summary-text">{{ processingCount }} indexing</span>
        </template>

        <template v-if="failedCount > 0">
          <span class="t-dot t-dot-red" aria-hidden="true"></span>
          <span class="t-summary-text t-summary-text-warn">{{ failedCount }} failed</span>
        </template>
      </div>

      <div class="t-auth-summary" aria-label="Signed-in user">
        <div class="t-auth-copy">
          <span class="t-auth-label">Signed in</span>
          <span class="t-auth-user">{{ userLabel }}</span>
        </div>

        <UserButton
          v-if="!isE2EApp"
          after-sign-out-url="/auth"
          :appearance="{
            elements: {
              avatarBox: 't-user-button-avatar'
            }
          }"
        />
        <div v-else class="t-user-button-avatar" aria-hidden="true">E2E</div>
      </div>
    </div>
  </header>
</template>
