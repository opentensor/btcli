from typing import Optional

from bittensor_wallet.utils import SS58_FORMAT

from src.bittensor.async_substrate_interface import AsyncSubstrateInterface
from src.bittensor.balances import Balance
from src import Constants, defaults, TYPE_REGISTRY


class SubtensorInterface:
    def __init__(self, network, chain_endpoint):
        if chain_endpoint and chain_endpoint != defaults.subtensor.chain_endpoint:
            self.chain_endpoint = chain_endpoint
            self.network = "local"
        elif network and network in Constants.network_map:
            self.chain_endpoint = Constants.network_map[network]
            self.network = network
        else:
            self.chain_endpoint = chain_endpoint
            self.network = "local"

        self.substrate = AsyncSubstrateInterface(
            chain_endpoint=self.chain_endpoint,
            ss58_format=SS58_FORMAT,
            type_registry=TYPE_REGISTRY,
        )

    async def __aenter__(self):
        async with self.substrate:
            return

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def get_chain_head(self):
        return await self.substrate.get_chain_head()

    async def get_balance(
        self, *addresses, block: Optional[int] = None, reuse_block: bool = False
    ) -> dict[str, Balance]:
        """
        Retrieves the balance for given coldkey(s)
        :param addresses: coldkey addresses(s)
        :param block: the block number, optional, currently unused
        :return: list of Balance objects
        """
        results = await self.substrate.query_multiple(
            params=[a for a in addresses],
            storage_function="Account",
            module="System",
            reuse_block_hash=reuse_block,
        )
        return {k: Balance(v.value["data"]["free"]) for (k, v) in results.items()}

    async def get_total_stake_for_coldkey(
        self, *ss58_addresses, block: Optional[int] = None, reuse_block: bool = False
    ) -> dict[str, Balance]:
        """
        Returns the total stake held on a coldkey.

        :param ss58_addresses: The SS58 address(es) of the coldkey(s)
        :param block: The block number to retrieve the stake from. Currently unused.
        :return:
        """
        results = await self.substrate.query_multiple(
            params=[s for s in ss58_addresses],
            module="SubtensorModule",
            storage_function="TotalColdkeyStake",
            reuse_block_hash=reuse_block,
        )
        return {
            k: Balance.from_rao(r.value) if getattr(r, "value", None) else Balance(0)
            for (k, r) in results.items()
        }
