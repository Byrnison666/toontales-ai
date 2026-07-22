import { createContext, useContext, useEffect, useMemo, useState, type PropsWithChildren } from 'react'
import { AUTH_EXPIRED_EVENT, type AuthResponse } from './api'
import { clearSession, getToken, setSession } from './storage'

interface AuthContextValue {
  isAuthenticated: boolean
  saveAuth: (auth: AuthResponse) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: PropsWithChildren): JSX.Element {
  const [isAuthenticated, setIsAuthenticated] = useState(() => Boolean(getToken()))

  useEffect(() => {
    const handleExpired = (): void => setIsAuthenticated(false)
    const handleStorage = (event: StorageEvent): void => {
      if (event.key === 'toontales_token') setIsAuthenticated(Boolean(event.newValue))
    }

    window.addEventListener(AUTH_EXPIRED_EVENT, handleExpired)
    window.addEventListener('storage', handleStorage)
    return () => {
      window.removeEventListener(AUTH_EXPIRED_EVENT, handleExpired)
      window.removeEventListener('storage', handleStorage)
    }
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      isAuthenticated,
      saveAuth: (auth) => {
        setSession(auth.access_token, auth.user_id)
        setIsAuthenticated(true)
      },
      logout: () => {
        clearSession()
        setIsAuthenticated(false)
      },
    }),
    [isAuthenticated],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}
