<script setup lang="ts">
import { useAuth, useUser } from '@clerk/vue'
import { computed, watchEffect } from 'vue'
import { useRouter } from 'vue-router'

import {
  E2E_USER_LABEL,
  LOCAL_DEV_USER_LABEL,
  getE2EAccessToken,
  isClerkAuthMode,
  isE2EApp,
  isLocalAuthMode
} from '../auth/e2e'
import WorkspaceView from './WorkspaceView.vue'

const AUTH_PATH = '/auth'

const router = useRouter()
const clerkAuth = isClerkAuthMode ? useAuth() : null
const clerkUser = isClerkAuthMode ? useUser() : null

const isLoaded = computed(() =>
  isLocalAuthMode || isE2EApp ? true : clerkAuth?.isLoaded.value === true
)
const isSignedIn = computed(() =>
  isLocalAuthMode || isE2EApp ? true : clerkAuth?.isSignedIn.value === true
)

async function getAccessToken() {
  if (isE2EApp) {
    return getE2EAccessToken()
  }

  if (isLocalAuthMode) {
    return null
  }

  return clerkAuth?.getToken.value() ?? null
}

const userLabel = computed(() => {
  if (isLocalAuthMode) {
    return LOCAL_DEV_USER_LABEL
  }

  if (isE2EApp) {
    return E2E_USER_LABEL
  }

  const fullName = clerkUser?.user.value?.fullName?.trim()
  if (fullName) {
    return fullName
  }

  const primaryEmail = clerkUser?.user.value?.primaryEmailAddress?.emailAddress?.trim()
  if (primaryEmail) {
    return primaryEmail
  }

  return 'Signed-in user'
})

watchEffect(() => {
  if (isClerkAuthMode && isLoaded.value && !isSignedIn.value) {
    void router.replace(AUTH_PATH)
  }
})
</script>

<template>
  <div v-if="!isLoaded || !isSignedIn" class="route-shell">
    <div class="route-card" role="status" aria-live="polite">
      <p class="route-eyebrow">Workspace</p>
      <h1 class="route-title">Checking your Clerk session.</h1>
      <p class="route-copy">
        We only show the workspace after Clerk confirms the current browser session.
      </p>
      <div class="route-status">
        <span class="route-spinner" aria-hidden="true"></span>
        <span>Loading workspace route…</span>
      </div>
    </div>
  </div>

  <WorkspaceView v-else :user-label="userLabel" :get-access-token="getAccessToken" />
</template>
