"""训练：就是 mjlab 的 train，参数一样，只多一处改动。

用法：docker compose run --rm train python -m nova_train.train Mjlab-Velocity-Flat-Unitree-G1 \
        --env.scene.num-envs 4096 --agent.max-iterations 1500 --agent.logger tensorboard \
        --agent.upload-model False --log-root /results/train

任务除了 mjlab 自带的，还有我们自己的（nova_train.tasks，名字以 Nova- 开头）。

改动：不打印"解的次数用完了"的提醒。mjlab 故意每一步只解 10 次（ls 20 次），为了快，解不完是预料之中的；
MuJoCo Warp 3.17 默认每一次都在显卡上打印一行，一轮就是几百行，还拖慢显卡。
缓冲区不够（接触、约束放不下）的提醒留着：那是真的算错了。
"""

import mujoco_warp as mjw
from mjlab.scripts.train import main as mjlab_train
from mjlab.sim.sim import SimulationCfg

import nova_train.tasks  # noqa: F401  登记我们自己的任务（Nova-…）

EXPECTED_OVERFLOWS = int(mjw.OverflowType.ITERATIONS) | int(mjw.OverflowType.LS_ITERATIONS)

_apply_wp_opt = SimulationCfg.apply_wp_opt


def apply_wp_opt_quietly(self: SimulationCfg, wp_opt: mjw.Option) -> None:
    _apply_wp_opt(self, wp_opt)
    wp_opt.warn_overflow = int(wp_opt.warn_overflow) & ~EXPECTED_OVERFLOWS


def main() -> None:
    SimulationCfg.apply_wp_opt = apply_wp_opt_quietly
    mjlab_train()


if __name__ == "__main__":
    main()
