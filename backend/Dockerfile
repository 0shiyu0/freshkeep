# 构建上下文是仓库根目录（需要同时拿到 backend/ 与 database/）
# 构建：docker build -f backend/Dockerfile -t freshkeep-api .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai \
    PORT=8000

WORKDIR /app

# 依赖层与代码层分离：只改业务代码时不会重装依赖
# psycopg[binary] 自带二进制，无需 libpq-dev / gcc
# PIP_INDEX_URL 默认走清华镜像（实测同机默认源 6 分 33 秒，镜像约 25 秒）
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --prefer-binary \
      --index-url "${PIP_INDEX_URL}" -r requirements.txt

COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini .
COPY backend/entrypoint.sh .
# 迁移要读取 database/001_init.sql（DDL 的唯一真相），必须一起打进镜像
COPY database ./database

# 运行期数据目录（compose 会用 bind mount 覆盖，这里保证镜像单独跑也能启动）
# 说明：容器以 root 运行是刻意的取舍 —— /data 是宿主 bind mount，
# 非 root 用户会遇到宿主目录属主不匹配导致写失败。若要加固：
#   1) 宿主执行 chown -R 1000:1000 storage backups pgdata
#   2) compose 里加 user: "1000:1000"
RUN chmod +x entrypoint.sh \
    && mkdir -p /data/logs /data/storage/uploads /data/storage/exports /data/backups

EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)"

ENTRYPOINT ["./entrypoint.sh"]
