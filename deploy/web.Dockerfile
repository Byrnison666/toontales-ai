# Сборка SPA (frontend/web + frontend/admin) и упаковка в Caddy.
# Контекст сборки — корень репозитория (нужны frontend/* и deploy/Caddyfile).
FROM oven/bun:1 AS build-web
WORKDIR /app
COPY frontend/web/package.json frontend/web/bun.lock ./
RUN bun install --frozen-lockfile
COPY frontend/web/ ./
RUN bun run build

FROM oven/bun:1 AS build-admin
WORKDIR /app
COPY frontend/admin/package.json frontend/admin/bun.lock ./
RUN bun install --frozen-lockfile
COPY frontend/admin/ ./
RUN bun run build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build-web /app/dist /srv/web
COPY --from=build-admin /app/dist /srv/admin
