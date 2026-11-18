# 训练：在显卡上做强化学习（mjlab、MuJoCo Warp、PyTorch）。
# 做镜像的位置是仓库的最上层：docker compose build train
# 版本都在 train/uv.lock 里写死（每个文件都有 SHA-256）；--locked：锁和 pyproject.toml 对不上就不装。
FROM python:3.13.18-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/train:/body \
    # 不往外发训练记录（wandb 默认会连它的网站）。记录写在 results 里，用 TensorBoard 看。
    WANDB_MODE=disabled \
    MPLBACKEND=Agg

RUN pip install --no-cache-dir --root-user-action=ignore uv==0.13.7

WORKDIR /train
COPY train/pyproject.toml train/uv.lock ./
RUN uv sync --locked --no-cache

# 训练不画图：mjlab 默认用 EGL 画图（MUJOCO_GL=egl），这个容器里没有 EGL，一 import mujoco 就出错。
# 容器里也没有 git：训练的库想把代码的 git 状态记进训练记录，找不到 git 就跳过（不报错）。
# 用的是哪一版代码，策略的规约里写着（mjlab 的提交号）。
ENV MUJOCO_GL=disable \
    GIT_PYTHON_REFRESH=quiet

COPY train /train
# 身体的代码（生成 Nova 的模型）和规约。开发时会被挂上来的目录盖住；这里放一份，镜像自己也是完整的。
COPY body /body
COPY contracts /contracts

CMD ["python", "-m", "nova_train.gpu"]
