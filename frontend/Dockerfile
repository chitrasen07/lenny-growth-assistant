# --- build -------------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

# Lockfile-first so the dependency layer caches independently of source changes.
COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# Baked in at build time by Vite. Empty => same-origin /api/*, proxied by nginx.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# --- serve -------------------------------------------------------------------
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

# 127.0.0.1, not localhost: inside the container localhost resolves to ::1 first, and
# nginx's `listen 80` binds IPv4 only, so the check would fail against a healthy server.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
