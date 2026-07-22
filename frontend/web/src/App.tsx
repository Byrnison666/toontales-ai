import { AnimatePresence } from 'framer-motion'
import { lazy, Suspense } from 'react'
import { Route, Routes, useLocation } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { MagicLoader } from './components/MagicLoader'
import { ProtectedRoute } from './components/ProtectedRoute'

const LandingPage = lazy(() => import('./pages/LandingPage').then((module) => ({ default: module.LandingPage })))
const AuthPage = lazy(() => import('./pages/AuthPage').then((module) => ({ default: module.AuthPage })))
const CreatePage = lazy(() => import('./pages/CreatePage').then((module) => ({ default: module.CreatePage })))
const RunPage = lazy(() => import('./pages/RunPage').then((module) => ({ default: module.RunPage })))
const GalleryPage = lazy(() => import('./pages/GalleryPage').then((module) => ({ default: module.GalleryPage })))
const NotFoundPage = lazy(() => import('./pages/NotFoundPage').then((module) => ({ default: module.NotFoundPage })))

export function App(): JSX.Element {
  const location = useLocation()

  return (
    <AppShell>
      <Suspense fallback={<MagicLoader label="Открываем страницу…" />}>
        <AnimatePresence mode="wait" initial={false}>
          <Routes location={location} key={location.pathname}>
            <Route path="/" element={<LandingPage />} />
            <Route path="/register" element={<AuthPage mode="register" />} />
            <Route path="/login" element={<AuthPage mode="login" />} />
            <Route element={<ProtectedRoute />}>
              <Route path="/create" element={<CreatePage />} />
              <Route path="/runs/:runId" element={<RunPage />} />
              <Route path="/gallery" element={<GalleryPage />} />
            </Route>
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </AnimatePresence>
      </Suspense>
    </AppShell>
  )
}
