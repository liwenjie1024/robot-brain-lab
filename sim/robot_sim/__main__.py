"""python -m robot_sim: 몸(시뮬레이터)을 띄운다."""

from __future__ import annotations

import logging
import os

from aiohttp import web

from .limits import DEFAULT_LIMITS
from .server import create_app
from .simulation import Simulation

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    simulation = Simulation()
    web.run_app(
        create_app(simulation, DEFAULT_LIMITS),
        host=os.environ.get("SIM_HOST", DEFAULT_HOST),
        port=int(os.environ.get("SIM_PORT", DEFAULT_PORT)),
        print=lambda message: logging.getLogger(__name__).info("%s", message),
    )


if __name__ == "__main__":
    main()
