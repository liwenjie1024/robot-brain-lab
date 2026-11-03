# 몸(시뮬레이터). Windows의 스마트 앱 컨트롤이 서명 없는 mujoco.dll을 막아 Linux 컨테이너에서 돌린다.
# 빌드 위치는 저장소 맨 위다 (contracts도 함께 넣는다): docker compose build sim
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONTRACTS_DIR=/contracts \
    PYTHONPATH=/app

WORKDIR /app
COPY sim/requirements.txt sim/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

COPY contracts /contracts
COPY sim /app

EXPOSE 8765
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=2)"
CMD ["python", "-m", "robot_sim"]
