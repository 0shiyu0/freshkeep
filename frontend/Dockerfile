# 两阶段：node 构建 → nginx 托管静态 + 反代 /api
FROM node:22-alpine AS build
WORKDIR /app

# 国内直连 registry.npmjs.org 容易 ECONNRESET（容器内无代理），默认走镜像；
# 海外构建可覆盖：docker compose build --build-arg NPM_REGISTRY=https://registry.npmjs.org
ARG NPM_REGISTRY=https://registry.npmmirror.com
RUN npm config set registry "$NPM_REGISTRY" && npm config set fund false && npm config set audit false

# 用 npm install 而非 npm ci：lockfile 在 macOS 上生成，缺少 linux-musl 的 rollup 可选依赖，
# npm ci 会因平台不一致失败；npm install 会补装当前平台的 optional deps。
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm install --no-audit --no-fund; else npm install --no-audit --no-fund; fi

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
