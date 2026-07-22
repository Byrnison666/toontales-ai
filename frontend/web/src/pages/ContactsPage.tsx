import { LegalLayout } from '../components/LegalLayout'
import { requisites } from '../lib/legal'

export function ContactsPage(): JSX.Element {
  return (
    <LegalLayout title="Контакты и реквизиты" subtitle="Связаться с нами и официальные данные исполнителя.">
      <h2>Как с нами связаться</h2>
      <dl>
        <dt>Email</dt>
        <dd>
          <a href={`mailto:${requisites.email}`}>{requisites.email}</a>
        </dd>
        <dt>Телефон</dt>
        <dd>
          <a href={`tel:${requisites.phoneHref}`}>{requisites.phone}</a>
        </dd>
        <dt>Город</dt>
        <dd>{requisites.city}</dd>
      </dl>

      <h2>Реквизиты</h2>
      <dl>
        <dt>Исполнитель</dt>
        <dd>{requisites.fullName}</dd>
        <dt>Статус</dt>
        <dd>{requisites.taxStatus}</dd>
        <dt>ИНН</dt>
        <dd>{requisites.inn}</dd>
      </dl>

      <p>
        По вопросам оплаты, работы сервиса и возвратов пишите на{' '}
        <a href={`mailto:${requisites.email}`}>{requisites.email}</a> — отвечаем в рабочее время.
      </p>
    </LegalLayout>
  )
}
