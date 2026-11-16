"""规约：网页和仿真之间的消息长什么样。只写在 contracts/sim/*.schema.json 这一处，这里只是照它检查。

网页发来的命令是外面来的输入：在这里检查，里面的代码只处理检查过的。
"""

import json
import os
from functools import cache
from pathlib import Path

from jsonschema import Draft202012Validator

CONTRACTS_DIR = Path(os.environ.get("NOVA_CONTRACTS_DIR", "/contracts")) / "sim"
SCENE, MESSAGE, COMMAND = "scene", "message", "command"
SCHEMA_SUFFIX = ".schema.json"


class CommandError(ValueError):
    """网页发来的命令读不懂、写得不对。说的话是给人看的。"""


@cache
def validator(name: str) -> Draft202012Validator:
    """一份规约的检查器。name 是 scene、message、command。"""
    schema = json.loads((CONTRACTS_DIR / (name + SCHEMA_SUFFIX)).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def problems(name: str, value: object) -> list[str]:
    """这个值哪里不合规约。全对就是空的。"""
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '最外面'}：{error.message}"
        for error in sorted(validator(name).iter_errors(value), key=lambda error: list(map(str, error.absolute_path)))
    ]


def parse_command(text: str) -> dict:
    """把网页发来的一条命令读出来，照规约检查。不对就报错。"""
    try:
        command = json.loads(text)
    except json.JSONDecodeError:
        raise CommandError("命令读不出来：不是 JSON") from None
    if not isinstance(command, dict):
        raise CommandError("命令要是一个对象")
    if problems(COMMAND, command):
        raise CommandError(f"命令的格式不对：{_what_is_wrong(command)}")
    return command


def command_id(text: str) -> int | None:
    """尽量读出命令的编号（答复时要用）。读不出来就是 None。"""
    try:
        command = json.loads(text)
    except json.JSONDecodeError:
        return None
    identifier = command.get("id") if isinstance(command, dict) else None
    return identifier if isinstance(identifier, int) and not isinstance(identifier, bool) and identifier >= 0 else None


def ack(identifier: int | None, reason: str = "") -> dict:
    """对一条命令的答复。reason 是空的就是照做了。"""
    return {"type": "ack", "id": identifier, "ok": not reason, "reason": reason}


def hello(body: str, episode: int) -> dict:
    """刚连上时的招呼。"""
    return {"type": "hello", "body": body, "episode": episode}


def _what_is_wrong(command: dict) -> str:
    """用一句话说命令哪里不对。先看是哪种命令，再照那一种的规约找第一处不对的地方。"""
    definitions = validator(COMMAND).schema["$defs"]
    # 每种命令的规约里都写着它的 type 是哪个词；别的定义（比如编号）没有。
    kinds = {
        schema["properties"]["type"]["const"]: name
        for name, schema in definitions.items()
        if "const" in schema.get("properties", {}).get("type", {})
    }
    kind = kinds.get(command.get("type")) if isinstance(command.get("type"), str) else None
    if kind is None:
        return f"不认识的命令 {command.get('type')!r}"
    one_kind = Draft202012Validator({"$ref": f"#/$defs/{kind}", "$defs": definitions})
    error = min(one_kind.iter_errors(command), key=lambda found: list(map(str, found.absolute_path)))
    where = "/".join(str(part) for part in error.absolute_path)
    return f"{where}：{error.message}" if where else error.message
