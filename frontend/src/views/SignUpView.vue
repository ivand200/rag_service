<script setup lang="ts">
import { SignUp, useAuth } from '@clerk/vue'
import { computed, watchEffect } from 'vue'
import { useRouter } from 'vue-router'

import { E2E_USER_LABEL, LOCAL_DEV_USER_LABEL, isClerkAuthMode, isE2EApp, isLocalAuthMode } from '../auth/e2e'

const HOME_PATH = '/'
const SIGN_UP_PATH = '/sign-up'
const AUTH_PATH = '/auth'

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
  <section class="auth-route" aria-label="Create account">
    <div v-if="isLocalAuthMode" class="route-shell">
      <div class="route-card" role="status" aria-live="polite">
        <p class="route-eyebrow">Authentication</p>
        <h1 class="route-title">Local auth mode is enabled.</h1>
        <p class="route-copy">
          Account creation is skipped locally and the workspace will open as {{ LOCAL_DEV_USER_LABEL }}.
        </p>
      </div>
    </div>

    <div v-else-if="isE2EApp" class="route-shell">
      <div class="route-card" role="status" aria-live="polite">
        <p class="route-eyebrow">Authentication</p>
        <h1 class="route-title">E2E sign-up route is ready.</h1>
        <p class="route-copy">
          The deterministic browser test user is signed in as {{ E2E_USER_LABEL }}.
        </p>
      </div>
    </div>

    <div v-else-if="!isReadyForAuthCard" class="route-shell">
      <div class="route-card" role="status" aria-live="polite">
        <p class="route-eyebrow">Authentication</p>
        <h1 class="route-title">Preparing account creation.</h1>
        <p class="route-copy">
          Clerk is checking the current session before we show the sign-up experience.
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
          <h1 class="auth-title">Create your workspace account.</h1>
          <p class="auth-lede">
            Sign up with Clerk to access the shared document library and keep your chat history private to your account.
          </p>
        </div>

        <div class="auth-points" aria-label="Workspace highlights">
          <article class="auth-point">
            <span class="auth-point-label">Shared corpus</span>
            <p class="auth-point-copy">Upload and browse the same research library every signed-in user can query.</p>
          </article>

          <article class="auth-point">
            <span class="auth-point-label">Private history</span>
            <p class="auth-point-copy">See only your own grounded chat exchanges after you sign in.</p>
          </article>

          <article class="auth-point">
            <span class="auth-point-label">Quick return</span>
            <p class="auth-point-copy">Already have an account? Clerk will send you back to the sign-in page.</p>
          </article>
        </div>
      </div>

      <div class="auth-form-shell">
        <div class="auth-form-card">
          <SignUp
            :fallback-redirect-url="HOME_PATH"
            :force-redirect-url="HOME_PATH"
            path="/sign-up"
            routing="path"
            :sign-in-url="AUTH_PATH"
          />
        </div>
      </div>
    </div>
  </section>
</template>
