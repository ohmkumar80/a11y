FROM node:22-slim AS build
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json apps/web/
COPY packages/ui/package.json packages/ui/
RUN pnpm install --frozen-lockfile
COPY apps/web apps/web
COPY packages/ui packages/ui
# API_INTERNAL_URL is baked into the rewrite at build time; compose overrides it at runtime via
# the standalone server's env, and the default below matches the compose service name.
ARG API_INTERNAL_URL=http://api:8000
ENV API_INTERNAL_URL=$API_INTERNAL_URL
RUN pnpm --filter @a11y/web build

FROM node:22-slim
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static apps/web/.next/static
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
