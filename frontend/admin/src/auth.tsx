import { createContext, useContext, useEffect, useMemo, useState, type PropsWithChildren } from 'react'
import {
  ADMIN_AUTH_INVALIDATED_EVENT,
  ADMIN_KEY_STORAGE_KEY,
  clearStoredAdminKey,
  getStoredAdminKey,
  storeAdminKey,
} from './api'

interface AuthContextValue {
  isAuthenticated: boolean
  login: (adminKey: string) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: PropsWithChildren): JSX.Element {
  const [adminKey, setAdminKey] = useState<string | null>(() => getStoredAdminKey())

  useEffect(() => {
    const handleInvalidation = () => setAdminKey(null)
    const handleStorage = (event: StorageEvent) => {
      if (event.key === ADMIN_KEY_STORAGE_KEY) {
        setAdminKey(event.newValue)
      }
    }

    window.addEventListener(ADMIN_AUTH_INVALIDATED_EVENT, handleInvalidation)
    window.addEventListener('storage', handleStorage)
    return () => {
      window.removeEventListener(ADMIN_AUTH_INVALIDATED_EVENT, handleInvalidation)
      window.removeEventListener('storage', handleStorage)
    }
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      isAuthenticated: adminKey !== null,
      login: (key: string) => {
        storeAdminKey(key)
        setAdminKey(key)
      },
      logout: () => {
        clearStoredAdminKey()
        setAdminKey(null)
      },
    }),
    [adminKey],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
