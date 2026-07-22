# Сборка пользовательского SPA (frontend/web) и упаковка в Caddy.
# Контекст сборки — корень репозитория (нужны frontend/web и deploy/Caddyfile).
FROM oven/bun:1 AS build
WORKDIR /app
COPY frontend/web/package.json frontend/web/bun.lock ./
RUN bun install --frozen-lockfile
COPY frontend/web/ ./
RUN bun run build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv/web
