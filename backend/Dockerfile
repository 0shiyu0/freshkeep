# 构建上下文是仓库根目录（需要同时拿到 backend/ 与 database/）
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# psycopg[binary] 自带二进制，无需 libpq-dev / gcc
# PIP_INDEX_URL 默认走清华镜像：实测同机默认源 6 分 33 秒，镜像约 25 秒。
# 海外构建可覆盖：docker compose build --build-arg PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --prefer-binary \
      --index-url "${PIP_INDEX_URL}" -r requirements.txt

COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini .
COPY backend/entrypoint.sh .
# 迁移要读取 database/001_init.sql（DDL 的唯一真相），必须一起打进镜像
COPY database ./database

RUN chmod +x entrypoint.sh && mkdir -p /data

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).status==200 else 1)"

ENTRYPOINT ["./entrypoint.sh"]
