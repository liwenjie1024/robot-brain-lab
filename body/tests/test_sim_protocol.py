"""规约的测试：网页发来的命令每一种都检查；不对的拒绝，说为什么；答复的样子合规约。"""

import json

import pytest
from jsonschema import Draft202012Validator

from nova_sim.protocol import (
    COMMAND,
    CONTRACTS_DIR,
    MESSAGE,
    SCENE,
    CommandError,
    ack,
    command_id,
    hello,
    parse_command,
    problems,
    validator,
)

GOOD_COMMANDS = [
    {"type": "reset", "id": 0},
    {"type": "pause", "id": 1},
    {"type": "resume", "id": 2},
    {"type": "control", "id": 3, "on": False},
    {"type": "push", "id": 4, "direction": "left", "share": 0.04},
    {"type": "push", "id": 5, "direction": "forward", "share": 0.5},
    {"type": "body", "id": 6, "body": "g1"},
]


@pytest.mark.parametrize("name", [SCENE, MESSAGE, COMMAND])
def test_every_contract_is_a_valid_schema(name):
    """三份规约都是写对了的 JSON Schema，每一份都有标题和说明。"""
    schema = json.loads((CONTRACTS_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema["title"] and schema["description"]
    assert validator(name) is validator(name)


@pytest.mark.parametrize("command", GOOD_COMMANDS, ids=[command["type"] for command in GOOD_COMMANDS])
def test_accepts_every_kind_of_command(command):
    """每一种命令写对了都收：重新开始、暂停、继续、松开或顶住、推一下、换身体。"""
    assert parse_command(json.dumps(command)) == command
    assert command_id(json.dumps(command)) == command["id"]


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("{ not json", "命令读不出来：不是 JSON"),
        ("[1, 2]", "命令要是一个对象"),
        ("7", "命令要是一个对象"),
        ('"reset"', "命令要是一个对象"),
        ("{}", "不认识的命令 None"),
        ('{"type": "dance", "id": 1}', "不认识的命令 'dance'"),
        ('{"type": "reset"}', "'id' is a required property"),
        ('{"type": "reset", "id": -1}', "id：-1 is less than the minimum of 0"),
        ('{"type": "reset", "id": 1.5}', "id：1.5 is not of type 'integer'"),
        ('{"type": "reset", "id": "1"}', "id："),
        ('{"type": "reset", "id": true}', "id："),
        ('{"type": "reset", "id": 1, "extra": 2}', "Additional properties are not allowed"),
        ('{"type": "push", "id": 1, "direction": "left", "share": 0}', "share：0 is less than or equal to the minimum"),
        ('{"type": "push", "id": 1, "direction": "left", "share": -0.1}', "share："),
        ('{"type": "push", "id": 1, "direction": "left", "share": 0.51}', "share：0.51 is greater than the maximum"),
        ('{"type": "push", "id": 1, "direction": "left", "share": "0.1"}', "share："),
        ('{"type": "push", "id": 1, "direction": "up", "share": 0.1}', "direction：'up' is not one of"),
        ('{"type": "push", "id": 1, "share": 0.1}', "'direction' is a required property"),
        ('{"type": "control", "id": 1, "on": "yes"}', "on："),
        ('{"type": "control", "id": 1}', "'on' is a required property"),
        ('{"type": "body", "id": 1, "body": 5}', "body："),
    ],
    ids=[
        "不是 JSON",
        "是一张表",
        "是一个数",
        "是一段文字",
        "空的对象",
        "不认识的命令",
        "没有编号",
        "编号是负的",
        "编号是小数",
        "编号是文字",
        "编号是真假值",
        "多了一项",
        "推力是 0",
        "推力是负的",
        "推力比一半体重大",
        "推力是文字",
        "不认识的方向",
        "没说往哪推",
        "开关不是真假值",
        "没说开还是关",
        "身体的记号不是文字",
    ],
)
def test_rejects_a_bad_command(text, reason):
    """命令写得不对就拒绝，说是哪一项不对。范围以外的值不改成范围里的。"""
    with pytest.raises(CommandError) as error:
        parse_command(text)
    assert reason in str(error.value)


@pytest.mark.parametrize(
    ("text", "identifier"),
    [
        ('{"type": "dance", "id": 12}', 12),
        ('{"id": 0}', 0),
        ("{ not json", None),
        ("[3]", None),
        ('{"id": -2}', None),
        ('{"id": true}', None),
        ('{"id": 2.0}', None),
        ('{"type": "reset"}', None),
    ],
    ids=["不认识的命令", "只有编号", "不是 JSON", "是一张表", "编号是负的", "编号是真假值", "编号是小数", "没有编号"],
)
def test_reads_the_id_of_a_bad_command_when_it_can(text, identifier):
    """命令不对时，答复里尽量带上它的编号（网页好对上是哪一条）；读不出来就是空的。"""
    assert command_id(text) == identifier


def test_ack_says_done_or_why_not():
    """答复：照做了 reason 是空的；没照做 reason 里写着为什么。两种都合规约。"""
    done, refused, unreadable = ack(3), ack(4, "上一下还没推完"), ack(None, "命令读不出来：不是 JSON")
    assert done == {"type": "ack", "id": 3, "ok": True, "reason": ""}
    assert refused == {"type": "ack", "id": 4, "ok": False, "reason": "上一下还没推完"}
    assert unreadable["id"] is None and not unreadable["ok"]
    for message in (done, refused, unreadable):
        assert problems(MESSAGE, message) == []


def test_hello_names_the_body_and_the_episode():
    """招呼里写着现在是哪个身体、第几回，合规约。"""
    message = hello("nova", 3)
    assert message == {"type": "hello", "body": "nova", "episode": 3}
    assert problems(MESSAGE, message) == []


def test_problems_point_at_what_is_wrong():
    """不合规约的消息：说出是哪一项。"""
    assert problems(MESSAGE, {"type": "ack", "id": 1, "ok": True, "reason": ""}) == []
    found = problems(MESSAGE, {"type": "hello", "body": "nova"})
    assert found and "最外面" in found[0]
    assert problems(COMMAND, {"type": "push", "id": 1, "direction": "left", "share": 2})
