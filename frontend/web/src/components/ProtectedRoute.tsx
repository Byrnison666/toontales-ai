import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../auth'

export function ProtectedRoute(): JSX.Element {
  const { isAuthenticated } = useAuth()
  const location = useLocation()

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return <Outlet />
}
