# 两阶段：node 构建 → nginx 托管静态 + 反代 /api
# 构建：docker build -f frontend/Dockerfile -t freshkeep-web ./frontend
FROM node:22-alpine AS build
WORKDIR /app

# 国内直连 registry.npmjs.org 容易 ECONNRESET（容器内无代理），默认走镜像；
# 海外构建可覆盖：docker compose build --build-arg NPM_REGISTRY=https://registry.npmjs.org
ARG NPM_REGISTRY=https://registry.npmmirror.com
RUN npm config set registry "$NPM_REGISTRY" && npm config set fund false && npm config set audit false

# 依赖层单独 COPY：只改业务代码时复用 npm 缓存层，构建从 ~2 分钟降到秒级
# 用 npm install 而非 npm ci：lockfile 在 macOS 上生成，缺少 linux-musl 的 rollup 可选依赖，
# npm ci 会因平台不一致失败；npm install 会补装当前平台的 optional deps。
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY . .
# build 脚本含 vue-tsc --noEmit，类型错误会让镜像构建失败（这正是想要的）
RUN npm run build

FROM nginx:1.27-alpine

# HTTP 与 HTTPS 两套 server 块分别由 nginx.conf / nginx.https.conf 提供；
# HTTPS 场景用 docker-compose.https.yml 把 nginx.https.conf 覆盖到同一路径
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80 443
STOPSIGNAL SIGQUIT
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
