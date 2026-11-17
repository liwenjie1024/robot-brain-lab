"""给一个网页发东西的队列。

仿真的循环只往队列里放，不等网页收：一个网页收得慢（网断了一半、电脑睡着了），不会拖停仿真和别的网页。
放进去的按顺序发。还没发出去的状态只留最新的一条（旧的状态已经没用了），但答复前后的两条状态不合并：
答复以后发出去的状态，一定是做完那条命令以后的。
"""

import asyncio
from collections import deque
from dataclasses import dataclass

# 正常的网页积压不了几条：状态会合并，排着的只有答复。积压到这么多，就当它收不动了。
MAX_PENDING = 100


@dataclass(frozen=True)
class _Pending:
    text: str
    is_state: bool


class ClientChannel:
    """一个网页的发送队列。放是马上放好的；发由这个网页自己的发送循环来等。"""

    def __init__(self) -> None:
        self._pending: deque[_Pending] = deque()
        self._ready = asyncio.Event()

    @property
    def pending(self) -> int:
        """还没发出去的有几条。"""
        return len(self._pending)

    @property
    def overflowing(self) -> bool:
        """积压得太多：这个网页收不动了。"""
        return len(self._pending) > MAX_PENDING

    def put(self, text: str) -> None:
        """放一条一定要发的消息（招呼、答复），排在最后。"""
        self._pending.append(_Pending(text, is_state=False))
        self._ready.set()

    def put_state(self, text: str) -> None:
        """放一条状态。排在最后的也是一条还没发出去的状态的话，换成这条新的。"""
        if self._pending and self._pending[-1].is_state:
            self._pending[-1] = _Pending(text, is_state=True)
        else:
            self._pending.append(_Pending(text, is_state=True))
        self._ready.set()

    async def next(self) -> str:
        """下一条要发的。还没有就等。"""
        while not self._pending:
            self._ready.clear()
            await self._ready.wait()
        return self._pending.popleft().text
