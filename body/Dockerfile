# 身体：设计计算（质量闭环）和模型生成。
# 做镜像的位置是仓库的最上层：docker compose build body
FROM python:3.13.18-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY body/requirements.txt body/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

COPY body /app
# 消息的规约。开发时会被挂上来的目录盖住；这里放一份，镜像自己也是完整的。
COPY contracts /contracts

CMD ["python", "-m", "nova_body.mass_report"]
