# 身体：设计计算（质量闭环）和模型生成；测试台；实时分区（C++）的脊髓层。
# 做镜像的位置是仓库的最上层：docker compose build body

# 第一段：编译实时分区（C++，rt/），做成给测试台用的模块。也是 C++ 测试的环境（docker compose run --rm rt）。
# 编译工具从 Debian 13 的软件源装，版本写死。
FROM python:3.13.18-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS rt-build

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        g++-14=14.2.0-19 \
        cmake=3.31.6-2 \
        ninja-build=1.12.1-1 \
        libeigen3-dev=3.4.0-5 \
        libgtest-dev=1.16.0-1 \
    && rm -rf /var/lib/apt/lists/*

ENV CXX=g++-14 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

COPY rt/requirements-build.txt /tmp/requirements-build.txt
RUN pip install --no-cache-dir -r /tmp/requirements-build.txt
COPY rt /rt
RUN pip wheel --no-cache-dir --no-build-isolation --no-deps --wheel-dir /wheels /rt

# 第二段：身体和测试台（不带编译工具）。
FROM python:3.13.18-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY body/requirements.txt body/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

# 脊髓层（C++）的模块。改了 rt/ 里的代码要重新做镜像：docker compose build body
COPY --from=rt-build /wheels /wheels
RUN pip install --no-cache-dir --no-deps /wheels/*.whl

COPY body /app
# 消息的规约。开发时会被挂上来的目录盖住；这里放一份，镜像自己也是完整的。
COPY contracts /contracts

CMD ["python", "-m", "nova_body.mass_report"]
