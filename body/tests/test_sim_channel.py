"""给一个网页发东西的队列的测试：按顺序发；没发出去的状态只留最新的；答复前后的状态不合并；积压太多要知道。"""

import asyncio

import pytest

from nova_sim.channel import MAX_PENDING, ClientChannel

WAIT_S = 0.05


def drain(channel: ClientChannel) -> list[str]:
    """把队列里现在有的都拿出来（不等）。"""

    async def take() -> list[str]:
        return [await channel.next() for _ in range(channel.pending)]

    return asyncio.run(take())


def test_sends_in_the_order_things_were_put():
    """招呼、状态、答复：按放进去的顺序发。"""
    channel = ClientChannel()
    channel.put("hello")
    channel.put_state("state 1")
    channel.put("ack 1")
    assert drain(channel) == ["hello", "state 1", "ack 1"]


def test_only_the_newest_unsent_state_is_kept():
    """网页收得慢，状态一条接一条地来：还没发出去的只留最新的一条。"""
    channel = ClientChannel()
    for number in range(5):
        channel.put_state(f"state {number}")
    assert channel.pending == 1
    assert drain(channel) == ["state 4"]


def test_states_on_both_sides_of_an_answer_are_not_merged():
    """答复前后的状态不合并：答复以后的状态一定是做完命令以后的，答复以前的那条也不丢。"""
    channel = ClientChannel()
    channel.put_state("before 1")
    channel.put_state("before 2")
    channel.put("ack")
    channel.put_state("after 1")
    channel.put_state("after 2")
    assert drain(channel) == ["before 2", "ack", "after 2"]


def test_the_same_answer_twice_is_sent_twice():
    """同一条答复放两次（同一条命令来了两次）：发两次，不合并。"""
    channel = ClientChannel()
    channel.put("ack 5")
    channel.put("ack 5")
    assert drain(channel) == ["ack 5", "ack 5"]


def test_a_state_after_everything_was_sent_is_sent_again():
    """前面的都发完了，再来一条状态：照发（合并只对还在排着的）。"""
    channel = ClientChannel()
    channel.put_state("state 1")
    assert drain(channel) == ["state 1"]
    channel.put_state("state 2")
    assert drain(channel) == ["state 2"]


def test_waits_until_something_is_put():
    """队列空着：等着；一放进来就拿到。"""

    async def scenario() -> tuple[bool, str]:
        channel = ClientChannel()
        waiting = asyncio.create_task(channel.next())
        await asyncio.sleep(WAIT_S)
        still_waiting = not waiting.done()
        channel.put_state("state")
        return still_waiting, await asyncio.wait_for(waiting, WAIT_S * 10)

    assert asyncio.run(scenario()) == (True, "state")


def test_empty_channel_keeps_waiting():
    """一直没东西放进来：一直等，不会凭空拿到什么。"""

    async def scenario() -> None:
        await asyncio.wait_for(ClientChannel().next(), WAIT_S)

    with pytest.raises(TimeoutError):
        asyncio.run(scenario())


@pytest.mark.parametrize(
    ("answers", "overflowing"),
    [(0, False), (MAX_PENDING - 1, False), (MAX_PENDING, True)],
    ids=["只有状态", "加上状态正好到上限", "加上状态超过上限"],
)
def test_knows_when_too_much_is_waiting(answers, overflowing):
    """排着的超过上限，就是这个网页收不动了。状态再多也只占一条，撑满它的只会是答复。"""
    channel = ClientChannel()
    for number in range(answers):
        channel.put(f"ack {number}")
    for number in range(MAX_PENDING * 2):
        channel.put_state(f"state {number}")
    assert channel.pending == answers + 1
    assert channel.overflowing is overflowing
