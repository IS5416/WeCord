import { create } from 'zustand'
import {
  checkAuthStatus,
  login as apiLogin,
  register as apiRegister,
  logout as apiLogout,
  getCurrentUser,
  setAuthToken,
  clearAuthToken,
  getAuthToken,
  setOnUnauthorized,
  type AuthUser,
} from '@/api'
import { isNetworkError } from '@/lib/errors'
import i18n from '@/i18n'

export type AuthState = 'loading' | 'unauthenticated' | 'no-user' | 'authenticated' | 'network-error'

interface AuthStore {
  // State
  state: AuthState
  user: AuthUser | null
  error: string | null
  shouldRedirectToRoot: boolean

  // Actions
  initialize: () => Promise<void>
  login: (identifier: string, password: string) => Promise<void>
  register: (username: string, nickname: string, email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  handleUnauthorized: () => void
  consumeRootRedirect: () => void
  retry: () => void
  clearError: () => void
  setUser: (user: AuthUser) => void
}

export const useAuthStore = create<AuthStore>((set, get) => {
  // Set up unauthorized callback
  setOnUnauthorized(() => {
    get().handleUnauthorized()
  })

  return {
    state: 'loading',
    user: null,
    error: null,
    shouldRedirectToRoot: false,

    initialize: async () => {
      // Helper: try checkAuthStatus with retry (ngrok interstitial workaround)
      const check = async (retries = 2): Promise<{ exists: boolean; publicRead: boolean }> => {
        for (let i = 0; i < retries; i++) {
          try {
            return await checkAuthStatus()
          } catch {
            if (i < retries - 1) await new Promise(r => setTimeout(r, 1500))
            else throw new Error('auth status check failed')
          }
        }
        throw new Error('unreachable')
      }
      try {
        const { exists, publicRead } = await check()

        // Public-read mode: skip authentication entirely
        if (publicRead) {
          set({
            state: 'authenticated',
            user: { username: 'reader', nickname: 'Public Reader', email: '', avatarUrl: '' },
          })
          return
        }

        if (!exists) {
          // No user registered, show register page
          set({ state: 'no-user', user: null })
          return
        }

        // User exists, check if we have a valid token
        const token = getAuthToken()
        if (!token) {
          set({ state: 'unauthenticated', user: null })
          return
        }

        // Try to get current user with existing token
        try {
          const user = await getCurrentUser()
          set({ state: 'authenticated', user })
        } catch (innerErr) {
          if (isNetworkError(innerErr)) {
            set({ state: 'network-error', user: null })
            return
          }
          get().handleUnauthorized()
        }
      } catch (err) {
        if (isNetworkError(err)) {
          set({ state: 'network-error', user: null })
          return
        }
        console.error('Failed to initialize auth:', err)
        set({ state: 'unauthenticated', user: null })
      }
    },

    login: async (identifier: string, password: string) => {
      set({ error: null })
      try {
        const response = await apiLogin(identifier, password)
        setAuthToken(response.token)
        set({ state: 'authenticated', user: response.user })
      } catch (err) {
        const message = isNetworkError(err)
          ? i18n.t('auth.network_error')
          : err instanceof Error ? err.message : 'Login failed'
        set({ error: message })
        throw err
      }
    },

    register: async (username: string, nickname: string, email: string, password: string) => {
      set({ error: null })
      try {
        const response = await apiRegister(username, nickname, email, password)
        setAuthToken(response.token)
        set({ state: 'authenticated', user: response.user })
      } catch (err) {
        const message = isNetworkError(err)
          ? i18n.t('auth.network_error')
          : err instanceof Error ? err.message : 'Registration failed'
        set({ error: message })
        throw err
      }
    },

    logout: async () => {
      try {
        await apiLogout()
      } catch {
        // Ignore errors, still clear local state
      }
      clearAuthToken()
      set({ state: 'unauthenticated', user: null, shouldRedirectToRoot: true })
    },

    handleUnauthorized: () => {
      clearAuthToken()
      set({ state: 'unauthenticated', user: null, error: null, shouldRedirectToRoot: true })
    },

    consumeRootRedirect: () => {
      set({ shouldRedirectToRoot: false })
    },

    retry: () => {
      set({ state: 'loading', error: null })
    },

    clearError: () => {
      set({ error: null })
    },

    setUser: (user: AuthUser) => {
      set({ user })
    },
  }
})

// Actions that can be called from outside React
export const authActions = {
  initialize: () => useAuthStore.getState().initialize(),
  login: (identifier: string, password: string) => useAuthStore.getState().login(identifier, password),
  register: (username: string, nickname: string, email: string, password: string) =>
    useAuthStore.getState().register(username, nickname, email, password),
  logout: () => useAuthStore.getState().logout(),
  retry: () => useAuthStore.getState().retry(),
  setUser: (user: AuthUser) => useAuthStore.getState().setUser(user),
}