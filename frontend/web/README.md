# ToonTales Web

Пользовательское SPA для создания коротких мультфильмов. Приложение независимо от `frontend/admin` и общается с FastAPI через Vite proxy.

## Запуск

Требования: Bun и backend на `http://localhost:8000`.

```bash
bun install
bun run dev
```

Приложение откроется на `http://localhost:5174`. Запросы `/api` и WebSocket-соединения `/ws` проксируются на backend.

## Проверки и production-сборка

```bash
bun test
bun run build
bun run preview
```

Собранные файлы создаются в `dist/`.
