FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build
FROM nginx:1.28-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY network-entrypoint.sh /docker-entrypoint.d/40-campus-networks.sh
RUN chmod +x /docker-entrypoint.d/40-campus-networks.sh
