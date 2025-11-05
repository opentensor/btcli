import asyncio
import os
import time
from typing import Optional, Any, Union, TypedDict, Iterable

from async_substrate_interface import AsyncExtrinsicReceipt
from async_substrate_interface.async_substrate import (
    DiskCachedAsyncSubstrateInterface,
    AsyncSubstrateInterface,
)
from async_substrate_interface.errors import SubstrateRequestException
from async_substrate_interface.utils.storage import StorageKey
from bittensor_wallet import Wallet
from bittensor_wallet.bittensor_wallet import Keypair
from bittensor_wallet.utils import SS58_FORMAT
from scalecodec import GenericCall, ScaleBytes
import typer
import websockets

from bittensor_cli.src.bittensor.chain_data import (
    DelegateInfo,
    StakeInfo,
    NeuronInfoLite,
    NeuronInfo,
    SubnetHyperparameters,
    decode_account_id,
    decode_hex_identity,
    DynamicInfo,
    SubnetState,
    MetagraphInfo,
    SimSwapResult,
    CrowdloanData,
)
from bittensor_cli.src import DelegatesDetails
from bittensor_cli.src.bittensor.balances import Balance, fixed_to_float
from bittensor_cli.src import Constants, defaults, TYPE_REGISTRY
from bittensor_cli.src.bittensor.utils import (
    format_error_message,
    console,
    err_console,
    decode_hex_identity_dict,
    validate_chain_endpoint,
    u16_normalized_float,
    U16_MAX,
    get_hotkey_pub_ss58,
)


class ParamWithTypes(TypedDict):
    name: str  # Name of the parameter.
    type: str  # ScaleType string of the parameter.


class ProposalVoteData:
    index: int
    threshold: int
    ayes: list[str]
    nays: list[str]
    end: int

    def __init__(self, proposal_dict: dict) -> None:
        self.index = proposal_dict["index"]
        self.threshold = proposal_dict["threshold"]
        self.ayes = self.decode_ss58_tuples(proposal_dict["ayes"])
        self.nays = self.decode_ss58_tuples(proposal_dict["nays"])
        self.end = proposal_dict["end"]

    @staticmethod
    def decode_ss58_tuples(data: tuple):
        """
        Decodes a tuple of ss58 addresses formatted as bytes tuples
        """
        return [decode_account_id(data[x][0]) for x in range(len(data))]


