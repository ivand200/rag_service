export const isE2EApp = import.meta.env.VITE_APP_ENV === 'e2e'
export const isLocalAuthMode = import.meta.env.VITE_AUTH_MODE === 'local'
export const isBypassAuthApp = isE2EApp || isLocalAuthMode
export const isClerkAuthMode = !isBypassAuthApp

export const E2E_ACCESS_TOKEN = 'e2e-user'
export const E2E_USER_LABEL = 'E2E Demo User'
export const LOCAL_DEV_USER_LABEL = 'Local Dev User'

export async function getE2EAccessToken() {
  return E2E_ACCESS_TOKEN
}
