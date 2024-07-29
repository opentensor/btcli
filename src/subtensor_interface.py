import asyncio
from typing import Optional, Any, Union, TypedDict

import scalecodec
from bittensor_wallet.utils import SS58_FORMAT
from scalecodec.base import RuntimeConfiguration
from scalecodec.type_registry import load_type_registry_preset

from src.bittensor.async_substrate_interface import AsyncSubstrateInterface
from src.bittensor.chain_data import DelegateInfo, custom_rpc_type_registry, StakeInfo
from src.bittensor.balances import Balance
from src import Constants, defaults, TYPE_REGISTRY
from src.utils import ss58_to_vec_u8


class ParamWithTypes(TypedDict):
    name: str  # Name of the parameter.
    type: str  # ScaleType string of the parameter.


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

    async def encode_params(
        self,
        call_definition: list["ParamWithTypes"],
        params: Union[list[Any], dict[str, Any]],
    ) -> str:
        """Returns a hex encoded string of the params using their types."""
        param_data = scalecodec.ScaleBytes(b"")

        for i, param in enumerate(call_definition["params"]):  # type: ignore
            scale_obj = await self.substrate.create_scale_object(param["type"])
            if type(params) is list:
                param_data += scale_obj.encode(params[i])
            else:
                if param["name"] not in params:
                    raise ValueError(f"Missing param {param['name']} in params dict.")

                param_data += scale_obj.encode(params[param["name"]])

        return param_data.to_hex()

    async def get_all_subnet_netuids(
        self, block_hash: Optional[str] = None
    ) -> list[int]:
        """
        Retrieves the list of all subnet unique identifiers (netuids) currently present in the Bittensor network.

        :param block_hash: The hash of the block to retrieve the subnet unique identifiers from.
        :return: A list of subnet netuids.

        This function provides a comprehensive view of the subnets within the Bittensor network,
        offering insights into its diversity and scale.
        """
        result = await self.substrate.query_map(
            module="SubtensorModule",
            storage_function="NetworksAdded",
            block_hash=block_hash,
            reuse_block_hash=True,
        )
        return (
            []
            if result is None or not hasattr(result, "records")
            else [netuid.value for netuid, exists in result if exists]
        )

    async def is_hotkey_delegate(
        self,
        hotkey_ss58: str,
        block_hash: Optional[int] = None,
        reuse_block: Optional[bool] = False,
    ) -> bool:
        """
        Determines whether a given hotkey (public key) is a delegate on the Bittensor network. This function
        checks if the neuron associated with the hotkey is part of the network's delegation system.

        Args:
            hotkey_ss58 (str): The SS58 address of the neuron's hotkey.
            block_hash (Optional[int], optional): The blockchain block number for the query.

        Returns:
            bool: ``True`` if the hotkey is a delegate, ``False`` otherwise.

        Being a delegate is a significant status within the Bittensor network, indicating a neuron's
        involvement in consensus and governance processes.
        """
        return hotkey_ss58 in [
            info.hotkey_ss58
            for info in await self.get_delegates(
                block_hash=block_hash, reuse_block=reuse_block
            )
        ]

    async def get_delegates(
        self, block_hash: Optional[str] = None, reuse_block: Optional[bool] = False
    ):
        json_body = await self.substrate.rpc_request(
            method="delegateInfo_getDelegates",  # custom rpc method
            params=[block_hash] if block_hash else [],
            reuse_block_hash=reuse_block,
        )

        if not (result := json_body.get("result", None)):
            return []

        return DelegateInfo.list_from_vec_u8(result)

    async def get_stake_info_for_coldkey(
        self,
        coldkey_ss58: str,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> Optional[list[StakeInfo]]:
        """
        Retrieves stake information associated with a specific coldkey. This function provides details
        about the stakes held by an account, including the staked amounts and associated delegates.

        Args:
            coldkey_ss58 (str): The ``SS58`` address of the account's coldkey.
            block (Optional[int], optional): The blockchain block number for the query.

        Returns:
            List[StakeInfo]: A list of StakeInfo objects detailing the stake allocations for the account.

        Stake information is vital for account holders to assess their investment and participation
        in the network's delegation and consensus processes.
        """
        encoded_coldkey = ss58_to_vec_u8(coldkey_ss58)

        hex_bytes_result = await self.query_runtime_api(
            runtime_api="StakeInfoRuntimeApi",
            method="get_stake_info_for_coldkey",
            params=[encoded_coldkey],
            block_hash=block_hash,
            reuse_block=reuse_block,
        )

        if hex_bytes_result is None:
            return None

        if hex_bytes_result.startswith("0x"):
            bytes_result = bytes.fromhex(hex_bytes_result[2:])
        else:
            bytes_result = bytes.fromhex(hex_bytes_result)
        # TODO: review if this is the correct type / works
        return StakeInfo.list_from_vec_u8(bytes_result)  # type: ignore

    async def query_runtime_api(
        self,
        runtime_api: str,
        method: str,
        params: Optional[Union[list[int], dict[str, int]]],
        block_hash: Optional[str] = None,
        reuse_block: Optional[bool] = False,
    ) -> Optional[str]:
        """
        Queries the runtime API of the Bittensor blockchain, providing a way to interact with the underlying
        runtime and retrieve data encoded in Scale Bytes format. This function is essential for advanced users
        who need to interact with specific runtime methods and decode complex data types.

        Args:
            runtime_api (str): The name of the runtime API to query.
            method (str): The specific method within the runtime API to call.
            params (Optional[List[ParamWithTypes]], optional): The parameters to pass to the method call.
            block (Optional[int]): The blockchain block number at which to perform the query.

        Returns:
            Optional[bytes]: The Scale Bytes encoded result from the runtime API call, or ``None`` if the call fails.

        This function enables access to the deeper layers of the Bittensor blockchain, allowing for detailed
        and specific interactions with the network's runtime environment.
        """
        call_definition = TYPE_REGISTRY["runtime_api"][runtime_api]["methods"][method]

        data = (
            "0x"
            if params is None
            else await self.encode_params(
                call_definition=call_definition, params=params
            )
        )
        api_method = f"{runtime_api}_{method}"

        json_result = await self.substrate.rpc_request(
            method="state_call",
            params=[api_method, data, block_hash] if block_hash else [api_method, data],
        )

        if json_result is None:
            return None

        return_type = call_definition["type"]

        as_scale_bytes = scalecodec.ScaleBytes(json_result["result"])  # type: ignore

        rpc_runtime_config = RuntimeConfiguration()
        rpc_runtime_config.update_type_registry(load_type_registry_preset("legacy"))
        rpc_runtime_config.update_type_registry(custom_rpc_type_registry)

        obj = rpc_runtime_config.create_scale_object(return_type, as_scale_bytes)
        if obj.data.to_hex() == "0x0400":  # RPC returned None result
            return None

        return obj.decode()

    async def get_balance(
        self, *addresses, block: Optional[int] = None, reuse_block: bool = False
    ) -> dict[str, Balance]:
        """
        Retrieves the balance for given coldkey(s)
        :param addresses: coldkey addresses(s)
        :param block: the block number, optional, currently unused
        :param reuse_block: Whether to reuse the last-used block hash when retrieving info.
        :return: dict of {address: Balance objects}
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
        :param reuse_block: Whether to reuse the last-used block hash when retrieving info.
        :return:
        """
        results = await self.substrate.query_multiple(
            params=[s for s in ss58_addresses],
            module="SubtensorModule",
            storage_function="TotalColdkeyStake",
            reuse_block_hash=reuse_block,
        )
        return {
            k: Balance.from_rao(getattr(r, "value", 0)) for (k, r) in results.items()
        }

    async def get_netuids_for_hotkey(
        self, hotkey_ss58: str, block_hash: Optional[str] = None, reuse_block: bool = False
    ) -> list[int]:
        """
        Retrieves a list of subnet UIDs (netuids) for which a given hotkey is a member. This function
        identifies the specific subnets within the Bittensor network where the neuron associated with
        the hotkey is active.

        Args:
            hotkey_ss58 (str): The ``SS58`` address of the neuron's hotkey.
            block (Optional[int]): The blockchain block number at which to perform the query.

        Returns:
            List[int]: A list of netuids where the neuron is a member.
        """
        result = await self.substrate.query_map(
            module="SubtensorModule",
            storage_function="IsNetworkMember",
            params=[hotkey_ss58],
            block_hash=block_hash,
            reuse_block_hash=reuse_block
        )
        return (
            [record[0].value for record in result.records if record[1]]
            if result and hasattr(result, "records")
            else []
        )

    async def subnet_exists(
        self, netuid: int, block_hash: Optional[str] = None, reuse_block: bool = False
    ) -> bool:
        """
        Checks if a subnet with the specified unique identifier (netuid) exists within the Bittensor network.

        :param netuid: The unique identifier of the subnet.
        :param block_hash: The hash of the blockchain block number at which to check the subnet existence.

        :return: `True` if the subnet exists, `False` otherwise.

        This function is critical for verifying the presence of specific subnets in the network,
        enabling a deeper understanding of the network's structure and composition.
        """
        result = await self.substrate.query(
            module="SubtensorModule",
            storage_function="NetworksAdded",
            params=[netuid],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )
        return getattr(result, "value", False)

    async def get_hyperparameter(
        self, param_name: str, netuid: int, block_hash: Optional[str] = None
    ) -> Optional[Any]:
        """
        Retrieves a specified hyperparameter for a specific subnet.

        :param param_name: The name of the hyperparameter to retrieve.
        :param netuid: The unique identifier of the subnet.
        :param block_hash: The hash of blockchain block number for the query.

        :return: The value of the specified hyperparameter if the subnet exists, or None
        """
        if not await self.subnet_exists(netuid, block_hash):
            return None

        result = await self.substrate.query(
            module="SubtensorModule",
            storage_function=param_name,
            params=[netuid],
            block_hash=block_hash,
        )

        if result is None or not hasattr(result, "value"):
            return None

        return result.value

    async def filter_netuids_by_registered_hotkeys(
        self, all_netuids, filter_for_netuids, all_hotkeys, reuse_block: bool = False
    ) -> list[int]:
        netuids_with_registered_hotkeys = [item for sublist in await asyncio.gather(
            *[
                self.get_netuids_for_hotkey(wallet.hotkey.ss58_address, reuse_block=reuse_block)
                for wallet in all_hotkeys
            ]
        ) for item in sublist]

        if not filter_for_netuids:
            all_netuids = netuids_with_registered_hotkeys

        else:
            all_netuids = [
                netuid for netuid in all_netuids if netuid in filter_for_netuids
            ]
            all_netuids.extend(netuids_with_registered_hotkeys)

        return list(set(all_netuids))
