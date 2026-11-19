# The LeaveDesk web app, in two stages:
#   1. "build": Node compiles the Angular app into plain HTML, JS and CSS files.
#   2. the final image: nginx serves those files and forwards /api to the API.
# Node and node_modules stay in stage 1, so the final image is small (about 50 MB).

FROM node:24-alpine AS build
WORKDIR /app
ENV CI=true

# Dependencies first: Docker reuses this layer until package*.json change.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build


# nginx-unprivileged runs as a normal user (not root) and listens on 8080.
FROM nginxinc/nginx-unprivileged:stable-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/frontend/browser /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD wget -q --spider http://127.0.0.1:8080/healthz || exit 1
