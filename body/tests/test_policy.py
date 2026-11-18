"""策略的规约的测试：照规约读进来；规约、ONNX、身体模型有一样对不上就拒绝，并且说出哪里不对；命令超出练过的范围就拒绝，不剪。

用的是测试用的小策略（tests/fixtures/policy，由 train/nova_train/fixtures.py 做）：ONNX 的输出就是观测里的两个数。
"""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from nova_body.policy import (
    CommandSpec,
    ObservationTerm,
    PolicyError,
    _fits_one_row,
    expected_size,
    load_policy,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "policy"
CONTRACT = "contract.json"


def fixture_copy(tmp_path: Path) -> Path:
    """测试用的小策略复制一份，改它不影响别的测试。回规约的路径。"""
    target = tmp_path / "policy"
    shutil.copytree(FIXTURE_DIR, target)
    return target / CONTRACT


def edit_contract(contract_path: Path, change) -> Path:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    change(contract)
    contract_path.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
    return contract_path


def test_the_fixture_policy_loads_with_its_sizes_and_order():
    """正常：读进来，观测一行 18 个、动作 2 个，关节按规约的顺序。"""
    policy = load_policy(FIXTURE_DIR / CONTRACT)
    assert policy.observation_size == 18
    assert policy.action_size == 2
    assert [joint.name for joint in policy.joints] == ["joint_a", "joint_b"]
    assert policy.rate_hz == 50.0
    assert policy.imu_site == "imu"
    assert [observation.term for observation in policy.observations][-1] == ObservationTerm.COMMAND


def test_act_returns_the_two_picked_observations():
    """ONNX 算出来的动作就是观测里的第 6 个（重力的 x）和最后一个（转弯的命令）。"""
    policy = load_policy(FIXTURE_DIR / CONTRACT)
    action = policy.act(np.arange(18, dtype=float))
    np.testing.assert_allclose(action, [6.0, 17.0])


def test_act_refuses_an_observation_of_the_wrong_length():
    """观测的长度不对就拒绝，不补零、不截掉。"""
    policy = load_policy(FIXTURE_DIR / CONTRACT)
    with pytest.raises(PolicyError, match="观测的长度"):
        policy.act(np.zeros(17))


def test_a_changed_onnx_file_is_refused(tmp_path):
    """ONNX 的文件被改过（SHA-256 和规约里的不一样）就拒绝。"""
    contract = fixture_copy(tmp_path)
    onnx_path = contract.parent / "policy.onnx"
    onnx_path.write_bytes(onnx_path.read_bytes() + b"\0")
    with pytest.raises(PolicyError, match="策略（ONNX）的文件和规约里写的不一样"):
        load_policy(contract)


def test_a_missing_body_model_is_refused(tmp_path):
    """练的时候用的身体模型不在就拒绝。"""
    contract = fixture_copy(tmp_path)
    (contract.parent / "body.xml").unlink()
    with pytest.raises(PolicyError, match="身体的模型的文件不在"):
        load_policy(contract)


def test_a_contract_without_the_imu_site_is_refused_by_name(tmp_path):
    """规约少了一项（imu_site）就拒绝，并且说出少的是哪一项。"""
    contract = edit_contract(fixture_copy(tmp_path), lambda c: c.pop("imu_site"))
    with pytest.raises(PolicyError, match="imu_site"):
        load_policy(contract)


def test_another_contract_version_is_refused(tmp_path):
    """规约的版本不是 1（意思变了）就拒绝。"""
    contract = edit_contract(fixture_copy(tmp_path), lambda c: c.update(contract_version=2))
    with pytest.raises(PolicyError, match="contract_version"):
        load_policy(contract)


def test_an_unknown_observation_term_is_refused(tmp_path):
    """规约里没有的观测（比如脚下的高度）不认。"""

    def change(contract):
        contract["observations"][0]["term"] = "height_scan"

    with pytest.raises(PolicyError, match="observations/0/term"):
        load_policy(edit_contract(fixture_copy(tmp_path), change))


def test_a_joint_observation_of_the_wrong_size_is_refused(tmp_path):
    """关节的观测（joint_pos）的长度要等于关节的个数。"""

    def change(contract):
        contract["observations"][3]["size"] = 3

    with pytest.raises(PolicyError, match="joint_pos 的长度是 3，应该是 2"):
        load_policy(edit_contract(fixture_copy(tmp_path), change))


def test_observations_that_do_not_fill_the_onnx_input_are_refused(tmp_path):
    """少了一项观测（命令），一行就只有 15 个，和 ONNX 的输入（18）对不上，拒绝。"""

    def change(contract):
        contract["observations"].pop()

    with pytest.raises(PolicyError, match="规约里的观测一行是 15"):
        load_policy(edit_contract(fixture_copy(tmp_path), change))


def test_repeated_joints_are_refused(tmp_path):
    """两个关节重名就拒绝（不然一个关节会收到两个目标）。"""

    def change(contract):
        contract["joints"][1]["name"] = "joint_a"

    with pytest.raises(PolicyError, match="关节重名：joint_a"):
        load_policy(edit_contract(fixture_copy(tmp_path), change))


def test_a_repeated_observation_term_is_refused(tmp_path):
    """同一项观测出现两次就拒绝。"""

    def change(contract):
        contract["observations"][1]["term"] = "base_lin_vel"

    with pytest.raises(PolicyError, match="重复的项：base_lin_vel"):
        load_policy(edit_contract(fixture_copy(tmp_path), change))


def test_command_ranges_must_cover_every_field(tmp_path):
    """命令的每一项都要有练过的范围，少一项就拒绝。"""

    def change(contract):
        contract["command"]["ranges"].pop("ang_vel_z")

    with pytest.raises(PolicyError, match="命令的范围"):
        load_policy(edit_contract(fixture_copy(tmp_path), change))


def test_a_reversed_command_range_is_refused(tmp_path):
    """范围写反了（最小比最大大）就拒绝。"""

    def change(contract):
        contract["command"]["ranges"]["lin_vel_x"] = [1.0, -1.0]

    with pytest.raises(PolicyError, match="范围反了"):
        load_policy(edit_contract(fixture_copy(tmp_path), change))


def test_a_contract_that_is_not_json_is_refused(tmp_path):
    """规约的文件坏了（不是 JSON）就拒绝。"""
    contract = fixture_copy(tmp_path)
    contract.write_text("{", encoding="utf-8")
    with pytest.raises(PolicyError, match="读不了"):
        load_policy(contract)


COMMAND = CommandSpec(
    fields=("lin_vel_x", "lin_vel_y", "ang_vel_z"),
    ranges={"lin_vel_x": (-1.0, 1.0), "lin_vel_y": (-1.0, 1.0), "ang_vel_z": (-0.5, 0.5)},
)


def test_a_command_in_range_comes_out_in_field_order():
    """范围里的命令按 fields 的顺序排好（给的顺序不要紧）。"""
    vector = COMMAND.vector({"ang_vel_z": 0.25, "lin_vel_x": 0.5, "lin_vel_y": -0.5})
    np.testing.assert_allclose(vector, [0.5, -0.5, 0.25])


def test_a_command_exactly_at_the_edge_is_accepted():
    """正好在范围的边上（1.0、-0.5）可以。"""
    vector = COMMAND.vector({"lin_vel_x": 1.0, "lin_vel_y": -1.0, "ang_vel_z": -0.5})
    np.testing.assert_allclose(vector, [1.0, -1.0, -0.5])


def test_a_command_beyond_the_trained_range_is_refused_not_clipped():
    """超出练过的范围（1.01 m/s）就拒绝，不剪成 1.0。"""
    with pytest.raises(PolicyError, match=r"lin_vel_x = 1.01 超出了练过的范围 \[-1, 1\]"):
        COMMAND.vector({"lin_vel_x": 1.01, "lin_vel_y": 0.0, "ang_vel_z": 0.0})


def test_a_command_missing_a_field_is_refused():
    """少了一项命令就拒绝（不当它是 0）。"""
    with pytest.raises(PolicyError, match="命令少了：ang_vel_z"):
        COMMAND.vector({"lin_vel_x": 0.0, "lin_vel_y": 0.0})


def test_a_command_with_an_unknown_field_is_refused():
    """策略不认得的命令（比如身体的高低）就拒绝。"""
    with pytest.raises(PolicyError, match="不认得这几项命令：height"):
        COMMAND.vector({"lin_vel_x": 0.0, "lin_vel_y": 0.0, "ang_vel_z": 0.0, "height": 0.7})


@pytest.mark.parametrize(
    ("shape", "size", "fits"),
    [
        ([1, 18], 18, True),
        (["batch", 18], 18, True),
        ([None, 18], 18, True),
        ([2, 18], 18, False),
        ([18], 18, False),
        ([1, 17], 18, False),
    ],
    ids=["一行", "行数不定（名字）", "行数不定", "两行", "没有行这一维", "长度不对"],
)
def test_onnx_shapes_must_hold_one_row_of_the_right_size(shape, size, fits):
    """ONNX 的输入、输出要是一行（或者行数不定），长度对。"""
    assert _fits_one_row(shape, size) is fits


def test_expected_sizes_follow_the_term():
    """速度、重力的方向是 3 个；关节的是关节的个数；命令是命令的项数。"""
    assert expected_size(ObservationTerm.PROJECTED_GRAVITY, 29, 3) == 3
    assert expected_size(ObservationTerm.LAST_ACTION, 29, 3) == 29
    assert expected_size(ObservationTerm.COMMAND, 29, 2) == 2
