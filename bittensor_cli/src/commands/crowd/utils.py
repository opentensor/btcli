from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


async def get_constant(subtensor: SubtensorInterface, constant_name: str) -> int:
    result = await subtensor.substrate.get_constant(
        module_name="Crowdloan",
        constant_name=constant_name,
    )
    return getattr(result, "value", result)
