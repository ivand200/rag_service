export const isE2EApp = import.meta.env.VITE_APP_ENV === 'e2e'

export const E2E_ACCESS_TOKEN = 'e2e-user'
export const E2E_USER_LABEL = 'E2E Demo User'

export async function getE2EAccessToken() {
  return E2E_ACCESS_TOKEN
}
