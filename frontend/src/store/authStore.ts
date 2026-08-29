import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface AuthUser {
  id: number
  full_name: string
  balance: number
  role: string
}

interface AuthState {
  accessToken: string | null
  user: AuthUser | null
  login: (token: string, user: AuthUser) => void
  updateBalance: (balance: number) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      user: null,
      login: (accessToken, user) => set({ accessToken, user }),
      updateBalance: (balance) =>
        set((state) => ({ user: state.user ? { ...state.user, balance } : state.user })),
      logout: () => set({ accessToken: null, user: null }),
    }),
    { name: 'moneymove-auth' }
  )
)
