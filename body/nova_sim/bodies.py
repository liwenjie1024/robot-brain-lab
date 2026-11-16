"""能放上测试台的身体：Nova 和基线。网页用记号来选。"""

from dataclasses import dataclass

from nova_body import baseline, model
from nova_body.body import Body
from nova_body.third_party import AssetError, ManifestError

NOVA = "nova"
G1 = "g1"


@dataclass(frozen=True)
class Choice:
    """一个能选的身体。body 是 None 的现在选不了，reason 说为什么。"""

    key: str
    name: str
    body: Body | None
    reason: str = ""


def load_choices() -> dict[str, Choice]:
    """把每个身体都准备好。基线的文件还没下载时，基线选不了（记下为什么），Nova 照样能用。"""
    choices = [Choice(NOVA, model.BODY_NAME, model.build_nova().body)]
    try:
        choices.append(Choice(G1, baseline.BODY_NAME, baseline.load_g1()))
    except (AssetError, ManifestError) as error:
        choices.append(Choice(G1, baseline.BODY_NAME, None, str(error)))
    return {choice.key: choice for choice in choices}
