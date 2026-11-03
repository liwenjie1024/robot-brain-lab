"""python -m robot_sim: 몸(시뮬레이터)을 띄운다."""

from __future__ import annotations

import logging
import os

from aiohttp import web

from .assets import POLICY_CONFIG, POLICY_FILE, ROBOT_XML, require_assets
from .limits import DEFAULT_LIMITS
from .locomotion import WalkingController
from .server import create_app
from .simulation import Simulation, build_arena

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    require_assets()
    simulation = Simulation(build_arena(ROBOT_XML), WalkingController.from_files(POLICY_CONFIG, POLICY_FILE))
    web.run_app(
        create_app(simulation, DEFAULT_LIMITS),
        host=os.environ.get("SIM_HOST", DEFAULT_HOST),
        port=int(os.environ.get("SIM_PORT", DEFAULT_PORT)),
        print=lambda message: logging.getLogger(__name__).info("%s", message),
    )


if __name__ == "__main__":
    main()
