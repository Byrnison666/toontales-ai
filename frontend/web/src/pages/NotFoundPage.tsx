import { useNavigate } from 'react-router-dom'
import { ErrorState } from '../components/ErrorState'
import { PageTransition } from '../components/PageTransition'

export function NotFoundPage(): JSX.Element {
  const navigate = useNavigate()
  return (
    <PageTransition className="mx-auto grid min-h-[70vh] max-w-7xl place-items-center px-4 py-12 sm:px-6 lg:px-8">
      <ErrorState
        title="Эта страница улетела за звёздами"
        message="Похоже, здесь нет ни одной сцены. Вернёмся туда, где истории только начинаются."
        actionLabel="На главную"
        onAction={() => navigate('/')}
      />
    </PageTransition>
  )
}
