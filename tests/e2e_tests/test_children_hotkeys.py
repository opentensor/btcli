import pytest

from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.commands.stake.children_hotkeys import (
    get_childkey_completion_block,
)


@pytest.mark.asyncio
async def test_get_childkey_completion_block(local_chain):
    async with SubtensorInterface("ws://127.0.0.1:9945") as subtensor:
        current_block, completion_block = await get_childkey_completion_block(
            subtensor, 1
        )
        assert (completion_block - current_block) >= 7200