class SubtensorInterface:
    """
    Thin layer for interacting with Substrate Interface. Mostly a collection of frequently-used calls.
    """

    def __init__(self, network, use_disk_cache: bool = False):
        if network in Constants.network_map:
            self.chain_endpoint = Constants.network_map[network]
            self.network = network
            if network == "local":
                console.log(
                    "[yellow]Warning[/yellow]: Verify your local subtensor is running on port 9944."
                )
        else:
            is_valid, _ = validate_chain_endpoint(network)
            if is_valid:
                self.chain_endpoint = network
                if network in Constants.network_map.values():
                    self.network = next(
                        key
                        for key, value in Constants.network_map.items()
                        if value == network
                    )
                else:
                    self.network = "custom"
            else:
                console.log(
                    f"Network not specified or not valid. Using default chain endpoint: "
                    f"{Constants.network_map[defaults.subtensor.network]}.\n"
                    f"You can set this for commands with the `--network` flag, or by setting this"
                    f" in the config. If you're sure you're using the correct URL, ensure it begins"
                    f" with 'ws://' or 'wss://'"
                )
                self.chain_endpoint = Constants.network_map[defaults.subtensor.network]
                self.network = defaults.subtensor.network
        substrate_class = (
            DiskCachedAsyncSubstrateInterface
            if (use_disk_cache or os.getenv("DISK_CACHE", "0") == "1")
            else AsyncSubstrateInterface
        )
        self.substrate = substrate_class(
            url=self.chain_endpoint,
            ss58_format=SS58_FORMAT,
            type_registry=TYPE_REGISTRY,
            chain_name="Bittensor",
        )

    def __str__(self):
        return f"Network: {self.network}, Chain: {self.chain_endpoint}"

    async def __aenter__(self):
        with console.status(
            f"[yellow]Connecting to Substrate:[/yellow][bold white] {self}..."
        ):
            try:
                await self.substrate.initialize()
                return self
            except TimeoutError:  # TODO verify
                err_console.print(
                    "\n[red]Error[/red]: Timeout occurred connecting to substrate. "
                    f"Verify your chain and network settings: {self}"
                )
                raise typer.Exit(code=1)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.substrate.close()

    async def query(
        self,
        module: str,
        storage_function: str,
        params: Optional[list] = None,
        block_hash: Optional[str] = None,
        raw_storage_key: Optional[bytes] = None,
        subscription_handler=None,
        reuse_block_hash: bool = False,
    ) -> Any:
        """
        Pass-through to substrate.query which automatically returns the .value if it's a ScaleObj
        """
        result = await self.substrate.query(
            module,
            storage_function,
            params,
            block_hash,
            raw_storage_key,
            subscription_handler,
            reuse_block_hash,
        )
        if hasattr(result, "value"):
            return result.value
        else:
            return result

    async def _decode_inline_call(
        self,
        call_option: Any,
        block_hash: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Decode an `Option<BoundedCall>` returned from storage into a structured dictionary.
        """
        if not call_option or "Inline" not in call_option:
            return None
        inline_bytes = bytes(call_option["Inline"][0][0])
        call_obj = await self.substrate.create_scale_object(
            "Call",
            data=ScaleBytes(inline_bytes),
            block_hash=block_hash,
        )
        call_value = call_obj.decode()

        if not isinstance(call_value, dict):
            return None

        call_args = call_value.get("call_args") or []
        args_map: dict[str, dict[str, Any]] = {}
        for arg in call_args:
            if isinstance(arg, dict) and arg.get("name"):
                args_map[arg["name"]] = {
                    "type": arg.get("type"),
                    "value": arg.get("value"),
                }

        return {
            "call_index": call_value.get("call_index"),
            "pallet": call_value.get("call_module"),
            "method": call_value.get("call_function"),
            "args": args_map,
            "hash": call_value.get("call_hash"),
        }

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
        res = []
        async for netuid, exists in result:
            if exists.value:
                res.append(netuid)
        return res

    async def get_stake_for_coldkey(
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

        result = await self.query_runtime_api(
            runtime_api="StakeInfoRuntimeApi",
            method="get_stake_info_for_coldkey",
            params=[coldkey_ss58],
            block_hash=block_hash,
            reuse_block=reuse_block,
        )

        if result is None:
            return []
        stakes: list[StakeInfo] = StakeInfo.list_from_any(result)
        return [stake for stake in stakes if stake.stake > 0]

    async def get_auto_stake_destinations(
        self,
        coldkey_ss58: str,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> dict[int, str]:
        """Retrieve auto-stake destinations configured for a coldkey."""

        query = await self.substrate.query_map(
            module="SubtensorModule",
            storage_function="AutoStakeDestination",
            params=[coldkey_ss58],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )

        destinations: dict[int, str] = {}
        async for netuid, destination in query:
            hotkey_ss58 = decode_account_id(destination.value[0])
            if hotkey_ss58:
                destinations[int(netuid)] = hotkey_ss58

        return destinations

    async def get_stake_for_coldkey_and_hotkey(
        self,
        hotkey_ss58: str,
        coldkey_ss58: str,
        netuid: Optional[int] = None,
        block_hash: Optional[str] = None,
    ) -> Balance:
        """
        Returns the stake under a coldkey - hotkey pairing.

        :param hotkey_ss58: The SS58 address of the hotkey.
        :param coldkey_ss58: The SS58 address of the coldkey.
        :param netuid: The subnet ID to filter by. If provided, only returns stake for this specific
            subnet.
        :param block_hash: The block hash at which to query the stake information.

        :return: Balance: The stake under the coldkey - hotkey pairing.
        """
        alpha_shares, hotkey_alpha, hotkey_shares = await asyncio.gather(
            self.query(
                module="SubtensorModule",
                storage_function="Alpha",
                params=[hotkey_ss58, coldkey_ss58, netuid],
                block_hash=block_hash,
            ),
            self.query(
                module="SubtensorModule",
                storage_function="TotalHotkeyAlpha",
                params=[hotkey_ss58, netuid],
                block_hash=block_hash,
            ),
            self.query(
                module="SubtensorModule",
                storage_function="TotalHotkeyShares",
                params=[hotkey_ss58, netuid],
                block_hash=block_hash,
            ),
        )

        alpha_shares_as_float = fixed_to_float(alpha_shares or 0)
        hotkey_shares_as_float = fixed_to_float(hotkey_shares or 0)

        if hotkey_shares_as_float == 0:
            return Balance.from_rao(0).set_unit(netuid=netuid)

        stake = alpha_shares_as_float / hotkey_shares_as_float * (hotkey_alpha or 0)

        return Balance.from_rao(int(stake)).set_unit(netuid=netuid)

    # Alias
    get_stake = get_stake_for_coldkey_and_hotkey

    async def query_runtime_api(
        self,
        runtime_api: str,
        method: str,
        params: Optional[Union[list, dict]] = None,
        block_hash: Optional[str] = None,
        reuse_block: Optional[bool] = False,
    ) -> Optional[Any]:
        """
        Queries the runtime API of the Bittensor blockchain, providing a way to interact with the underlying
        runtime and retrieve data encoded in Scale Bytes format. This function is essential for advanced users
        who need to interact with specific runtime methods and decode complex data types.

        :param runtime_api: The name of the runtime API to query.
        :param method: The specific method within the runtime API to call.
        :param params: The parameters to pass to the method call.
        :param block_hash: The hash of the blockchain block number at which to perform the query.
        :param reuse_block: Whether to reuse the last-used block hash.

        :return: The decoded result from the runtime API call, or ``None`` if the call fails.

        This function enables access to the deeper layers of the Bittensor blockchain, allowing for detailed
        and specific interactions with the network's runtime environment.
        """
        if reuse_block:
            block_hash = self.substrate.last_block_hash
        result = (
            await self.substrate.runtime_call(runtime_api, method, params, block_hash)
        ).value

        return result

    async def get_balance(
        self,
        address: str,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> Balance:
        """
        Retrieves the balance for a single coldkey address

        :param address: coldkey address
        :param block_hash: the block hash, optional
        :param reuse_block: Whether to reuse the last-used block hash when retrieving info.
        :return: Balance object representing the address's balance
        """
        result = await self.query(
            module="System",
            storage_function="Account",
            params=[address],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )
        value = result or {"data": {"free": 0}}
        return Balance(value["data"]["free"])

    async def get_balances(
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
        if reuse_block:
            block_hash = self.substrate.last_block_hash
        calls = [
            (
                await self.substrate.create_storage_key(
                    "System", "Account", [address], block_hash=block_hash
                )
            )
            for address in addresses
        ]
        batch_call = await self.substrate.query_multi(calls, block_hash=block_hash)
        results = {}
        for item in batch_call:
            value = item[1] or {"data": {"free": 0}}
            results.update({item[0].params[0]: Balance(value["data"]["free"])})
        return results

    async def get_total_stake_for_coldkey(
        self,
        *ss58_addresses,
        block_hash: Optional[str] = None,
    ) -> dict[str, tuple[Balance, Balance]]:
        """
        Returns the total stake held on a coldkey.

        :param ss58_addresses: The SS58 address(es) of the coldkey(s)
        :param block_hash: The hash of the block number to retrieve the stake from.

        :return: {address: Balance objects}
        """
        sub_stakes = await self.get_stake_for_coldkeys(
            list(ss58_addresses), block_hash=block_hash
        )
        # Token pricing info
        dynamic_info = await self.all_subnets()

        results = {}
        for ss58, stake_info_list in sub_stakes.items():
            total_tao_value = Balance(0)
            total_swapped_tao_value = Balance(0)
            for sub_stake in stake_info_list:
                if sub_stake.stake.rao == 0:
                    continue
                netuid = sub_stake.netuid
                pool = dynamic_info[netuid]

                alpha_value = Balance.from_rao(int(sub_stake.stake.rao)).set_unit(
                    netuid
                )

                # Without slippage
                tao_value = pool.alpha_to_tao(alpha_value)
                total_tao_value += tao_value

                # With slippage
                if netuid == 0:
                    swapped_tao_value = tao_value
                else:
                    swapped_tao_value, _, _ = pool.alpha_to_tao_with_slippage(
                        sub_stake.stake
                    )
                total_swapped_tao_value += swapped_tao_value

            results[ss58] = (total_tao_value, total_swapped_tao_value)
        return results

    async def get_total_stake_for_hotkey(
        self,
        *ss58_addresses,
        netuids: Optional[list[int]] = None,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> dict[str, dict[int, Balance]]:
        """
        Returns the total stake held on a hotkey.

        :param ss58_addresses: The SS58 address(es) of the hotkey(s)
        :param netuids: The netuids to retrieve the stake from. If not specified, will use all subnets.
        :param block_hash: The hash of the block number to retrieve the stake from.
        :param reuse_block: Whether to reuse the last-used block hash when retrieving info.

        :return:
            {
                hotkey_ss58_1: {
                    netuid_1: netuid1_stake,
                    netuid_2: netuid2_stake,
                    ...
                },
                hotkey_ss58_2: {
                    netuid_1: netuid1_stake,
                    netuid_2: netuid2_stake,
                    ...
                },
                ...
            }
        """
        if not block_hash:
            if reuse_block:
                block_hash = self.substrate.last_block_hash
            else:
                block_hash = await self.substrate.get_chain_head()

        netuids = netuids or await self.get_all_subnet_netuids(block_hash=block_hash)
        calls = [
            (
                await self.substrate.create_storage_key(
                    "SubtensorModule",
                    "TotalHotkeyAlpha",
                    params=[ss58, netuid],
                    block_hash=block_hash,
                )
            )
            for ss58 in ss58_addresses
            for netuid in netuids
        ]
        query = await self.substrate.query_multi(calls, block_hash=block_hash)
        results: dict[str, dict[int, "Balance"]] = {
            hk_ss58: {} for hk_ss58 in ss58_addresses
        }
        for idx, (_, val) in enumerate(query):
            hotkey_ss58 = ss58_addresses[idx // len(netuids)]
            netuid = netuids[idx % len(netuids)]
            value = (Balance.from_rao(val) if val is not None else Balance(0)).set_unit(
                netuid
            )
            results[hotkey_ss58][netuid] = value
        return results

    async def current_take(
        self,
        hotkey_ss58: str,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> Optional[float]:
        """
        Retrieves the delegate 'take' percentage for a neuron identified by its hotkey. The 'take'
        represents the percentage of rewards that the delegate claims from its nominators' stakes.

        :param hotkey_ss58: The `SS58` address of the neuron's hotkey.
        :param block_hash: The hash of the block number to retrieve the stake from.
        :param reuse_block: Whether to reuse the last-used block hash when retrieving info.

        :return: The delegate take percentage, None if not available.

        The delegate take is a critical parameter in the network's incentive structure, influencing
        the distribution of rewards among neurons and their nominators.
        """
        result = await self.query(
            module="SubtensorModule",
            storage_function="Delegates",
            params=[hotkey_ss58],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )
        if result is None:
            return None
        else:
            return u16_normalized_float(result)

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
        res = []
        async for record in result:
            if record[1].value:
                res.append(record[0])
        return res

    async def is_subnet_active(
        self,
        netuid: int,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> bool:
        """Verify if subnet with provided netuid is active.

        Args:
            netuid (int): The unique identifier of the subnet.
            block_hash (Optional[str]): The blockchain block_hash representation of block id.
            reuse_block (bool): Whether to reuse the last-used block hash.

        Returns:
            True if subnet is active, False otherwise.

        This means whether the `start_call` was initiated or not.
        """
        query = await self.substrate.query(
            module="SubtensorModule",
            storage_function="FirstEmissionBlockNumber",
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
            params=[netuid],
        )
        return True if query and query.value > 0 else False

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
        result = await self.query(
            module="SubtensorModule",
            storage_function="NetworksAdded",
            params=[netuid],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )
        return result

    async def get_subnet_state(
        self, netuid: int, block_hash: Optional[str] = None
    ) -> Optional["SubnetState"]:
        """
        Retrieves the state of a specific subnet within the Bittensor network.

        :param netuid: The network UID of the subnet to query.
        :param block_hash: The hash of the blockchain block number for the query.

        :return: SubnetState object containing the subnet's state information, or None if the subnet doesn't exist.
        """
        result = await self.query_runtime_api(
            runtime_api="SubnetInfoRuntimeApi",
            method="get_subnet_state",
            params=[netuid],
            block_hash=block_hash,
        )

        if result is None:
            return None

        return SubnetState.from_any(result)

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
            print("subnet does not exist")
            return None

        result = await self.query(
            module="SubtensorModule",
            storage_function=param_name,
            params=[netuid],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )

        if result is None:
            return None

        return result

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
                        get_hotkey_pub_ss58(wallet),
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
            filtered_netuids = [
                netuid for netuid in all_netuids if netuid in filter_for_netuids
            ]

            registered_hotkeys_filtered = [
                netuid
                for netuid in netuids_with_registered_hotkeys
                if netuid in filter_for_netuids
            ]

            # Combine both filtered lists
            all_netuids = filtered_netuids + registered_hotkeys_filtered

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
        result = getattr(
            await self.substrate.get_constant(
                module_name="Balances",
                constant_name="ExistentialDeposit",
                block_hash=block_hash,
                reuse_block_hash=reuse_block,
            ),
            "value",
            None,
        )

        if result is None:
            raise Exception("Unable to retrieve existential deposit amount.")

        return Balance.from_rao(result)

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
        result = await self.query_runtime_api(
            runtime_api="NeuronInfoRuntimeApi",
            method="get_neurons_lite",
            params=[netuid],
            block_hash=block_hash,
            reuse_block=reuse_block,
        )

        if result is None:
            return []

        return NeuronInfoLite.list_from_any(result)

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

        result = await self.query_runtime_api(
            runtime_api="NeuronInfoRuntimeApi",
            method="get_neuron",
            params=[
                netuid,
                uid,
            ],  # TODO check to see if this can accept more than one at a time
            block_hash=block_hash,
        )

        if not result:
            return NeuronInfo.get_null_neuron()

        return NeuronInfo.from_any(result)

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
        result = await self.query_runtime_api(
            runtime_api="DelegateInfoRuntimeApi",
            method="get_delegated",
            params=[coldkey_ss58],
            block_hash=block_hash,
        )

        if not result:
            return []

        return DelegateInfo.list_from_any(result)

    async def query_all_identities(
        self,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> dict[str, dict]:
        """
        Queries all identities on the Bittensor blockchain.

        :param block_hash: The hash of the blockchain block number at which to perform the query.
        :param reuse_block: Whether to reuse the last-used blockchain block hash.

        :return: A dictionary mapping addresses to their decoded identity data.
        """

        identities = await self.substrate.query_map(
            module="SubtensorModule",
            storage_function="IdentitiesV2",
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
            fully_exhaust=True,
        )
        all_identities = {}
        for ss58_address, identity in identities.records:
            all_identities[decode_account_id(ss58_address[0])] = decode_hex_identity(
                identity.value
            )

        return all_identities

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
        identity_info = await self.query(
            module="SubtensorModule",
            storage_function="IdentitiesV2",
            params=[key],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )
        if not identity_info:
            return {}
        try:
            return decode_hex_identity(identity_info)
        except TypeError:
            return {}

    async def fetch_coldkey_hotkey_identities(
        self,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> dict[str, dict]:
        """
        Builds a dictionary containing coldkeys and hotkeys with their associated identities and relationships.
        :param block_hash: The hash of the blockchain block number for the query.
        :param reuse_block: Whether to reuse the last-used blockchain block hash.
        :return: Dict with 'coldkeys' and 'hotkeys' as keys.
        """
        if block_hash is None:
            block_hash = await self.substrate.get_chain_head()
        coldkey_identities = await self.query_all_identities(block_hash=block_hash)
        identities = {"coldkeys": {}, "hotkeys": {}}
        sks = [
            await self.substrate.create_storage_key(
                "SubtensorModule", "OwnedHotkeys", [ck], block_hash=block_hash
            )
            for ck in coldkey_identities.keys()
        ]
        query = await self.substrate.query_multi(sks, block_hash=block_hash)

        storage_key: StorageKey
        for storage_key, hotkeys in query:
            coldkey_ss58 = storage_key.params[0]
            coldkey_identity = coldkey_identities.get(coldkey_ss58)

            identities["coldkeys"][coldkey_ss58] = {
                "identity": coldkey_identity,
                "hotkeys": hotkeys,
            }

            for hotkey_ss58 in hotkeys:
                identities["hotkeys"][hotkey_ss58] = {
                    "coldkey": coldkey_ss58,
                    "identity": coldkey_identity,
                }

        return identities

    async def weights(
        self, netuid: int, block_hash: Optional[str] = None
    ) -> list[tuple[int, list[tuple[int, int]]]]:
        """
        Retrieves the weight distribution set by neurons within a specific subnet of the Bittensor network.
        This function maps each neuron's UID to the weights it assigns to other neurons, reflecting the
        network's trust and value assignment mechanisms.

        :param netuid: The network UID of the subnet to query.
        :param block_hash: The hash of the blockchain block for the query.

        :return: A list of tuples mapping each neuron's UID to its assigned weights.

        The weight distribution is a key factor in the network's consensus algorithm and the ranking of neurons,
        influencing their influence and reward allocation within the subnet.
        """
        w_map_encoded = await self.substrate.query_map(
            module="SubtensorModule",
            storage_function="Weights",
            params=[netuid],
            block_hash=block_hash,
        )
        w_map = []
        async for uid, w in w_map_encoded:
            w_map.append((uid, w.value))

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
        b_map_encoded = await self.substrate.query_map(
            module="SubtensorModule",
            storage_function="Bonds",
            params=[netuid],
            block_hash=block_hash,
        )
        b_map = []
        async for uid, b in b_map_encoded:
            b_map.append((uid, b))

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
        result = await self.query(
            module="SubtensorModule",
            storage_function="Owner",
            params=[hotkey_ss58],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )
        return_val = result != "5C4hrfjw9DjXZTzV3MwzrrAr9P1MJhSrvWGWqi1eSuyUpnhM"
        return return_val

    async def get_hotkey_owner(
        self,
        hotkey_ss58: str,
        block_hash: Optional[str] = None,
        check_exists: bool = True,
    ) -> Optional[str]:
        val = await self.query(
            module="SubtensorModule",
            storage_function="Owner",
            params=[hotkey_ss58],
            block_hash=block_hash,
        )
        if check_exists:
            if val:
                exists = await self.does_hotkey_exist(
                    hotkey_ss58, block_hash=block_hash
                )
            else:
                exists = False
        else:
            exists = True
        hotkey_owner = val if exists else None
        return hotkey_owner

    async def sign_and_send_extrinsic(
        self,
        call: GenericCall,
        wallet: Wallet,
        wait_for_inclusion: bool = True,
        wait_for_finalization: bool = False,
        era: Optional[dict[str, int]] = None,
    ) -> tuple[bool, str, Optional[AsyncExtrinsicReceipt]]:
        """
        Helper method to sign and submit an extrinsic call to chain.

        :param call: a prepared Call object
        :param wallet: the wallet whose coldkey will be used to sign the extrinsic
        :param wait_for_inclusion: whether to wait until the extrinsic call is included on the chain
        :param wait_for_finalization: whether to wait until the extrinsic call is finalized on the chain
        :param era: The length (in blocks) for which a transaction should be valid.

        :return: (success, error message)
        """
        call_args: dict[str, Union[GenericCall, Keypair, dict[str, int]]] = {
            "call": call,
            "keypair": wallet.coldkey,
        }
        if era is not None:
            call_args["era"] = era
        extrinsic = await self.substrate.create_signed_extrinsic(
            **call_args
        )  # sign with coldkey
        try:
            response = await self.substrate.submit_extrinsic(
                extrinsic,
                wait_for_inclusion=wait_for_inclusion,
                wait_for_finalization=wait_for_finalization,
            )
            # We only wait here if we expect finalization.
            if not wait_for_finalization and not wait_for_inclusion:
                return True, "", response
            if await response.is_success:
                return True, "", response
            else:
                return False, format_error_message(await response.error_message), None
        except SubstrateRequestException as e:
            return False, format_error_message(e), None

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
            children = await self.query(
                module="SubtensorModule",
                storage_function="ChildKeys",
                params=[hotkey, netuid],
            )
            if children:
                formatted_children = []
                for proportion, child in children:
                    # Convert U64 to int
                    formatted_child = decode_account_id(child[0])
                    int_proportion = int(proportion)
                    formatted_children.append((int_proportion, formatted_child))
                return True, formatted_children, ""
            else:
                return True, [], ""
        except SubstrateRequestException as e:
            return False, [], format_error_message(e)

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
        result = await self.query_runtime_api(
            runtime_api="SubnetInfoRuntimeApi",
            method="get_subnet_hyperparams_v2",
            params=[netuid],
            block_hash=block_hash,
        )
        if not result:
            return []

        return SubnetHyperparameters.from_any(result)

    async def get_subnet_mechanisms(
        self, netuid: int, block_hash: Optional[str] = None
    ) -> int:
        """Return the number of mechanisms that belong to the provided subnet."""

        result = await self.query(
            module="SubtensorModule",
            storage_function="MechanismCountCurrent",
            params=[netuid],
            block_hash=block_hash,
        )

        if result is None:
            return 0
        return int(result)

    async def get_all_subnet_mechanisms(
        self, block_hash: Optional[str] = None
    ) -> dict[int, int]:
        """Return mechanism counts for every subnet with a recorded value."""

        results = await self.substrate.query_map(
            module="SubtensorModule",
            storage_function="MechanismCountCurrent",
            params=[],
            block_hash=block_hash,
        )
        res = {}
        async for netuid, count in results:
            res[int(netuid)] = int(count.value)
        return res

    async def get_mechanism_emission_split(
        self, netuid: int, block_hash: Optional[str] = None
    ) -> list[int]:
        """Return the emission split configured for the provided subnet."""

        result = await self.query(
            module="SubtensorModule",
            storage_function="MechanismEmissionSplit",
            params=[netuid],
            block_hash=block_hash,
        )

        if not result:
            return []

        return [int(value) for value in result]

    async def burn_cost(self, block_hash: Optional[str] = None) -> Optional[Balance]:
        result = await self.query_runtime_api(
            runtime_api="SubnetRegistrationRuntimeApi",
            method="get_network_registration_cost",
            params=[],
            block_hash=block_hash,
        )
        return Balance.from_rao(result) if result is not None else None

    async def get_vote_data(
        self,
        proposal_hash: str,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> Optional["ProposalVoteData"]:
        """
        Retrieves the voting data for a specific proposal on the Bittensor blockchain. This data includes
        information about how senate members have voted on the proposal.

        :param proposal_hash: The hash of the proposal for which voting data is requested.
        :param block_hash: The hash of the blockchain block number to query the voting data.
        :param reuse_block: Whether to reuse the last-used blockchain block hash.

        :return: An object containing the proposal's voting data, or `None` if not found.

        This function is important for tracking and understanding the decision-making processes within
        the Bittensor network, particularly how proposals are received and acted upon by the governing body.
        """
        vote_data = await self.query(
            module="Triumvirate",
            storage_function="Voting",
            params=[proposal_hash],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )
        if vote_data is None:
            return None
        else:
            return ProposalVoteData(vote_data)

    async def get_delegate_identities(
        self, block_hash: Optional[str] = None
    ) -> dict[str, DelegatesDetails]:
        """
        Fetches delegates identities from the chain and GitHub. Preference is given to chain data, and missing info
        is filled-in by the info from GitHub. At some point, we want to totally move away from fetching this info
        from GitHub, but chain data is still limited in that regard.

        :param block_hash: the hash of the blockchain block for the query

        :return: {ss58: DelegatesDetails, ...}

        """
        identities_info = await self.substrate.query_map(
            module="Registry",
            storage_function="IdentityOf",
            block_hash=block_hash,
        )

        all_delegates_details = {}
        async for ss58_address, identity in identities_info:
            all_delegates_details.update(
                {
                    decode_account_id(
                        ss58_address[0]
                    ): DelegatesDetails.from_chain_data(
                        decode_hex_identity_dict(identity.value["info"])
                    )
                }
            )

        return all_delegates_details

    async def get_stake_for_coldkey_and_hotkey_on_netuid(
        self,
        hotkey_ss58: str,
        coldkey_ss58: str,
        netuid: int,
        block_hash: Optional[str] = None,
    ) -> "Balance":
        """Returns the stake under a coldkey - hotkey - netuid pairing"""
        _result = await self.query(
            "SubtensorModule",
            "Alpha",
            [hotkey_ss58, coldkey_ss58, netuid],
            block_hash,
        )
        if _result is None:
            return Balance(0).set_unit(netuid)
        else:
            return Balance.from_rao(fixed_to_float(_result)).set_unit(int(netuid))

    async def get_mechagraph_info(
        self, netuid: int, mech_id: int, block_hash: Optional[str] = None
    ) -> Optional[MetagraphInfo]:
        """
        Returns the metagraph info for a given subnet and mechanism id.
        And yes, it is indeed 'mecha'graph
        """
        query = await self.query_runtime_api(
            runtime_api="SubnetInfoRuntimeApi",
            method="get_mechagraph",
            params=[netuid, mech_id],
            block_hash=block_hash,
        )

        if query is None:
            return None

        return MetagraphInfo.from_any(query)

    async def get_metagraph_info(
        self, netuid: int, block_hash: Optional[str] = None
    ) -> Optional[MetagraphInfo]:
        query = await self.query_runtime_api(
            runtime_api="SubnetInfoRuntimeApi",
            method="get_metagraph",
            params=[netuid],
            block_hash=block_hash,
        )

        if query is None:
            return None

        return MetagraphInfo.from_any(query)

    async def get_all_metagraphs_info(
        self, block_hash: Optional[str] = None
    ) -> list[MetagraphInfo]:
        query = await self.query_runtime_api(
            runtime_api="SubnetInfoRuntimeApi",
            method="get_all_metagraphs",
            params=[],
            block_hash=block_hash,
        )

        return MetagraphInfo.list_from_any(query)

    async def multi_get_stake_for_coldkey_and_hotkey_on_netuid(
        self,
        hotkey_ss58s: list[str],
        coldkey_ss58: str,
        netuids: list[int],
        block_hash: Optional[str] = None,
    ) -> dict[str, dict[int, "Balance"]]:
        """
        Queries the stake for multiple hotkey - coldkey - netuid pairings.

        :param hotkey_ss58s: list of hotkey ss58 addresses
        :param coldkey_ss58: a single coldkey ss58 address
        :param netuids: list of netuids
        :param block_hash: hash of the blockchain block, if any

        :return:
            {
                hotkey_ss58_1: {
                    netuid_1: netuid1_stake,
                    netuid_2: netuid2_stake,
                    ...
                },
                hotkey_ss58_2: {
                    netuid_1: netuid1_stake,
                    netuid_2: netuid2_stake,
                    ...
                },
                ...
            }

        """
        calls = [
            (
                await self.substrate.create_storage_key(
                    "SubtensorModule",
                    "Alpha",
                    [hk_ss58, coldkey_ss58, netuid],
                    block_hash=block_hash,
                )
            )
            for hk_ss58 in hotkey_ss58s
            for netuid in netuids
        ]
        batch_call = await self.substrate.query_multi(calls, block_hash=block_hash)
        results: dict[str, dict[int, "Balance"]] = {
            hk_ss58: {} for hk_ss58 in hotkey_ss58s
        }
        for idx, (_, val) in enumerate(batch_call):
            hotkey_idx = idx // len(netuids)
            netuid_idx = idx % len(netuids)
            hotkey_ss58 = hotkey_ss58s[hotkey_idx]
            netuid = netuids[netuid_idx]
            value = (
                Balance.from_rao(val).set_unit(netuid)
                if val is not None
                else Balance(0).set_unit(netuid)
            )
            results[hotkey_ss58][netuid] = value
        return results

    async def get_stake_for_coldkeys(
        self, coldkey_ss58_list: list[str], block_hash: Optional[str] = None
    ) -> Optional[dict[str, list[StakeInfo]]]:
        """
        Retrieves stake information for a list of coldkeys. This function aggregates stake data for multiple
        accounts, providing a collective view of their stakes and delegations.

        :param coldkey_ss58_list: A list of SS58 addresses of the accounts' coldkeys.
        :param block_hash: The blockchain block number for the query.

        :return: A dictionary mapping each coldkey to a list of its StakeInfo objects.

        This function is useful for analyzing the stake distribution and delegation patterns of multiple
        accounts simultaneously, offering a broader perspective on network participation and investment strategies.
        """
        batch_size = 60

        tasks = []
        for i in range(0, len(coldkey_ss58_list), batch_size):
            ss58_chunk = coldkey_ss58_list[i : i + batch_size]
            tasks.append(
                self.query_runtime_api(
                    runtime_api="StakeInfoRuntimeApi",
                    method="get_stake_info_for_coldkeys",
                    params=[ss58_chunk],
                    block_hash=block_hash,
                )
            )
        results = await asyncio.gather(*tasks)
        stake_info_map = {}
        for result in results:
            if result is None:
                continue
            for coldkey_bytes, stake_info_list in result:
                coldkey_ss58 = decode_account_id(coldkey_bytes)
                stake_info_map[coldkey_ss58] = StakeInfo.list_from_any(stake_info_list)

        return stake_info_map if stake_info_map else None

    async def all_subnets(self, block_hash: Optional[str] = None) -> list[DynamicInfo]:
        result, prices = await asyncio.gather(
            self.query_runtime_api(
                "SubnetInfoRuntimeApi",
                "get_all_dynamic_info",
                block_hash=block_hash,
            ),
            self.get_subnet_prices(block_hash=block_hash, page_size=129),
        )
        sns: list[DynamicInfo] = DynamicInfo.list_from_any(result)
        for sn in sns:
            if sn.netuid == 0:
                sn.price = Balance.from_tao(1.0)
            else:
                try:
                    sn.price = prices[sn.netuid]
                except KeyError:
                    sn.price = sn.tao_in / sn.alpha_in
        return sns

    async def subnet(
        self, netuid: int, block_hash: Optional[str] = None
    ) -> "DynamicInfo":
        result, price = await asyncio.gather(
            self.query_runtime_api(
                "SubnetInfoRuntimeApi",
                "get_dynamic_info",
                params=[netuid],
                block_hash=block_hash,
            ),
            self.get_subnet_price(netuid=netuid, block_hash=block_hash),
        )
        if not result:
            raise ValueError(f"Subnet {netuid} not found")
        subnet_ = DynamicInfo.from_any(result)
        subnet_.price = price if netuid != 0 else Balance.from_tao(1.0)
        return subnet_

    async def get_owned_hotkeys(
        self,
        coldkey_ss58: str,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> list[str]:
        """
        Retrieves all hotkeys owned by a specific coldkey address.

        :param coldkey_ss58: The SS58 address of the coldkey to query.
        :param block_hash: The hash of the blockchain block number for the query.
        :param reuse_block: Whether to reuse the last-used blockchain block hash.

        :return: A list of hotkey SS58 addresses owned by the coldkey.
        """
        owned_hotkeys = await self.query(
            module="SubtensorModule",
            storage_function="OwnedHotkeys",
            params=[coldkey_ss58],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )

        return [decode_account_id(hotkey[0]) for hotkey in owned_hotkeys or []]

    async def get_extrinsic_fee(self, call: GenericCall, keypair: Keypair) -> Balance:
        """
        Determines the fee for the extrinsic call.
        Args:
            call: Created extrinsic call
            keypair: The keypair that would sign the extrinsic (usually you would just want to use the *pub for this)

        Returns:
            Balance object representing the fee for this extrinsic.
        """
        fee_dict = await self.substrate.get_payment_info(call, keypair)
        return Balance.from_rao(fee_dict["partial_fee"])

    async def sim_swap(
        self,
        origin_netuid: int,
        destination_netuid: int,
        amount: int,
        block_hash: Optional[str] = None,
    ) -> SimSwapResult:
        """
        Hits the SimSwap Runtime API to calculate the fee and result for a given transaction. This should be used
        instead of get_stake_fee for staking fee calculations. The SimSwapResult contains the staking fees and expected
        returned amounts of a given transaction. This does not include the transaction (extrinsic) fee.

        Args:
            origin_netuid: Netuid of the source subnet (0 if new stake)
            destination_netuid: Netuid of the destination subnet
            amount: Amount to transfer in Rao
            block_hash: The hash of the blockchain block number for the query.

        Returns:
            SimSwapResult object representing the result
        """
        block_hash = block_hash or await self.substrate.get_chain_head()
        if origin_netuid > 0 and destination_netuid > 0:
            # for cross-subnet moves where neither origin nor destination is root
            intermediate_result_, sn_price = await asyncio.gather(
                self.query_runtime_api(
                    "SwapRuntimeApi",
                    "sim_swap_alpha_for_tao",
                    params={"netuid": origin_netuid, "alpha": amount},
                    block_hash=block_hash,
                ),
                self.get_subnet_price(origin_netuid, block_hash=block_hash),
            )
            intermediate_result = SimSwapResult.from_dict(
                intermediate_result_, origin_netuid
            )
            result = SimSwapResult.from_dict(
                await self.query_runtime_api(
                    "SwapRuntimeApi",
                    "sim_swap_tao_for_alpha",
                    params={
                        "netuid": destination_netuid,
                        "tao": intermediate_result.tao_amount.rao,
                    },
                    block_hash=block_hash,
                ),
                destination_netuid,
            )
            secondary_fee = (result.tao_fee / sn_price.tao).set_unit(origin_netuid)
            result.alpha_fee = result.alpha_fee + secondary_fee
            return result
        elif origin_netuid > 0:
            # dynamic to tao
            return SimSwapResult.from_dict(
                await self.query_runtime_api(
                    "SwapRuntimeApi",
                    "sim_swap_alpha_for_tao",
                    params={"netuid": origin_netuid, "alpha": amount},
                    block_hash=block_hash,
                ),
                origin_netuid,
            )
        else:
            # tao to dynamic or unstaked to staked tao (SN0)
            return SimSwapResult.from_dict(
                await self.query_runtime_api(
                    "SwapRuntimeApi",
                    "sim_swap_tao_for_alpha",
                    params={"netuid": destination_netuid, "tao": amount},
                    block_hash=block_hash,
                ),
                destination_netuid,
            )

    async def get_scheduled_coldkey_swap(
        self,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> Optional[list[str]]:
        """
        Queries the chain to fetch the list of coldkeys that are scheduled for a swap.

        :param block_hash: Block hash at which to perform query.
        :param reuse_block: Whether to reuse the last-used block hash.

        :return: A list of SS58 addresses of the coldkeys that are scheduled for a coldkey swap.
        """
        result = await self.substrate.query_map(
            module="SubtensorModule",
            storage_function="ColdkeySwapScheduled",
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )

        keys_pending_swap = []
        async for ss58, _ in result:
            keys_pending_swap.append(decode_account_id(ss58))
        return keys_pending_swap

    async def get_crowdloans(
        self, block_hash: Optional[str] = None
    ) -> list[CrowdloanData]:
        """Retrieves all crowdloans from the network.

        Args:
            block_hash (Optional[str]): The blockchain block hash at which to perform the query.

        Returns:
            dict[int, CrowdloanData]: A dictionary mapping crowdloan IDs to CrowdloanData objects
                containing details such as creator, deposit, cap, raised amount, and finalization status.

        This function fetches information about all crowdloans
        """
        crowdloans_data = await self.substrate.query_map(
            module="Crowdloan",
            storage_function="Crowdloans",
            block_hash=block_hash,
            fully_exhaust=True,
        )
        crowdloans = {}
        async for fund_id, fund_info in crowdloans_data:
            decoded_call = await self._decode_inline_call(
                fund_info["call"],
                block_hash=block_hash,
            )
            info_dict = dict(fund_info.value)
            info_dict["call_details"] = decoded_call
            crowdloans[fund_id] = CrowdloanData.from_any(info_dict)

        return crowdloans

    async def get_single_crowdloan(
        self,
        crowdloan_id: int,
        block_hash: Optional[str] = None,
    ) -> Optional[CrowdloanData]:
        """Retrieves detailed information about a specific crowdloan.

        Args:
            crowdloan_id (int): The unique identifier of the crowdloan to retrieve.
            block_hash (Optional[str]): The blockchain block hash at which to perform the query.

        Returns:
            Optional[CrowdloanData]: A CrowdloanData object containing the crowdloan's details if found,
                None if the crowdloan does not exist.

        The returned data includes crowdloan details such as funding targets,
        contribution minimums, timeline, and current funding status
        """
        crowdloan_info = await self.query(
            module="Crowdloan",
            storage_function="Crowdloans",
            params=[crowdloan_id],
            block_hash=block_hash,
        )
        if crowdloan_info:
            decoded_call = await self._decode_inline_call(
                crowdloan_info.get("call"),
                block_hash=block_hash,
            )
            crowdloan_info["call_details"] = decoded_call
            return CrowdloanData.from_any(crowdloan_info)
        return None

    async def get_crowdloan_contribution(
        self,
        crowdloan_id: int,
        contributor: str,
        block_hash: Optional[str] = None,
    ) -> Optional[Balance]:
        """Retrieves a user's contribution to a specific crowdloan.

        Args:
            crowdloan_id (int): The ID of the crowdloan.
            contributor (str): The SS58 address of the contributor.
            block_hash (Optional[str]): The blockchain block hash at which to perform the query.

        Returns:
            Optional[Balance]: The contribution amount as a Balance object if found, None otherwise.

        This function queries the Contributions storage to find the amount a specific address
        has contributed to a given crowdloan.
        """
        contribution = await self.query(
            module="Crowdloan",
            storage_function="Contributions",
            params=[crowdloan_id, contributor],
            block_hash=block_hash,
        )

        if contribution:
            return Balance.from_rao(contribution)
        return None

    async def get_coldkey_swap_schedule_duration(
        self,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> int:
        """
        Retrieves the duration (in blocks) required for a coldkey swap to be executed.

        Args:
            block_hash: The hash of the blockchain block number for the query.
            reuse_block: Whether to reuse the last-used blockchain block hash.

        Returns:
            int: The number of blocks required for the coldkey swap schedule duration.
        """
        result = await self.query(
            module="SubtensorModule",
            storage_function="ColdkeySwapScheduleDuration",
            params=[],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )

        return result

    async def get_coldkey_claim_type(
        self,
        coldkey_ss58: str,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> str:
        """
        Retrieves the root claim type for a specific coldkey.

        Root claim types control how staking emissions are handled on the ROOT network (subnet 0):
        - "Swap": Future Root Alpha Emissions are swapped to TAO at claim time and added to your root stake
        - "Keep": Future Root Alpha Emissions are kept as Alpha

        Args:
            coldkey_ss58: The SS58 address of the coldkey to query.
            block_hash: The hash of the blockchain block number for the query.
            reuse_block: Whether to reuse the last-used blockchain block hash.

        Returns:
            str: The root claim type for the coldkey ("Swap" or "Keep").
        """
        result = await self.query(
            module="SubtensorModule",
            storage_function="RootClaimType",
            params=[coldkey_ss58],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )

        if result is None:
            return "Swap"
        return next(iter(result.keys()))

    async def get_all_coldkeys_claim_type(
        self,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> dict[str, str]:
        """
        Retrieves all root claim types for all coldkeys in the network.

        Args:
            block_hash: The hash of the blockchain block number for the query.
            reuse_block: Whether to reuse the last-used blockchain block hash.

        Returns:
            dict[str, str]: A dictionary mapping coldkey SS58 addresses to their root claim type ("Keep" or "Swap").
        """
        result = await self.substrate.query_map(
            module="SubtensorModule",
            storage_function="RootClaimType",
            params=[],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )

        root_claim_types = {}
        async for coldkey, claim_type in result:
            coldkey_ss58 = decode_account_id(coldkey[0])
            claim_type = next(iter(claim_type.value.keys()))
            root_claim_types[coldkey_ss58] = claim_type

        return root_claim_types

    async def get_staking_hotkeys(
        self,
        coldkey_ss58: str,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> list[str]:
        """Retrieves all hotkeys that a coldkey is staking to.

        Args:
            coldkey_ss58: The SS58 address of the coldkey.
            block_hash: The hash of the blockchain block for the query.
            reuse_block: Whether to reuse the last-used blockchain block hash.

        Returns:
            list[str]: A list of hotkey SS58 addresses that the coldkey has staked to.
        """
        result = await self.query(
            module="SubtensorModule",
            storage_function="StakingHotkeys",
            params=[coldkey_ss58],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )
        staked_hotkeys = [decode_account_id(hotkey) for hotkey in result]
        return staked_hotkeys

    async def get_claimed_amount(
        self,
        coldkey_ss58: str,
        hotkey_ss58: str,
        netuid: int,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> Balance:
        """Retrieves the root claimed Alpha shares for coldkey from hotkey in provided subnet.

        Args:
            coldkey_ss58: The SS58 address of the staker.
            hotkey_ss58: The SS58 address of the root validator.
            netuid: The unique identifier of the subnet.
            block_hash: The blockchain block hash for the query.
            reuse_block: Whether to reuse the last-used blockchain block hash.

        Returns:
            Balance: The number of Alpha stake claimed from the root validator.
        """
        query = await self.query(
            module="SubtensorModule",
            storage_function="RootClaimed",
            params=[netuid, hotkey_ss58, coldkey_ss58],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )
        return Balance.from_rao(query).set_unit(netuid=netuid)

    async def get_claimed_amount_all_netuids(
        self,
        coldkey_ss58: str,
        hotkey_ss58: str,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> dict[int, Balance]:
        """Retrieves the root claimed Alpha shares for coldkey from hotkey in all subnets.

        Args:
            coldkey_ss58: The SS58 address of the staker.
            hotkey_ss58: The SS58 address of the root validator.
            block_hash: The blockchain block hash for the query.
            reuse_block: Whether to reuse the last-used blockchain block hash.

        Returns:
            dict[int, Balance]: Dictionary mapping netuid to claimed stake.
        """
        query = await self.substrate.query_map(
            module="SubtensorModule",
            storage_function="RootClaimed",
            params=[hotkey_ss58, coldkey_ss58],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )
        total_claimed = {}
        async for netuid, claimed in query:
            total_claimed[netuid] = Balance.from_rao(claimed.value).set_unit(
                netuid=netuid
            )
        return total_claimed

    async def get_claimable_rate_all_netuids(
        self,
        hotkey_ss58: str,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> dict[int, float]:
        """Retrieves all root claimable rates from a given hotkey address for all subnets with this validator.

        Args:
            hotkey_ss58: The SS58 address of the root validator.
            block_hash: The blockchain block hash for the query.
            reuse_block: Whether to reuse the last-used blockchain block hash.

        Returns:
            dict[int, float]: Dictionary mapping netuid to claimable rate.
        """
        query = await self.query(
            module="SubtensorModule",
            storage_function="RootClaimable",
            params=[hotkey_ss58],
            block_hash=block_hash,
            reuse_block_hash=reuse_block,
        )

        if not query:
            return {}

        bits_list = next(iter(query))
        return {bits[0]: fixed_to_float(bits[1], frac_bits=32) for bits in bits_list}

    async def get_claimable_rate_netuid(
        self,
        hotkey_ss58: str,
        netuid: int,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> float:
        """Retrieves the root claimable rate from a given hotkey address for provided netuid.

        Args:
            hotkey_ss58: The SS58 address of the root validator.
            netuid: The unique identifier of the subnet to get the rate.
            block_hash: The blockchain block hash for the query.
            reuse_block: Whether to reuse the last-used blockchain block hash.

        Returns:
            float: The rate of claimable stake from validator's hotkey for provided subnet.
        """
        all_rates = await self.get_claimable_rate_all_netuids(
            hotkey_ss58=hotkey_ss58,
            block_hash=block_hash,
            reuse_block=reuse_block,
        )
        return all_rates.get(netuid, 0.0)

    async def get_claimable_stake_for_netuid(
        self,
        coldkey_ss58: str,
        hotkey_ss58: str,
        netuid: int,
        block_hash: Optional[str] = None,
        reuse_block: bool = False,
    ) -> Balance:
        """Retrieves the root claimable stake for a given coldkey address.

        Args:
            coldkey_ss58: Delegate's ColdKey SS58 address.
            hotkey_ss58: The root validator hotkey SS58 address.
            netuid: Delegate's netuid where stake will be claimed.
            block_hash: The blockchain block hash for the query.
            reuse_block: Whether to reuse the last-used blockchain block hash.

        Returns:
            Balance: Available for claiming root stake.

        Note:
            After manual claim, claimable (available) stake will be added to subnet stake.
        """
        root_stake, root_claimable_rate, root_claimed = await asyncio.gather(
            self.get_stake_for_coldkey_and_hotkey_on_netuid(
                coldkey_ss58=coldkey_ss58,
                hotkey_ss58=hotkey_ss58,
                netuid=0,
                block_hash=block_hash,
            ),
            self.get_claimable_rate_netuid(
                hotkey_ss58=hotkey_ss58,
                netuid=netuid,
                block_hash=block_hash,
                reuse_block=reuse_block,
            ),
            self.get_claimed_amount(
                coldkey_ss58=coldkey_ss58,
                hotkey_ss58=hotkey_ss58,
                netuid=netuid,
                block_hash=block_hash,
                reuse_block=reuse_block,
            ),
        )

        root_claimable_stake = (root_claimable_rate * root_stake).set_unit(
            netuid=netuid
        )
        # Return the difference (what's left to claim)
        return max(
            root_claimable_stake - root_claimed,
            Balance.from_rao(0).set_unit(netuid=netuid),
        )

    async def get_claimable_stakes_for_coldkey(
        self,
        coldkey_ss58: str,
        stakes_info: list["StakeInfo"],
        block_hash: Optional[str] = None,
    ) -> dict[str, dict[int, "Balance"]]:
        """Batch query claimable stakes for multiple hotkey-netuid pairs.

        Args:
            coldkey_ss58: The coldkey SS58 address.
            stakes_info: List of StakeInfo objects containing stake data.
            block_hash: Optional block hash for the query.

        Returns:
            dict[str, dict[int, Balance]]: Mapping of hotkey to netuid to claimable Balance.
        """
        if not stakes_info:
            return {}

        root_stakes = {}
        for stake_info in stakes_info:
            if stake_info.netuid == 0 and stake_info.stake.rao > 0:
                root_stakes[stake_info.hotkey_ss58] = stake_info.stake

        target_pairs = []
        for s in stakes_info:
            if s.netuid != 0 and s.stake.rao > 0 and s.hotkey_ss58 in root_stakes:
                pair = (s.hotkey_ss58, s.netuid)
                target_pairs.append(pair)

        if not target_pairs:
            return {}

        unique_hotkeys = list(set(h for h, _ in target_pairs))
        if not unique_hotkeys:
            return {}

        batch_claimable_calls = []
        batch_claimed_calls = []

        # Get the claimable rate
        for hotkey in unique_hotkeys:
            batch_claimable_calls.append(
                await self.substrate.create_storage_key(
                    "SubtensorModule", "RootClaimable", [hotkey], block_hash=block_hash
                )
            )

        # Get already claimed
        claimed_pairs = target_pairs
        for hotkey, netuid in claimed_pairs:
            batch_claimed_calls.append(
                await self.substrate.create_storage_key(
                    "SubtensorModule",
                    "RootClaimed",
                    [netuid, hotkey, coldkey_ss58],
                    block_hash=block_hash,
                )
            )

        batch_claimable, batch_claimed = await asyncio.gather(
            self.substrate.query_multi(batch_claimable_calls, block_hash=block_hash),
            self.substrate.query_multi(batch_claimed_calls, block_hash=block_hash),
        )

        claimable_rates = {}
        claimed_amounts = {}
        for idx, (_, result) in enumerate(batch_claimable):
            hotkey = unique_hotkeys[idx]
            if result:
                for netuid, rate in result:
                    if hotkey not in claimable_rates:
                        claimable_rates[hotkey] = {}
                    claimable_rates[hotkey][netuid] = fixed_to_float(rate, frac_bits=32)

        for idx, (_, result) in enumerate(batch_claimed):
            hotkey, netuid = claimed_pairs[idx]
            value = result or 0
            claimed_amounts[(hotkey, netuid)] = Balance.from_rao(value).set_unit(netuid)

        # Calculate the claimable stake for each pair
        results = {}
        for hotkey, netuid in target_pairs:
            root_stake = root_stakes[hotkey]
            rate = claimable_rates[hotkey].get(netuid, 0)
            claimable_stake = rate * root_stake
            already_claimed = claimed_amounts.get((hotkey, netuid), 0)
            net_claimable = max(claimable_stake - already_claimed, 0)
            if hotkey not in results:
                results[hotkey] = {}
            results[hotkey][netuid] = net_claimable.set_unit(netuid)
        return results

    async def get_subnet_price(
        self,
        netuid: int = None,
        block_hash: Optional[str] = None,
    ) -> Balance:
        """
        Gets the current Alpha price in TAO for a specific subnet.

        :param netuid: The unique identifier of the subnet.
        :param block_hash: The hash of the block to retrieve the price from.

        :return: The current Alpha price in TAO units for the specified subnet.
        """
        current_sqrt_price = await self.query(
            module="Swap",
            storage_function="AlphaSqrtPrice",
            params=[netuid],
            block_hash=block_hash,
        )

        current_sqrt_price = fixed_to_float(current_sqrt_price)
        current_price = current_sqrt_price * current_sqrt_price
        return Balance.from_rao(int(current_price * 1e9))

    async def get_subnet_prices(
        self, block_hash: Optional[str] = None, page_size: int = 100
    ) -> dict[int, Balance]:
        """
        Gets the current Alpha prices in TAO for all subnets.

        :param block_hash: The hash of the block to retrieve prices from.
        :param page_size: The page size for batch queries (default: 100).

        :return: A dictionary mapping netuid to the current Alpha price in TAO units.
        """
        query = await self.substrate.query_map(
            module="Swap",
            storage_function="AlphaSqrtPrice",
            page_size=page_size,
            block_hash=block_hash,
        )

        map_ = {}
        async for netuid_, current_sqrt_price in query:
            current_sqrt_price_ = fixed_to_float(current_sqrt_price.value)
            current_price = current_sqrt_price_**2
            map_[netuid_] = Balance.from_rao(int(current_price * 1e9))

        return map_

    async def get_all_subnet_ema_tao_inflow(
        self,
        block_hash: Optional[str] = None,
        page_size: int = 100,
    ) -> dict[int, Balance]:
        """
        Query EMA TAO inflow for all subnets.

        This represents the exponential moving average of TAO flowing
        into or out of a subnet. Negative values indicate net outflow.

        Args:
            block_hash: Optional block hash to query at.
            page_size: The page size for batch queries (default: 100).

        Returns:
            Dict mapping netuid -> Balance(EMA TAO inflow).
        """
        query = await self.substrate.query_map(
            module="SubtensorModule",
            storage_function="SubnetEmaTaoFlow",
            page_size=page_size,
            block_hash=block_hash,
        )
        ema_map = {}
        async for netuid, value in query:
            if not value:
                ema_map[netuid] = Balance.from_rao(0)
            else:
                _, raw_ema_value = value
                ema_value = fixed_to_float(raw_ema_value)
                ema_map[netuid] = Balance.from_rao(ema_value)
        return ema_map

    async def get_subnet_ema_tao_inflow(
        self,
        netuid: int,
        block_hash: Optional[str] = None,
    ) -> Balance:
        """
        Query EMA TAO inflow for a specific subnet.

        This represents the exponential moving average of TAO flowing
        into or out of a subnet. Negative values indicate net outflow.

        Args:
            netuid: The unique identifier of the subnet.
            block_hash: Optional block hash to query at.

        Returns:
            Balance(EMA TAO inflow).
        """
        value = await self.substrate.query(
            module="SubtensorModule",
            storage_function="SubnetEmaTaoFlow",
            params=[netuid],
            block_hash=block_hash,
        )
        if not value:
            return Balance.from_rao(0)
        _, raw_ema_value = value
        ema_value = fixed_to_float(raw_ema_value)
        return Balance.from_rao(ema_value)


async def best_connection(networks: list[str]):
    """
    Basic function to compare the latency of a given list of websocket endpoints
    Args:
        networks: list of network URIs

    Returns:
        {network_name: [end_to_end_latency, single_request_latency, chain_head_request_latency]}

    """
    results = {}
    for network in networks:
        try:
            t1 = time.monotonic()
            async with websockets.connect(network) as websocket:
                pong = await websocket.ping()
                latency = await pong
                pt1 = time.monotonic()
                await websocket.send(
                    "{'jsonrpc': '2.0', 'method': 'chain_getHead', 'params': [], 'id': '82'}"
                )
                await websocket.recv()
                t2 = time.monotonic()
            results[network] = [t2 - t1, latency, t2 - pt1]
        except Exception as e:
            err_console.print(f"Error attempting network {network}: {e}")
    return results
