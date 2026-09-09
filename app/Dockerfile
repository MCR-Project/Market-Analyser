# Multi-stage: `dev` runs the Vite dev server with HMR against a bind-mounted
# app/ (see docker-compose.yml, and the node_modules named volume it layers
# over the mount — a host-installed node_modules carries Windows-native
# esbuild/rollup binaries that do not run in this Linux image). `prod` builds
# static assets and serves them from nginx.
FROM node:22-slim AS base
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ── dev ──────────────────────────────────────────────────────────────
FROM base AS dev
COPY . .
EXPOSE 5173
# --host so Vite binds 0.0.0.0: it defaults to loopback-only, which is
# unreachable from outside the container.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ── build ────────────────────────────────────────────────────────────
# VITE_API_BASE is inlined into the JS bundle at build time (see
# src/utils/api.js), not read at container start - it has to be a build ARG,
# not an environment variable on the prod stage below. Defaulted to match
# api.js's own fallback so an image built with no --build-arg still points
# somewhere sane instead of baking in an empty string.
FROM base AS build
ARG VITE_API_BASE=http://localhost:8000/api
ENV VITE_API_BASE=$VITE_API_BASE
COPY . .
RUN npm run build

# ── prod ─────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
