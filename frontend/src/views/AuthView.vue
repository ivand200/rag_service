<script setup lang="ts">
import { SignIn, useAuth } from '@clerk/vue'
import { computed, watchEffect } from 'vue'
import { useRouter } from 'vue-router'

import { E2E_USER_LABEL, LOCAL_DEV_USER_LABEL, isClerkAuthMode, isE2EApp, isLocalAuthMode } from '../auth/e2e'

const HOME_PATH = '/'
const AUTH_PATH = '/auth'
const SIGN_UP_PATH = '/sign-up'

const router = useRouter()
const clerkAuth = isClerkAuthMode ? useAuth() : null

const isReadyForAuthCard = computed(() => {
  if (!isClerkAuthMode) {
    return false
  }

  return clerkAuth?.isLoaded.value === true && !clerkAuth.isSignedIn.value
})

watchEffect(() => {
  if (isLocalAuthMode) {
    void router.replace(HOME_PATH)
    return
  }

  if (isClerkAuthMode && clerkAuth?.isLoaded.value && clerkAuth.isSignedIn.value) {
    void router.replace(HOME_PATH)
  }
})
</script>

<template>
  <section class="auth-route" aria-label="Authentication">
    <div v-if="isLocalAuthMode" class="route-shell">
      <div class="route-card" role="status" aria-live="polite">
        <p class="route-eyebrow">Authentication</p>
        <h1 class="route-title">Local auth mode is enabled.</h1>
        <p class="route-copy">
          The workspace is available without Clerk and will open as {{ LOCAL_DEV_USER_LABEL }}.
        </p>
      </div>
    </div>

    <div v-else-if="isE2EApp" class="route-shell">
      <div class="route-card" role="status" aria-live="polite">
        <p class="route-eyebrow">Authentication</p>
        <h1 class="route-title">E2E sign-in route is ready.</h1>
        <p class="route-copy">
          The deterministic browser test user is signed in as {{ E2E_USER_LABEL }}.
        </p>
      </div>
    </div>

    <div v-else-if="!isReadyForAuthCard" class="route-shell">
      <div class="route-card" role="status" aria-live="polite">
        <p class="route-eyebrow">Authentication</p>
        <h1 class="route-title">Preparing your workspace access.</h1>
        <p class="route-copy">
          Clerk is checking the current session before we show the sign-in experience.
        </p>
        <div class="route-status">
          <span class="route-spinner" aria-hidden="true"></span>
          <span>Loading Clerk…</span>
        </div>
      </div>
    </div>

    <div v-else class="auth-card">
      <div class="auth-copy-panel">
        <div>
          <span class="auth-kicker">Lumen Workspace</span>
          <h1 class="auth-title">Sign in to the shared research desk.</h1>
          <p class="auth-lede">
            Continue with Clerk to open the document workspace, upload files, and demo the app with
            a real signed-in flow. New users can create an account directly from the auth form.
          </p>
        </div>

        <div class="auth-points" aria-label="Workspace highlights">
          <article class="auth-point">
            <span class="auth-point-label">Shared corpus</span>
            <p class="auth-point-copy">Browse the same document library every signed-in user can query.</p>
          </article>

          <article class="auth-point">
            <span class="auth-point-label">Grounded answers</span>
            <p class="auth-point-copy">Keep citations and abstention behavior front and center in demos.</p>
          </article>

          <article class="auth-point">
            <span class="auth-point-label">Clerk UI</span>
            <p class="auth-point-copy">Use the built-in sign-in and sign-up flow instead of custom auth chrome.</p>
          </article>
        </div>
      </div>

      <div class="auth-form-shell">
        <div class="auth-form-card">
          <SignIn
            :fallback-redirect-url="HOME_PATH"
            :force-redirect-url="HOME_PATH"
            :path="AUTH_PATH"
            routing="path"
            :sign-up-fallback-redirect-url="HOME_PATH"
            :sign-up-force-redirect-url="HOME_PATH"
            :sign-up-url="SIGN_UP_PATH"
          />
        </div>
      </div>
    </div>
  </section>
</template>
