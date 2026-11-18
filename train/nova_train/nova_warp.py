"""Nova 的模型放进 MuJoCo Warp（显卡上的仿真）：跑不跑得起来、站不站得住、多快、占多少显存。

用法：docker compose run --rm train python -m nova_train.nova_warp
2.3 步练 Nova 以前要知道：哪些地方要改（训练用的简化模型），这块显卡一次能同时跑多少个 Nova。
每个 Nova 都从站姿开始，驱动器顶着站姿（和测试台一样），站 1 秒，和 CPU 上算的比骨盆的高度。
"""

import copy
import gc
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import mujoco
import mujoco_warp as mjw
import numpy as np
import warp as wp
from nova_body.bench import STAND_KEY
from nova_body.model import build_nova

WORLD_COUNTS = (256, 1024, 2048, 4096)
SECONDS = 1.0
# 接触、约束按 CPU 上站着时的这么多倍留（站着的时候最少；走起来、摔倒了会多）。
CONTACT_MARGIN = 4
# 显卡和 CPU 站 1 秒以后骨盆的高度差在这以内，就算一样站得住。
HEIGHT_TOLERANCE_M = 0.005
BYTES_PER_MIB = 1024**2
DEVICE = "cuda:0"
RESULT_PATH = Path("/results/nova_warp.json")


@dataclass(frozen=True)
class WarpRun:
    timestep_s: float
    worlds: int
    steps_per_second: float
    memory_mib: float
    pelvis_height_m: float
    cpu_pelvis_height_m: float
    finite: bool


def nova_model() -> mujoco.MjModel:
    return copy.copy(build_nova().body.model)


def standing_cpu(model: mujoco.MjModel, steps: int) -> tuple[mujoco.MjData, int, int, float]:
    """CPU 上从站姿站一会儿：回开始的状态、站着时最多有几个接触和几个约束、最后骨盆的高度。"""
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, STAND_KEY))
    mujoco.mj_forward(model, data)
    start = copy.copy(data)
    most_contacts, most_constraints = data.ncon, data.nefc
    for _ in range(steps):
        mujoco.mj_step(model, data)
        most_contacts, most_constraints = max(most_contacts, data.ncon), max(most_constraints, data.nefc)
    return start, most_contacts, most_constraints, float(data.qpos[2])


def run_on_gpu(model: mujoco.MjModel, worlds: int) -> WarpRun:
    steps = round(SECONDS / model.opt.timestep)
    start, contacts, constraints, cpu_height = standing_cpu(model, steps)
    # 量 Warp 自己记的显存用量：它会留着用过的显存给下一次，所以"显卡还剩多少"量不准。
    gc.collect()
    used_before = wp.get_mempool_used_mem_current(DEVICE)
    gpu_model = mjw.put_model(model)
    gpu_data = mjw.put_data(
        model,
        start,
        nworld=worlds,
        nconmax=CONTACT_MARGIN * max(contacts, 1),
        njmax=CONTACT_MARGIN * max(constraints, 1),
    )
    mjw.step(gpu_model, gpu_data)  # 第一次要编译显卡的程序，不算时间
    wp.synchronize()
    begin = time.perf_counter()
    for _ in range(steps - 1):
        mjw.step(gpu_model, gpu_data)
    wp.synchronize()
    elapsed = time.perf_counter() - begin
    memory = (wp.get_mempool_used_mem_current(DEVICE) - used_before) / BYTES_PER_MIB
    heights = gpu_data.qpos.numpy()[:, 2]
    return WarpRun(
        timestep_s=float(model.opt.timestep),
        worlds=worlds,
        steps_per_second=worlds * (steps - 1) / elapsed,
        memory_mib=memory,
        pelvis_height_m=float(np.median(heights)),
        cpu_pelvis_height_m=cpu_height,
        finite=bool(np.isfinite(gpu_data.qpos.numpy()).all()),
    )


def describe(model: mujoco.MjModel) -> dict[str, int]:
    return {
        "自由度": model.nv,
        "驱动器": model.nu,
        "形状": model.ngeom,
        "网格": model.nmesh,
        "肌腱": model.ntendon,
        "传感器": model.nsensor,
        "相机": model.ncam,
    }


def main() -> None:
    wp.config.quiet = True
    model = nova_model()
    print("Nova 的模型：" + "、".join(f"{name} {count}" for name, count in describe(model).items()))
    try:
        mjw.put_model(model)
    except NotImplementedError as error:
        print(f"MuJoCo Warp 不支持：{error}")
        raise SystemExit(1) from error
    runs = []
    for timestep in (model.opt.timestep, 0.005):
        model.opt.timestep = timestep
        for worlds in WORLD_COUNTS:
            try:
                run = run_on_gpu(model, worlds)
            except Exception as error:  # 显存不够等，记下来接着量别的
                print(f"步长 {timestep * 1000:g} 毫秒、{worlds} 个：{type(error).__name__}: {error}")
                break
            runs.append(run)
            same = abs(run.pelvis_height_m - run.cpu_pelvis_height_m) <= HEIGHT_TOLERANCE_M and run.finite
            print(
                f"步长 {timestep * 1000:g} 毫秒、{worlds} 个 Nova：每秒 {run.steps_per_second:,.0f} 步，"
                f"显存 {run.memory_mib:,.0f} MiB；站 1 秒后骨盆高 {run.pelvis_height_m:.3f} m"
                f"（CPU {run.cpu_pelvis_height_m:.3f} m，{'一样' if same else '不一样'}）"
            )
    RESULT_PATH.write_text(
        json.dumps({"model": describe(model), "runs": [asdict(run) for run in runs]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"写进了 {RESULT_PATH}")


if __name__ == "__main__":
    main()
