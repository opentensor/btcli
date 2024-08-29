import asyncio
from typing import Optional, Any, Union, TypedDict, Iterable

import scalecodec
import typer
from bittensor_wallet import Wallet
from bittensor_wallet.utils import SS58_FORMAT
from scalecodec import GenericCall
from scalecodec.base import RuntimeConfiguration
from scalecodec.type_registry import load_type_registry_preset
from substrateinterface.exceptions import SubstrateRequestException

from bittensor_cli.src.bittensor.async_substrate_interface import (
    AsyncSubstrateInterface,
    TimeoutException,
)
from bittensor_cli.src.bittensor.chain_data import (
    DelegateInfo,
    custom_rpc_type_registry,
    StakeInfo,
    NeuronInfoLite,
    NeuronInfo,
    SubnetHyperparameters,
)
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src import Constants, defaults, TYPE_REGISTRY
from bittensor_cli.src.utils import (
    ss58_to_vec_u8,
    format_error_message,
    console,
    err_console,
)


class ParamWithTypes(TypedDict):
    name: str  # Name of the parameter.
    type: str  # ScaleType string of the parameter.


class SubtensorInterface:
    """
    Thin layer for interacting with Substrate Interface. Mostly a collection of frequently-used calls.
    """

    def __init__(self, network, chain_endpoint):
        if chain_endpoint:
            if not chain_endpoint.startswith("ws"):
                console.log(
                    "[yellow]Warning[/yellow] verify your chain endpoint is a valid substrate endpoint."
                )
            self.chain_endpoint = chain_endpoint
            self.network = "local"
        elif network and network in Constants.network_map:
            self.chain_endpoint = Constants.network_map[network]
            self.network = network
        else:
            console.log(
                f"Network not specified or not valid. Using default chain endpoint: "
                f"{Constants.network_map[defaults.subtensor.network]}.\n"
                f"You can set this for commands with the `--network` flag, or by setting this"
                f" in the config."
            )
            self.chain_endpoint = Constants.network_map[defaults.subtensor.network]
            self.network = defaults.subtensor.network

        self.substrate = AsyncSubstrateInterface(
            chain_endpoint=self.chain_endpoint,
            ss58_format=SS58_FORMAT,
            type_registry=TYPE_REGISTRY,
        )

    def __str__(self):
        return f"Network: {self.network}, Chain: {self.chain_endpoint}"

    async def __aenter__(self):
        with console.status(
            f"[yellow]Connecting to Substrate:[/yellow][bold white] {self}..."
        ):
            try:
                async with self.substrate:
                    return self
            except TimeoutException:
                err_console.print(
                    "\n[red]Error[/red]: Timeout occurred connecting to substrate. "
                    f"Verify your chain and network settings: {self}"
                )
                raise typer.Exit(code=1)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.substrate.close()

    async def encode_params(
        self,
        call_definition: list["ParamWithTypes"],
        params: Union[list[Any], dict[str, Any]],
    ) -> str:
        """Returns a hex encoded string of the params using their types."""
        param_data = scalecodec.ScaleBytes(b"")

        for i, param in enumerate(call_definition["params"]):  # type: ignore
            scale_obj = await self.substrate.create_scale_object(param["type"])
            if isinstance(params, list):
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

        :param hotkey_ss58: The SS58 address of the neuron's hotkey.
        :param block_hash: The hash of the blockchain block number for the query.
        :param reuse_block: Whether to reuse the last-used block hash.

        :return: `True` if the hotkey is a delegate, `False` otherwise.

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
    ) -> list[DelegateInfo]:
        """
        Fetches all delegates on the chain

        :param block_hash: hash of the blockchain block number for the query.
        :param reuse_block: whether to reuse the last-used block hash.

        :return: List of DelegateInfo objects, or an empty list if there are no delegates.
        """
        json_body = await self.substrate.rpc_request(
            method="delegateInfo_getDelegates",  # custom rpc method
            params=[block_hash] if block_hash else [],
            reuse_block_hash=reuse_block,
        )

        if not (result := json_body.get("result", None)):
            return []

        # TODO not yet working
        # import time
        # start = time.time()
        # DelegateInfo.list_from_vec_u8(result)
        # print("old time", time.time() - start)
        # start = time.time()
        # DelegateInfo.list_from_vec_u8_new(bytes(result))
        # print("new time", time.time() - start)

        # return DelegateInfo.list_from_vec_u8_new(bytes(result))

        return DelegateInfo.list_from_vec_u8(result)

    async def get_stake_info_for_coldkey(
        self,
        coldkey_ss58: str,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> list[StakeInfo]:
        """
        Retrieves stake information associated with a specific coldkey. This function provides details
        about the stakes held by an account, including the staked amounts and associated delegates.

        :param coldkey_ss58: The ``SS58`` address of the account's coldkey.
        :param block_hash: The hash of the blockchain block number for the query.
        :param reuse_block: Whether to reuse the last-used block hash.

        :return: A list of StakeInfo objects detailing the stake allocations for the account.

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
            return []

        if hex_bytes_result.startswith("0x"):
            bytes_result = bytes.fromhex(hex_bytes_result[2:])
        else:
            bytes_result = bytes.fromhex(hex_bytes_result)
        # TODO: review if this is the correct type / works
        return StakeInfo.list_from_vec_u8(bytes_result)  # type: ignore

    async def get_stake_for_coldkey_and_hotkey(
        self, hotkey_ss58: str, coldkey_ss58: str, block_hash: Optional[str]
    ) -> Balance:
        """
        Retrieves stake information associated with a specific coldkey and hotkey.
        :param hotkey_ss58: the hotkey SS58 address to query
        :param coldkey_ss58: the coldkey SS58 address to query
        :param block_hash: the hash of the blockchain block number for the query.
        :return: Stake Balance for the given coldkey and hotkey
        """
        _result = await self.substrate.query(
            module="SubtensorModule",
            storage_function="Stake",
            params=[hotkey_ss58, coldkey_ss58],
            block_hash=block_hash,
        )
        return Balance.from_rao(getattr(_result, "value", 0))

    async def query_runtime_api(
        self,
        runtime_api: str,
        method: str,
        params: Optional[Union[list[list[int]], dict[str, int]]],
        block_hash: Optional[str] = None,
        reuse_block: Optional[bool] = False,
    ) -> Optional[str]:
        """
        Queries the runtime API of the Bittensor blockchain, providing a way to interact with the underlying
        runtime and retrieve data encoded in Scale Bytes format. This function is essential for advanced users
        who need to interact with specific runtime methods and decode complex data types.

        :param runtime_api: The name of the runtime API to query.
        :param method: The specific method within the runtime API to call.
        :param params: The parameters to pass to the method call.
        :param block_hash: The hash of the blockchain block number at which to perform the query.
        :param reuse_block: Whether to reuse the last-used block hash.

        :return: The Scale Bytes encoded result from the runtime API call, or ``None`` if the call fails.

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
        self,
        *addresses: str,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> dict[str, Balance]:
        """
        Retrieves the balance for given coldkey(s)
        :param addresses: coldkey addresses(s)
        :param block_hash: the block hash, optional
        :param reuse_block: Whether to reuse the last-used block hash when retrieving info.
        :return: dict of {address: Balance objects}
        """
        results = await self.substrate.query_multiple(
            params=[a for a in addresses],
            storage_function="Account",
            module="System",
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )
        return {k: Balance(v.value["data"]["free"]) for (k, v) in results.items()}

    async def get_total_stake_for_coldkey(
        self,
        *ss58_addresses,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> dict[str, Balance]:
        """
        Returns the total stake held on a coldkey.

        :param ss58_addresses: The SS58 address(es) of the coldkey(s)
        :param block_hash: The hash of the block number to retrieve the stake from.
        :param reuse_block: Whether to reuse the last-used block hash when retrieving info.

        :return: {address: Balance objects}
        """
        results = await self.substrate.query_multiple(
            params=[s for s in ss58_addresses],
            module="SubtensorModule",
            storage_function="TotalColdkeyStake",
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )
        return {
            k: Balance.from_rao(getattr(r, "value", 0)) for (k, r) in results.items()
        }

    async def get_total_stake_for_hotkey(
        self,
        *ss58_addresses,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> dict[str, Balance]:
        """
        Returns the total stake held on a hotkey.

        :param ss58_addresses: The SS58 address(es) of the hotkey(s)
        :param block_hash: The hash of the block number to retrieve the stake from.
        :param reuse_block: Whether to reuse the last-used block hash when retrieving info.

        :return: {address: Balance objects}
        """
        results = await self.substrate.query_multiple(
            params=[s for s in ss58_addresses],
            module="SubtensorModule",
            storage_function="TotalHotkeyStake",
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )
        return {
            k: Balance.from_rao(getattr(r, "value", 0)) for (k, r) in results.items()
        }

    async def get_netuids_for_hotkey(
        self,
        hotkey_ss58: str,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> list[int]:
        """
        Retrieves a list of subnet UIDs (netuids) for which a given hotkey is a member. This function
        identifies the specific subnets within the Bittensor network where the neuron associated with
        the hotkey is active.

        :param hotkey_ss58: The ``SS58`` address of the neuron's hotkey.
        :param block_hash: The hash of the blockchain block number at which to perform the query.
        :param reuse_block: Whether to reuse the last-used block hash when retrieving info.

        :return: A list of netuids where the neuron is a member.
        """

        result = await self.substrate.query_map(
            module="SubtensorModule",
            storage_function="IsNetworkMember",
            params=[hotkey_ss58],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
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
        :param reuse_block: Whether to reuse the last-used block hash.

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
        self,
        param_name: str,
        netuid: int,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> Optional[Any]:
        """
        Retrieves a specified hyperparameter for a specific subnet.

        :param param_name: The name of the hyperparameter to retrieve.
        :param netuid: The unique identifier of the subnet.
        :param block_hash: The hash of blockchain block number for the query.
        :param reuse_block: Whether to reuse the last-used block hash.

        :return: The value of the specified hyperparameter if the subnet exists, or None
        """
        if not await self.subnet_exists(netuid, block_hash):
            return None

        result = await self.substrate.query(
            module="SubtensorModule",
            storage_function=param_name,
            params=[netuid],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )

        if result is None or not hasattr(result, "value"):
            return None

        return result.value

    async def filter_netuids_by_registered_hotkeys(
        self,
        all_netuids: Iterable[int],
        filter_for_netuids: Iterable[int],
        all_hotkeys: Iterable[Wallet],
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> list[int]:
        """
        Filters a given list of all netuids for certain specified netuids and hotkeys

        :param all_netuids: A list of netuids to filter.
        :param filter_for_netuids: A subset of all_netuids to filter from the main list
        :param all_hotkeys: Hotkeys to filter from the main list
        :param block_hash: hash of the blockchain block number at which to perform the query.
        :param reuse_block: whether to reuse the last-used blockchain hash when retrieving info.

        :return: the filtered list of netuids.
        """
        netuids_with_registered_hotkeys = [
            item
            for sublist in await asyncio.gather(
                *[
                    self.get_netuids_for_hotkey(
                        wallet.hotkey.ss58_address,
                        reuse_block=reuse_block,
                        block_hash=block_hash,
                    )
                    for wallet in all_hotkeys
                ]
            )
            for item in sublist
        ]

        if not filter_for_netuids:
            all_netuids = netuids_with_registered_hotkeys

        else:
            all_netuids = [
                netuid for netuid in all_netuids if netuid in filter_for_netuids
            ]
            all_netuids.extend(netuids_with_registered_hotkeys)

        return list(set(all_netuids))

    async def get_existential_deposit(
        self, block_hash: Optional[str] = None, reuse_block: bool = False
    ) -> Balance:
        """
        Retrieves the existential deposit amount for the Bittensor blockchain. The existential deposit
        is the minimum amount of TAO required for an account to exist on the blockchain. Accounts with
        balances below this threshold can be reaped to conserve network resources.

        :param block_hash: Block hash at which to query the deposit amount. If `None`, the current block is used.
        :param reuse_block: Whether to reuse the last-used blockchain block hash.

        :return: The existential deposit amount

        The existential deposit is a fundamental economic parameter in the Bittensor network, ensuring
        efficient use of storage and preventing the proliferation of dust accounts.
        """
        result = await self.substrate.get_constant(
            module_name="Balances",
            constant_name="ExistentialDeposit",
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )

        if result is None or not hasattr(result, "value"):
            raise Exception("Unable to retrieve existential deposit amount.")

        return Balance.from_rao(result.value)

    async def neurons(
        self, netuid: int, block_hash: Optional[str] = None
    ) -> list[NeuronInfo]:
        """
        Retrieves a list of all neurons within a specified subnet of the Bittensor network. This function
        provides a snapshot of the subnet's neuron population, including each neuron's attributes and network
        interactions.

        :param netuid: The unique identifier of the subnet.
        :param block_hash: The hash of the blockchain block number for the query.

        :return: A list of NeuronInfo objects detailing each neuron's characteristics in the subnet.

        Understanding the distribution and status of neurons within a subnet is key to comprehending the
        network's decentralized structure and the dynamics of its consensus and governance processes.
        """
        neurons_lite, weights, bonds = await asyncio.gather(
            self.neurons_lite(netuid=netuid, block_hash=block_hash),
            self.weights(netuid=netuid, block_hash=block_hash),
            self.bonds(netuid=netuid, block_hash=block_hash),
        )

        weights_as_dict = {uid: w for uid, w in weights}
        bonds_as_dict = {uid: b for uid, b in bonds}

        neurons = [
            NeuronInfo.from_weights_bonds_and_neuron_lite(
                neuron_lite, weights_as_dict, bonds_as_dict
            )
            for neuron_lite in neurons_lite
        ]

        return neurons

    async def neurons_lite(
        self, netuid: int, block_hash: Optional[str] = None, reuse_block: bool = False
    ) -> list[NeuronInfoLite]:
        """
        Retrieves a list of neurons in a 'lite' format from a specific subnet of the Bittensor network.
        This function provides a streamlined view of the neurons, focusing on key attributes such as stake
        and network participation.

        :param netuid: The unique identifier of the subnet.
        :param block_hash: The hash of the blockchain block number for the query.
        :param reuse_block: Whether to reuse the last-used blockchain block hash.

        :return: A list of simplified neuron information for the subnet.

        This function offers a quick overview of the neuron population within a subnet, facilitating
        efficient analysis of the network's decentralized structure and neuron dynamics.
        """
        hex_bytes_result = await self.query_runtime_api(
            runtime_api="NeuronInfoRuntimeApi",
            method="get_neurons_lite",
            params=[
                netuid
            ],  # TODO check to see if this can accept more than one at a time
            block_hash=block_hash,
            reuse_block=reuse_block,
        )

        if hex_bytes_result is None:
            return []

        try:
            bytes_result = bytes.fromhex(hex_bytes_result[2:])
        except ValueError:
            bytes_result = bytes.fromhex(hex_bytes_result)

        return NeuronInfoLite.list_from_vec_u8_new(bytes_result)

    async def neuron_for_uid(
        self, uid: Optional[int], netuid: int, block_hash: Optional[str] = None
    ) -> NeuronInfo:
        """
        Retrieves detailed information about a specific neuron identified by its unique identifier (UID)
        within a specified subnet (netuid) of the Bittensor network. This function provides a comprehensive
        view of a neuron's attributes, including its stake, rank, and operational status.


        :param uid: The unique identifier of the neuron.
        :param netuid: The unique identifier of the subnet.
        :param block_hash: The hash of the blockchain block number for the query.

        :return: Detailed information about the neuron if found, a null neuron otherwise

        This function is crucial for analyzing individual neurons' contributions and status within a specific
        subnet, offering insights into their roles in the network's consensus and validation mechanisms.
        """
        if uid is None:
            return NeuronInfo.get_null_neuron()

        params = [netuid, uid, block_hash] if block_hash else [netuid, uid]
        json_body = await self.substrate.rpc_request(
            method="neuronInfo_getNeuron",
            params=params,  # custom rpc method
        )

        if not (result := json_body.get("result", None)):
            return NeuronInfo.get_null_neuron()

        bytes_result = bytes(result)
        return NeuronInfo.from_vec_u8_new(bytes_result)

    async def get_delegated(
        self,
        coldkey_ss58: str,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> list[tuple[DelegateInfo, Balance]]:
        """
        Retrieves a list of delegates and their associated stakes for a given coldkey. This function
        identifies the delegates that a specific account has staked tokens on.

        :param coldkey_ss58: The `SS58` address of the account's coldkey.
        :param block_hash: The hash of the blockchain block number for the query.
        :param reuse_block: Whether to reuse the last-used blockchain block hash.

        :return: A list of tuples, each containing a delegate's information and staked amount.

        This function is important for account holders to understand their stake allocations and their
        involvement in the network's delegation and consensus mechanisms.
        """

        block_hash = (
            block_hash
            if block_hash
            else (self.substrate.last_block_hash if reuse_block else None)
        )
        encoded_coldkey = ss58_to_vec_u8(coldkey_ss58)
        json_body = await self.substrate.rpc_request(
            method="delegateInfo_getDelegated",
            params=([block_hash, encoded_coldkey] if block_hash else [encoded_coldkey]),
        )

        if not (result := json_body.get("result")):
            return []

        return DelegateInfo.delegated_list_from_vec_u8(result)

    async def query_identity(
        self,
        key: str,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> dict:
        """
        Queries the identity of a neuron on the Bittensor blockchain using the given key. This function retrieves
        detailed identity information about a specific neuron, which is a crucial aspect of the network's decentralized
        identity and governance system.

        Note:
        See the `Bittensor CLI documentation <https://docs.bittensor.com/reference/btcli>`_ for supported identity
        parameters.

        :param key: The key used to query the neuron's identity, typically the neuron's SS58 address.
        :param block_hash: The hash of the blockchain block number at which to perform the query.
        :param reuse_block: Whether to reuse the last-used blockchain block hash.

        :return: An object containing the identity information of the neuron if found, ``None`` otherwise.

        The identity information can include various attributes such as the neuron's stake, rank, and other
        network-specific details, providing insights into the neuron's role and status within the Bittensor network.
        """

        def decode_hex_identity_dict(info_dictionary):
            for k, v in info_dictionary.items():
                if isinstance(v, dict):
                    item = list(v.values())[0]
                    if isinstance(item, str) and item.startswith("0x"):
                        try:
                            info_dictionary[k] = bytes.fromhex(item[2:]).decode()
                        except UnicodeDecodeError:
                            print(f"Could not decode: {k}: {item}")
                    else:
                        info_dictionary[k] = item
            return info_dictionary

        identity_info = await self.substrate.query(
            module="Registry",
            storage_function="IdentityOf",
            params=[key],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )
        return decode_hex_identity_dict(identity_info.value["info"])

    async def weights(
        self, netuid: int, block_hash: Optional[str] = None
    ) -> list[tuple[int, list[tuple[int, int]]]]:
        """
        Retrieves the weight distribution set by neurons within a specific subnet of the Bittensor network.
        This function maps each neuron's UID to the weights it assigns to other neurons, reflecting the
        network's trust and value assignment mechanisms.

        Args:
        :param netuid: The network UID of the subnet to query.
        :param block_hash: The hash of the blockchain block for the query.

        :return: A list of tuples mapping each neuron's UID to its assigned weights.

        The weight distribution is a key factor in the network's consensus algorithm and the ranking of neurons,
        influencing their influence and reward allocation within the subnet.
        """
        w_map = []
        w_map_encoded = await self.substrate.query_map(
            module="SubtensorModule",
            storage_function="Weights",
            params=[netuid],
            block_hash=block_hash,
        )

        if w_map_encoded.records:
            for uid, w in w_map_encoded:
                w_map.append((uid.serialize(), w.serialize()))

        return w_map

    async def bonds(
        self, netuid: int, block_hash: Optional[str] = None
    ) -> list[tuple[int, list[tuple[int, int]]]]:
        """
        Retrieves the bond distribution set by neurons within a specific subnet of the Bittensor network.
        Bonds represent the investments or commitments made by neurons in one another, indicating a level
        of trust and perceived value. This bonding mechanism is integral to the network's market-based approach
        to measuring and rewarding machine intelligence.

        :param netuid: The network UID of the subnet to query.
        :param block_hash: The hash of the blockchain block number for the query.

        :return: list of tuples mapping each neuron's UID to its bonds with other neurons.

        Understanding bond distributions is crucial for analyzing the trust dynamics and market behavior
        within the subnet. It reflects how neurons recognize and invest in each other's intelligence and
        contributions, supporting diverse and niche systems within the Bittensor ecosystem.
        """
        b_map = []
        b_map_encoded = await self.substrate.query_map(
            module="SubtensorModule",
            storage_function="Bonds",
            params=[netuid],
            block_hash=block_hash,
        )
        if b_map_encoded.records:
            for uid, b in b_map_encoded:
                b_map.append((uid.serialize(), b.serialize()))

        return b_map

    async def does_hotkey_exist(
        self,
        hotkey_ss58: str,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> bool:
        """
        Returns true if the hotkey is known by the chain and there are accounts.

        :param hotkey_ss58: The SS58 address of the hotkey.
        :param block_hash: The hash of the block number to check the hotkey against.
        :param reuse_block: Whether to reuse the last-used blockchain hash.

        :return: `True` if the hotkey is known by the chain and there are accounts, `False` otherwise.
        """
        result = await self.substrate.query(
            module="SubtensorModule",
            storage_function="Owner",
            params=[hotkey_ss58],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )
        return (
            False
            if getattr(result, "value", None) is None
            else result.value != "5C4hrfjw9DjXZTzV3MwzrrAr9P1MJhSrvWGWqi1eSuyUpnhM"
        )

    async def sign_and_send_extrinsic(
        self,
        call: GenericCall,
        wallet: Wallet,
        wait_for_inclusion: bool = True,
        wait_for_finalization: bool = False,
    ) -> tuple[bool, str]:
        """
        Helper method to sign and submit an extrinsic call to chain.

        :param call: a prepared Call object
        :param wallet: the wallet whose coldkey will be used to sign the extrinsic
        :param wait_for_inclusion: whether to wait until the extrinsic call is included on the chain
        :param wait_for_finalization: whether to wait until the extrinsic call is finalized on the chain

        :return: (success, error message)
        """
        extrinsic = await self.substrate.create_signed_extrinsic(
            call=call, keypair=wallet.coldkey
        )  # sign with coldkey
        response = await self.substrate.submit_extrinsic(
            extrinsic,
            wait_for_inclusion=wait_for_inclusion,
            wait_for_finalization=wait_for_finalization,
        )
        # We only wait here if we expect finalization.
        if not wait_for_finalization and not wait_for_inclusion:
            return True, ""
        response.process_events()
        if response.is_success:
            return True, ""
        else:
            return False, format_error_message(response.error_message)

    async def get_children(self, hotkey, netuid) -> tuple[bool, list, str]:
        """
        This method retrieves the children of a given hotkey and netuid. It queries the SubtensorModule's ChildKeys
        storage function to get the children and formats them before returning as a tuple.

        :param hotkey: The hotkey value.
        :param netuid: The netuid value.

        :return: A tuple containing a boolean indicating success or failure, a list of formatted children, and an error
        message (if applicable)
        """
        try:
            children = await self.substrate.query(
                module="SubtensorModule",
                storage_function="ChildKeys",
                params=[hotkey, netuid],
            )
            if children:
                formatted_children = []
                for proportion, child in children:
                    # Convert U64 to int
                    int_proportion = (
                        proportion.value
                        if hasattr(proportion, "value")
                        else int(proportion)
                    )
                    formatted_children.append((int_proportion, child.value))
                return True, formatted_children, ""
            else:
                return True, [], ""
        except SubstrateRequestException as e:
            return False, [], str(e)

    async def get_subnet_hyperparameters(
        self, netuid: int, block_hash: Optional[str] = None
    ) -> Optional[Union[list, SubnetHyperparameters]]:
        """
        Retrieves the hyperparameters for a specific subnet within the Bittensor network. These hyperparameters
        define the operational settings and rules governing the subnet's behavior.

        :param netuid: The network UID of the subnet to query.
        :param block_hash: The hash of the blockchain block number for the query.

        :return: The subnet's hyperparameters, or `None` if not available.

        Understanding the hyperparameters is crucial for comprehending how subnets are configured and
        managed, and how they interact with the network's consensus and incentive mechanisms.
        """
        hex_bytes_result = await self.query_runtime_api(
            runtime_api="SubnetInfoRuntimeApi",
            method="get_subnet_hyperparams",
            params=[netuid],
            block_hash=block_hash,
        )

        if hex_bytes_result is None:
            return []

        if hex_bytes_result.startswith("0x"):
            bytes_result = bytes.fromhex(hex_bytes_result[2:])
        else:
            bytes_result = bytes.fromhex(hex_bytes_result)

        return SubnetHyperparameters.from_vec_u8(bytes_result)  # type: ignore
