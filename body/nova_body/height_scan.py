"""高度扫描（2.2 步起）：从骨盆往下打一片竖直的射线，量骨盆比脚下的地面高多少。和 mjlab 练楼梯时策略看的一样：

- 射线从骨盆那一点出发，网格只跟着骨盆转偏航（不跟着前后、左右歪），方向一直是竖直朝下；
- 网格 x × y（每 resolution 一个点，两头都有点），先 y 后 x 地排（mjlab 的 GridPatternCfg：
  `torch.meshgrid(x, y, indexing="xy")` 再拉平）；
- 只打地面：固定在世界上的形状，并且在给定的几组里（身体自己的形状在别的组），骨盆自己也不打；
- 打不到、或者比 max_distance 远，就当 max_distance。射线是竖直的，量到的高度就是射线的长度。

现在用仿真里的真数（以后换成胸前深度相机算的，2.5 步）。
"""

import math
from dataclasses import dataclass

import mujoco
import numpy as np

# MuJoCo 的形状一共分几组（mj_ray 的 geomgroup 每组一个开关）。
GEOM_GROUP_COUNT = 6
# 骨盆的前方快要竖直的时候（比如躺着），偏航改用左方算（和 mjlab 一样）。
YAW_FALLBACK_NORM = 0.1
DOWN = np.array([0.0, 0.0, -1.0])
NO_HIT = -1.0


@dataclass(frozen=True)
class HeightScanSpec:
    """高度扫描的样子：从哪个身体打、网格多大（m）、多密（m）、中心挪多少（m）、最远多远（m）、打哪几组形状。"""

    frame_body: str
    size_m: tuple[float, float]
    resolution_m: tuple[float, float]
    offset_m: tuple[float, float]
    max_distance_m: float
    geom_groups: tuple[int, ...]

    def __post_init__(self) -> None:
        if min(self.size_m) < 0 or min(self.resolution_m) <= 0:
            raise ValueError(f"网格的大小不能是负的，间隔要大于 0：{self.size_m}、{self.resolution_m}")
        if self.max_distance_m <= 0:
            raise ValueError(f"最远的距离要大于 0：{self.max_distance_m}")
        if not self.geom_groups or any(not 0 <= group < GEOM_GROUP_COUNT for group in self.geom_groups):
            raise ValueError(f"形状的组要是 0~{GEOM_GROUP_COUNT - 1}：{self.geom_groups}")

    def grid_m(self) -> np.ndarray:
        """网格上每一点在偏航坐标里的 (x, y)，先 y 后 x 地排。"""
        xs, ys = (
            np.arange(-size / 2, size / 2 + step / 2, step) + offset
            for size, step, offset in zip(self.size_m, self.resolution_m, self.offset_m, strict=True)
        )
        grid_x, grid_y = np.meshgrid(xs, ys, indexing="xy")
        return np.column_stack([grid_x.ravel(), grid_y.ravel()])

    @property
    def size(self) -> int:
        return len(self.grid_m())


def yaw_rotation(rotation: np.ndarray) -> np.ndarray:
    """只留下偏航的转动（绕竖轴）。前方快要竖直时用左方算偏航。"""
    forward = np.array([rotation[0, 0], rotation[1, 0]])
    if np.linalg.norm(forward) < YAW_FALLBACK_NORM:
        left = np.array([rotation[0, 1], rotation[1, 1]])
        forward = np.array([left[1], -left[0]])
    cos_yaw, sin_yaw = forward / max(np.linalg.norm(forward), 1e-6)
    return np.array([[cos_yaw, -sin_yaw, 0.0], [sin_yaw, cos_yaw, 0.0], [0.0, 0.0, 1.0]])


class HeightScanner:
    """在一个模型上照 HeightScanSpec 扫：每次 scan 回网格上每一点骨盆比地面高多少（m）。"""

    def __init__(self, model: mujoco.MjModel, spec: HeightScanSpec) -> None:
        self._model = model
        self._spec = spec
        self._frame = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, spec.frame_body)
        if self._frame < 0:
            raise ValueError(f"模型里没有高度扫描的身体 {spec.frame_body}")
        grid = spec.grid_m()
        self._offsets = np.column_stack([grid, np.zeros(len(grid))])
        self._geomgroup = np.array([group in spec.geom_groups for group in range(GEOM_GROUP_COUNT)], dtype=np.uint8)
        self._geom = np.zeros(1, dtype=np.int32)

    @property
    def spec(self) -> HeightScanSpec:
        return self._spec

    def scan(self, data: mujoco.MjData) -> np.ndarray:
        position = data.xpos[self._frame]
        origins = position + self._offsets @ yaw_rotation(data.xmat[self._frame].reshape(3, 3)).T
        heights = np.empty(len(origins))
        for index, origin in enumerate(origins):
            distance = mujoco.mj_ray(self._model, data, origin, DOWN, self._geomgroup, True, self._frame, self._geom)
            missed = distance == NO_HIT or math.isnan(distance) or distance > self._spec.max_distance_m
            heights[index] = self._spec.max_distance_m if missed else distance
        return heights
