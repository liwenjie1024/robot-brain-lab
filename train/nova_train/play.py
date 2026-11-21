"""看练出来的策略：就是 mjlab 的 play，参数一样，只多一处改动（和 nova_train.train 的一样）。

用法：docker compose run --rm -p 127.0.0.1:8080:8080 train python -m nova_train.play Nova-Velocity-Stairs-Unitree-G1 \
        --checkpoint-file /results/train/g1_velocity/<那一次>/model_4600.pt --viewer viser

然后在浏览器里打开 http://127.0.0.1:8080（mjlab 的网页播放器 viser）。播放器里可以换成那一次训练的别的存档，
看机器人是怎么一步步学会的。一般用 scripts/watch.ps1，它找最新的那一次、开容器、开浏览器。

改动：不打印"解的次数用完了"的提醒（为什么见 nova_train.train）。
"""

from mjlab.scripts.play import main as mjlab_play
from mjlab.sim.sim import SimulationCfg

import nova_train.tasks  # noqa: F401  登记我们自己的任务（Nova-…）
from nova_train.train import apply_wp_opt_quietly


def main() -> None:
    SimulationCfg.apply_wp_opt = apply_wp_opt_quietly
    mjlab_play()


if __name__ == "__main__":
    main()
