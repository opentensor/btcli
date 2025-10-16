from typing import Optional

from async_substrate_interface.types import Runtime

from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


async def get_constant(
    subtensor: SubtensorInterface,
    constant_name: str,
    runtime: Optional[Runtime] = None,
    block_hash: Optional[str] = None,
) -> int:
    """
    Get a constant from the Crowdloan pallet.

    Args:
        subtensor: SubtensorInterface object for chain interaction
        constant_name: Name of the constant to get
        runtime: Runtime object
        block_hash: Block hash

    Returns:
        The value of the constant
    """

    runtime = runtime or await subtensor.substrate.init_runtime(block_hash=block_hash)

    result = await subtensor.substrate.get_constant(
        module_name="Crowdloan",
        constant_name=constant_name,
        block_hash=block_hash,
        runtime=runtime,
    )
    return getattr(result, "value", result)
