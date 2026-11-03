"""화면용 모델 설명: 화면이 로봇을 몰라도 그릴 수 있는지."""

from __future__ import annotations

import struct

import pytest

from robot_sim.limits import DEFAULT_LIMITS
from robot_sim.scene import MESH_HEADER, describe, mesh_binary, moving_bodies
from robot_sim.simulation import ROBOT_ROOT_BODY

RATES = {"physicsHz": 500.0, "controlHz": 50.0, "stateHz": 50.0}


def test_describes_robot_visuals_and_floor(arena_model):
    """로봇의 보이는 모양(메시)과 바닥을 알리고, 로봇의 충돌용 모양은 겹쳐 그리지 않게 뺀다"""
    scene = describe(arena_model, arena_model.body(ROBOT_ROOT_BODY).id, DEFAULT_LIMITS, RATES)

    shapes = [geom["shape"] for geom in scene["geoms"]]
    robot_geoms = [geom for geom in scene["geoms"] if geom["body"] != 0]
    assert shapes.count("plane") == 1
    assert robot_geoms
    assert all(geom["shape"] == "mesh" for geom in robot_geoms)
    assert len(robot_geoms) == arena_model.nmesh


def test_moving_bodies_are_the_robot_links(arena_model):
    """움직이는 몸체는 바닥(세계)을 빼고 골반과 다리 12마디다"""
    bodies = moving_bodies(arena_model)

    assert len(bodies) == 13
    assert 0 not in bodies


def test_limits_and_rates_are_published(arena_model):
    scene = describe(arena_model, arena_model.body(ROBOT_ROOT_BODY).id, DEFAULT_LIMITS, RATES)

    assert scene["limits"]["forward"] == {"min": -0.5, "max": 1.0}
    assert scene["rates"]["controlHz"] == 50.0


def test_mesh_binary_layout(arena_model):
    """메시 바이너리: 머리말(꼭짓점 수, 삼각형 수) 뒤에 xyz(f32)와 번호(u32)가 이어진다"""
    data = mesh_binary(arena_model, 0)

    vertices, faces = MESH_HEADER.unpack_from(data)
    assert vertices == arena_model.mesh_vertnum[0]
    assert faces == arena_model.mesh_facenum[0]
    assert len(data) == MESH_HEADER.size + vertices * 3 * 4 + faces * 3 * 4
    first_index = struct.unpack_from("<I", data, MESH_HEADER.size + vertices * 12)[0]
    assert first_index < vertices


@pytest.mark.parametrize("mesh", [-1, 10_000], ids=["음수", "없는 번호"])
def test_unknown_mesh_raises(arena_model, mesh):
    with pytest.raises(KeyError):
        mesh_binary(arena_model, mesh)
