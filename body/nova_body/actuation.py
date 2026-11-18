"""仿真里的驱动器（1.6 步）：每一步按转速和绕组的温度定每个驱动器能出多大的力，按它真的出了多大的力算它热了多少；
命令晚一步（1 毫秒，脊髓层经总线发过去）才到驱动器。

模型里的驱动器是"位置 + 阻尼"（代表驱动器里自己跑的阻抗环）。力的上下限每一步改一次：往转的方向推受电压限，
绕组热了两个方向都降额（drives.DriveSpec 的规则，这里一次算全部的驱动器）。
没有驱动器模型的身体（基线：文件里没有这些数）只有延迟，力的上限用文件里的，不发热。
"""

from collections import deque
from collections.abc import Sequence

import mujoco
import numpy as np

from nova_body.drives import COOLANT_C, DriveArrays, DriveSpec

# 命令晚几步到驱动器：总线每毫秒一次（EtherCAT 1 kHz），仿真的一步也是 1 毫秒。
COMMAND_DELAY_STEPS = 1
# 热每 10 步（10 毫秒）算一次，用这几步力的平方的平均：绕组最快的时间常数也有十几秒，这样足够细，仿真也快。
HEAT_EVERY_STEPS = 10


class DriveLayer:
    """一个身体全部驱动器在仿真里的样子：力的上下限、温度、命令的延迟。

    它改的是传进来的这一份模型里的力的上下限，所以要用仿真自己的那一份模型（不要用大家共用的）。
    """

    def __init__(self, model: mujoco.MjModel, drives: Sequence[DriveSpec | None]) -> None:
        if len(drives) != model.nu:
            raise ValueError(f"模型里有 {model.nu} 个驱动器，却给了 {len(drives)} 个驱动器的样子")
        self._model = model
        self._modeled = np.array([index for index, drive in enumerate(drives) if drive is not None], dtype=int)
        self._arrays = DriveArrays.of([drive for drive in drives if drive is not None])
        self._file_ranges = model.actuator_forcerange.copy()
        # 还在路上的命令：哪一步到、每个驱动器的目标。
        self._commands: deque[tuple[int, np.ndarray]] = deque()
        self._step = 0
        self.winding_c = np.full(len(self._modeled), COOLANT_C)
        self.housing_c = np.full(len(self._modeled), COOLANT_C)
        self._thermal_nm = self._arrays.thermal_limit_nm(self.winding_c)
        self._squares = np.zeros(len(self._modeled))
        self._since_heat = 0

    @property
    def modeled(self) -> np.ndarray:
        """有驱动器模型的那些驱动器（在模型里的编号）。温度的顺序和它一样。"""
        return self._modeled

    def reset(self) -> None:
        """重新开始：驱动器都是冷的，没有在路上的命令，力的上下限回到文件里的。"""
        self.winding_c[:] = COOLANT_C
        self.housing_c[:] = COOLANT_C
        self._thermal_nm = self._arrays.thermal_limit_nm(self.winding_c)
        self._squares[:] = 0.0
        self._since_heat = 0
        self._commands.clear()
        self._step = 0
        self._model.actuator_forcerange[:] = self._file_ranges

    def command(self, targets: Sequence[float]) -> None:
        """发一次命令（每个驱动器的目标）。它晚 COMMAND_DELAY_STEPS 步才到驱动器。"""
        targets = np.asarray(targets, dtype=float)
        if targets.shape != (self._model.nu,):
            raise ValueError(f"命令要给 {self._model.nu} 个驱动器的目标，收到的是 {targets.shape}")
        self._commands.append((self._step + COMMAND_DELAY_STEPS, targets))

    def before_step(self, data: mujoco.MjData) -> None:
        """这一步开始以前：到了的命令交给驱动器；按现在的转速和温度定力的上下限。"""
        while self._commands and self._commands[0][0] <= self._step:
            data.ctrl[:] = self._commands.popleft()[1]
        if len(self._modeled) == 0:
            return
        speeds = data.actuator_velocity[self._modeled]
        lower, upper = self._arrays.limits_with(speeds, self._thermal_nm)
        self._model.actuator_forcerange[self._modeled, 0] = lower
        self._model.actuator_forcerange[self._modeled, 1] = upper

    def after_step(self, data: mujoco.MjData, seconds: float) -> None:
        """这一步走完以后：按每个驱动器真的出了多大的力，算它热了多少。"""
        self._step += 1
        if len(self._modeled) == 0:
            return
        self._squares += data.actuator_force[self._modeled] ** 2
        self._since_heat += 1
        if self._since_heat == HEAT_EVERY_STEPS:
            mean = self._squares / self._since_heat
            self.winding_c, self.housing_c, _ = self._arrays.heat(
                self.winding_c, self.housing_c, mean, seconds * self._since_heat
            )
            self._thermal_nm = self._arrays.thermal_limit_nm(self.winding_c)
            self._squares[:] = 0.0
            self._since_heat = 0


def step(model: mujoco.MjModel, data: mujoco.MjData, drives: DriveLayer) -> None:
    """仿真走一步，驱动器照它们的样子出力、发热。"""
    drives.before_step(data)
    mujoco.mj_step(model, data)
    drives.after_step(data, float(model.opt.timestep))
