"""启动实时的仿真和给网页的服务。

用法：python -m nova_sim [--port 端口]
平常用 docker compose up -d sim 启动，网页（view）经它自己的开发服务器连过来。
"""

import argparse
import sys

from aiohttp import web

from nova_sim.bodies import load_choices
from nova_sim.server import DEFAULT_PORT, Hub, create_app

LISTEN_HOST = "0.0.0.0"


def main(argv: list[str] | None = None) -> int:
    """命令行入口：把身体准备好，启动服务，一直跑到被停掉。"""
    parser = argparse.ArgumentParser(description="启动实时的仿真和给网页的服务。")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="在哪个端口上等网页连过来")
    arguments = parser.parse_args(argv)
    choices = load_choices()
    for choice in choices.values():
        print(f"{choice.name}：{'准备好了' if choice.body is not None else '用不了：' + choice.reason}")
    # 容器里要在所有的地址上等；从外面只能经这台电脑自己（compose.yaml 里只开了 127.0.0.1）连进来。
    web.run_app(create_app(Hub(choices)), host=LISTEN_HOST, port=arguments.port, print=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
