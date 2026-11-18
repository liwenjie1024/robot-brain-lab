"""看训练容器里显卡能不能用：PyTorch、Warp、MuJoCo Warp 都要认得它，并且 MuJoCo Warp 算的和 CPU 的 MuJoCo 一样。

用法：docker compose run --rm train python -m nova_train.gpu
"""

import sys
from dataclasses import dataclass

import mujoco
import mujoco_warp as mjw
import numpy as np
import torch
import warp as wp

# 一个方块从 0.5 m 高落到地上：显卡和 CPU 各算一遍，比最后的高度。
FALLING_BOX_XML = """
<mujoco>
  <option timestep="0.002"/>
  <worldbody>
    <geom type="plane" size="1 1 0.1"/>
    <body pos="0 0 0.5">
      <freejoint/>
      <geom type="box" size="0.05 0.05 0.05" mass="1"/>
    </body>
  </worldbody>
</mujoco>
"""
WORLDS = 64
STEPS = 500
# float32 的显卡和 float64 的 CPU 算 1 秒，高度差在这以内就算一样。
HEIGHT_TOLERANCE_M = 1e-3
BYTES_PER_GIB = 1024**3


@dataclass(frozen=True)
class GpuReport:
    torch_version: str
    torch_cuda: str
    device_name: str
    memory_gib: float
    warp_version: str
    mujoco_version: str
    mujoco_warp_version: str
    gpu_height_m: float
    cpu_height_m: float

    @property
    def same_physics(self) -> bool:
        return abs(self.gpu_height_m - self.cpu_height_m) <= HEIGHT_TOLERANCE_M


def box_height_on_cpu() -> float:
    model = mujoco.MjModel.from_xml_string(FALLING_BOX_XML)
    data = mujoco.MjData(model)
    for _ in range(STEPS):
        mujoco.mj_step(model, data)
    return float(data.qpos[2])


def box_heights_on_gpu() -> np.ndarray:
    model = mujoco.MjModel.from_xml_string(FALLING_BOX_XML)
    data = mujoco.MjData(model)
    gpu_model = mjw.put_model(model)
    gpu_data = mjw.put_data(model, data, nworld=WORLDS)
    for _ in range(STEPS):
        mjw.step(gpu_model, gpu_data)
    wp.synchronize()
    return gpu_data.qpos.numpy()[:, 2]


def check() -> GpuReport:
    if not torch.cuda.is_available():
        raise SystemExit("PyTorch 找不到显卡。看 compose.yaml 的 train 有没有 deploy.resources 里的 gpu。")
    wp.init()
    heights = box_heights_on_gpu()
    if not np.allclose(heights, heights[0]):
        raise SystemExit(f"{WORLDS} 个一样的世界算出来不一样：{heights.min():.6f}~{heights.max():.6f} m")
    properties = torch.cuda.get_device_properties(0)
    return GpuReport(
        torch_version=torch.__version__,
        torch_cuda=str(torch.version.cuda),
        device_name=properties.name,
        memory_gib=properties.total_memory / BYTES_PER_GIB,
        warp_version=wp.config.version,
        mujoco_version=mujoco.__version__,
        mujoco_warp_version=mjw.__version__ if hasattr(mjw, "__version__") else "?",
        gpu_height_m=float(heights[0]),
        cpu_height_m=box_height_on_cpu(),
    )


def main() -> None:
    report = check()
    print(f"显卡：{report.device_name}，{report.memory_gib:.1f} GiB")
    print(f"PyTorch {report.torch_version}（CUDA {report.torch_cuda}）、Warp {report.warp_version}")
    print(f"MuJoCo {report.mujoco_version}、MuJoCo Warp {report.mujoco_warp_version}")
    print(f"方块落地（{WORLDS} 个世界、{STEPS} 步）：显卡 {report.gpu_height_m:.5f} m，CPU {report.cpu_height_m:.5f} m")
    if not report.same_physics:
        print("显卡和 CPU 算的不一样。")
        sys.exit(1)
    print("显卡能用，显卡和 CPU 算的一样。")


if __name__ == "__main__":
    main()
