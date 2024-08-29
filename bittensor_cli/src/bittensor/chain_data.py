from dataclasses import dataclass
from enum import Enum
from typing import Optional, Any, Union
import warnings

import bt_decode
import netaddr
from scalecodec import ScaleBytes
from scalecodec.base import RuntimeConfiguration
from scalecodec.type_registry import load_type_registry_preset
from scalecodec.utils.ss58 import ss58_encode

from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.extrinsics.registration import use_torch, torch
from bittensor_cli.src.bittensor.networking import int_to_ip
from bittensor_cli.src.utils import SS58_FORMAT, u16_normalized_float, RAO_PER_TAO


class ChainDataType(Enum):
    NeuronInfo = 1
    SubnetInfo = 2
    DelegateInfo = 3
    NeuronInfoLite = 4
    DelegatedInfo = 5
    StakeInfo = 6
    IPInfo = 7
    SubnetHyperparameters = 8


def from_scale_encoding(
    input_: Union[list[int], bytes, ScaleBytes],
    type_name: ChainDataType,
    is_vec: bool = False,
    is_option: bool = False,
) -> Optional[dict]:
    """
    Decodes input_ data from SCALE encoding based on the specified type name and modifiers.

    :param input_: The input data to decode.
    :param type_name:The type of data being decoded.
    :param is_vec:: Whether the data is a vector of the specified type.
    :param is_option: Whether the data is an optional value of the specified type.

    :return: The decoded data as a dictionary, or `None` if the decoding fails.
    """
    type_string = type_name.name
    if type_name == ChainDataType.DelegatedInfo:
        # DelegatedInfo is a tuple of (DelegateInfo, Compact<u64>)
        type_string = f"({ChainDataType.DelegateInfo.name}, Compact<u64>)"
    if is_option:
        type_string = f"Option<{type_string}>"
    if is_vec:
        type_string = f"Vec<{type_string}>"

    return from_scale_encoding_using_type_string(input_, type_string)


def from_scale_encoding_using_type_string(
    input_: Union[list[int], bytes, ScaleBytes], type_string: str
) -> Optional[dict]:
    if isinstance(input_, ScaleBytes):
        as_scale_bytes = input_
    else:
        if isinstance(input_, list) and all([isinstance(i, int) for i in input_]):
            vec_u8 = input_
            as_bytes = bytes(vec_u8)
        elif isinstance(input_, bytes):
            as_bytes = input_
        else:
            raise TypeError("input_ must be a list[int], bytes, or ScaleBytes")

        as_scale_bytes = ScaleBytes(as_bytes)

    rpc_runtime_config = RuntimeConfiguration()
    rpc_runtime_config.update_type_registry(load_type_registry_preset("legacy"))
    rpc_runtime_config.update_type_registry(custom_rpc_type_registry)

    obj = rpc_runtime_config.create_scale_object(type_string, data=as_scale_bytes)

    return obj.decode()


def decode_account_id(account_id_bytes):
    # Convert the AccountId bytes to a Base64 string
    return ss58_encode(bytes(account_id_bytes).hex(), SS58_FORMAT)


def process_stake_data(stake_data):
    decoded_stake_data = {}
    for account_id_bytes, stake_ in stake_data:
        account_id = decode_account_id(account_id_bytes)
        decoded_stake_data.update({account_id: Balance.from_rao(stake_)})
    return decoded_stake_data


@dataclass
class AxonInfo:
    version: int
    ip: str
    port: int
    ip_type: int
    hotkey: str
    coldkey: str
    protocol: int = 4
    placeholder1: int = 0
    placeholder2: int = 0

    @property
    def is_serving(self) -> bool:
        """True if the endpoint is serving."""
        return self.ip != "0.0.0.0"

    @classmethod
    def from_neuron_info(cls, neuron_info: dict) -> "AxonInfo":
        """
        Converts a dictionary to an AxonInfo object.

        Args:
            neuron_info (dict): A dictionary containing the neuron information.

        Returns:
            instance (AxonInfo): An instance of AxonInfo created from the dictionary.
        """
        return cls(
            version=neuron_info["axon_info"]["version"],
            ip=int_to_ip(int(neuron_info["axon_info"]["ip"])),
            port=neuron_info["axon_info"]["port"],
            ip_type=neuron_info["axon_info"]["ip_type"],
            hotkey=neuron_info["hotkey"],
            coldkey=neuron_info["coldkey"],
        )


@dataclass
class SubnetHyperparameters:
    """Dataclass for subnet hyperparameters."""

    rho: int
    kappa: int
    immunity_period: int
    min_allowed_weights: int
    max_weight_limit: float
    tempo: int
    min_difficulty: int
    max_difficulty: int
    weights_version: int
    weights_rate_limit: int
    adjustment_interval: int
    activity_cutoff: int
    registration_allowed: bool
    target_regs_per_interval: int
    min_burn: int
    max_burn: int
    bonds_moving_avg: int
    max_regs_per_block: int
    serving_rate_limit: int
    max_validators: int
    adjustment_alpha: int
    difficulty: int
    commit_reveal_weights_interval: int
    commit_reveal_weights_enabled: bool
    alpha_high: int
    alpha_low: int
    liquid_alpha_enabled: bool

    @classmethod
    def from_vec_u8(cls, vec_u8: list[int]) -> Optional["SubnetHyperparameters"]:
        """Returns a SubnetHyperparameters object from a ``vec_u8``."""
        if len(vec_u8) == 0:
            return None

        decoded = from_scale_encoding(vec_u8, ChainDataType.SubnetHyperparameters)
        if decoded is None:
            return None

        return SubnetHyperparameters.fix_decoded_values(decoded)

    @classmethod
    def list_from_vec_u8(cls, vec_u8: list[int]) -> list["SubnetHyperparameters"]:
        """Returns a list of SubnetHyperparameters objects from a ``vec_u8``."""
        decoded = from_scale_encoding(
            vec_u8, ChainDataType.SubnetHyperparameters, is_vec=True, is_option=True
        )
        if decoded is None:
            return []

        return [SubnetHyperparameters.fix_decoded_values(d) for d in decoded]

    @classmethod
    def fix_decoded_values(cls, decoded: dict) -> "SubnetHyperparameters":
        """Returns a SubnetInfo object from a decoded SubnetInfo dictionary."""
        return SubnetHyperparameters(
            rho=decoded["rho"],
            kappa=decoded["kappa"],
            immunity_period=decoded["immunity_period"],
            min_allowed_weights=decoded["min_allowed_weights"],
            max_weight_limit=decoded["max_weights_limit"],
            tempo=decoded["tempo"],
            min_difficulty=decoded["min_difficulty"],
            max_difficulty=decoded["max_difficulty"],
            weights_version=decoded["weights_version"],
            weights_rate_limit=decoded["weights_rate_limit"],
            adjustment_interval=decoded["adjustment_interval"],
            activity_cutoff=decoded["activity_cutoff"],
            registration_allowed=decoded["registration_allowed"],
            target_regs_per_interval=decoded["target_regs_per_interval"],
            min_burn=decoded["min_burn"],
            max_burn=decoded["max_burn"],
            max_regs_per_block=decoded["max_regs_per_block"],
            max_validators=decoded["max_validators"],
            serving_rate_limit=decoded["serving_rate_limit"],
            bonds_moving_avg=decoded["bonds_moving_avg"],
            adjustment_alpha=decoded["adjustment_alpha"],
            difficulty=decoded["difficulty"],
            commit_reveal_weights_interval=decoded["commit_reveal_weights_interval"],
            commit_reveal_weights_enabled=decoded["commit_reveal_weights_enabled"],
            alpha_high=decoded["alpha_high"],
            alpha_low=decoded["alpha_low"],
            liquid_alpha_enabled=decoded["liquid_alpha_enabled"],
        )


@dataclass
class StakeInfo:
    """Dataclass for stake info."""

    hotkey_ss58: str  # Hotkey address
    coldkey_ss58: str  # Coldkey address
    stake: Balance  # Stake for the hotkey-coldkey pair

    @classmethod
    def fix_decoded_values(cls, decoded: Any) -> "StakeInfo":
        """Fixes the decoded values."""
        return cls(
            hotkey_ss58=ss58_encode(decoded["hotkey"], SS58_FORMAT),
            coldkey_ss58=ss58_encode(decoded["coldkey"], SS58_FORMAT),
            stake=Balance.from_rao(decoded["stake"]),
        )

    @classmethod
    def from_vec_u8(cls, vec_u8: list[int]) -> Optional["StakeInfo"]:
        """Returns a StakeInfo object from a ``vec_u8``."""
        if len(vec_u8) == 0:
            return None

        decoded = from_scale_encoding(vec_u8, ChainDataType.StakeInfo)
        if decoded is None:
            return None

        return StakeInfo.fix_decoded_values(decoded)

    @classmethod
    def list_of_tuple_from_vec_u8(
        cls, vec_u8: list[int]
    ) -> dict[str, list["StakeInfo"]]:
        """Returns a list of StakeInfo objects from a ``vec_u8``."""
        decoded: Optional[list[tuple[str, list[object]]]] = (
            from_scale_encoding_using_type_string(
                input_=vec_u8, type_string="Vec<(AccountId, Vec<StakeInfo>)>"
            )
        )

        if decoded is None:
            return {}

        return {
            ss58_encode(address=account_id, ss58_format=SS58_FORMAT): [
                StakeInfo.fix_decoded_values(d) for d in stake_info
            ]
            for account_id, stake_info in decoded
        }

    @classmethod
    def list_from_vec_u8(cls, vec_u8: list[int]) -> list["StakeInfo"]:
        """Returns a list of StakeInfo objects from a ``vec_u8``."""
        decoded = from_scale_encoding(vec_u8, ChainDataType.StakeInfo, is_vec=True)
        if decoded is None:
            return []

        return [StakeInfo.fix_decoded_values(d) for d in decoded]


@dataclass
class PrometheusInfo:
    """Dataclass for prometheus info."""

    block: int
    version: int
    ip: str
    port: int
    ip_type: int

    @classmethod
    def fix_decoded_values(cls, prometheus_info_decoded: dict) -> "PrometheusInfo":
        """Returns a PrometheusInfo object from a prometheus_info_decoded dictionary."""
        prometheus_info_decoded["ip"] = int_to_ip(int(prometheus_info_decoded["ip"]))

        return cls(**prometheus_info_decoded)


@dataclass
class NeuronInfo:
    """Dataclass for neuron metadata."""

    hotkey: str
    coldkey: str
    uid: int
    netuid: int
    active: int
    stake: Balance
    # mapping of coldkey to amount staked to this Neuron
    stake_dict: dict[str, Balance]
    total_stake: Balance
    rank: float
    emission: float
    incentive: float
    consensus: float
    trust: float
    validator_trust: float
    dividends: float
    last_update: int
    validator_permit: bool
    weights: list[list[int]]
    bonds: list[list[int]]
    pruning_score: int
    prometheus_info: Optional["PrometheusInfo"] = None
    axon_info: Optional[AxonInfo] = None
    is_null: bool = False

    @classmethod
    def from_weights_bonds_and_neuron_lite(
        cls,
        neuron_lite: "NeuronInfoLite",
        weights_as_dict: dict[int, list[tuple[int, int]]],
        bonds_as_dict: dict[int, list[tuple[int, int]]],
    ) -> "NeuronInfo":
        n_dict = neuron_lite.__dict__
        n_dict["weights"] = weights_as_dict.get(neuron_lite.uid, [])
        n_dict["bonds"] = bonds_as_dict.get(neuron_lite.uid, [])

        return cls(**n_dict)

    @staticmethod
    def get_null_neuron() -> "NeuronInfo":
        neuron = NeuronInfo(
            uid=0,
            netuid=0,
            active=0,
            stake=Balance.from_rao(0),
            stake_dict={},
            total_stake=Balance.from_rao(0),
            rank=0,
            emission=0,
            incentive=0,
            consensus=0,
            trust=0,
            validator_trust=0,
            dividends=0,
            last_update=0,
            validator_permit=False,
            weights=[],
            bonds=[],
            prometheus_info=None,
            axon_info=None,
            is_null=True,
            coldkey="000000000000000000000000000000000000000000000000",
            hotkey="000000000000000000000000000000000000000000000000",
            pruning_score=0,
        )
        return neuron

    @classmethod
    def fix_decoded_values(cls, neuron_info_decoded: Any) -> "NeuronInfo":
        """Fixes the values of the NeuronInfo object."""
        neuron_info_decoded = NeuronInfoLite.fix_decoded(neuron_info_decoded)
        neuron_info_decoded["weights"] = [
            [int(weight[0]), int(weight[1])]
            for weight in neuron_info_decoded["weights"]
        ]
        neuron_info_decoded["bonds"] = [
            [int(bond[0]), int(bond[1])] for bond in neuron_info_decoded["bonds"]
        ]
        return cls(**neuron_info_decoded)

    @classmethod
    def from_vec_u8(cls, vec_u8: list[int]) -> "NeuronInfo":
        """
        DEPRECATED
        Returns a NeuronInfo object from a ``vec_u8``.
        """
        warnings.warn("This is deprecated. Use the from_vec_u8_new method")
        if len(vec_u8) == 0:
            return NeuronInfo.get_null_neuron()

        decoded = from_scale_encoding(vec_u8, ChainDataType.NeuronInfo)
        if decoded is None:
            return NeuronInfo.get_null_neuron()

        return NeuronInfo.fix_decoded_values(decoded)

    @classmethod
    def from_vec_u8_new(cls, vec_u8: bytes) -> "NeuronInfo":
        n = bt_decode.NeuronInfo.decode(vec_u8)
        stake_dict = process_stake_data(n.stake)
        total_stake = sum(stake_dict.values())
        axon_info = n.axon_info
        coldkey = decode_account_id(n.coldkey)
        hotkey = decode_account_id(n.hotkey)
        return NeuronInfo(
            hotkey=hotkey,
            coldkey=coldkey,
            uid=n.uid,
            netuid=n.netuid,
            active=n.active,
            stake=total_stake,
            stake_dict=stake_dict,
            total_stake=total_stake,
            rank=u16_normalized_float(n.rank),
            emission=n.emission / 1e9,
            incentive=u16_normalized_float(n.incentive),
            consensus=u16_normalized_float(n.consensus),
            trust=u16_normalized_float(n.trust),
            validator_trust=u16_normalized_float(n.validator_trust),
            dividends=u16_normalized_float(n.dividends),
            last_update=n.last_update,
            validator_permit=n.validator_permit,
            weights=[[e[0], e[1]] for e in n.weights],
            bonds=[[e[0], e[1]] for e in n.bonds],
            pruning_score=n.pruning_score,
            prometheus_info=PrometheusInfo(
                block=n.prometheus_info.block,
                version=n.prometheus_info.version,
                ip=str(netaddr.IPAddress(n.prometheus_info.ip)),
                port=n.prometheus_info.port,
                ip_type=n.prometheus_info.ip_type,
            ),
            axon_info=AxonInfo(
                version=axon_info.version,
                ip=str(netaddr.IPAddress(axon_info.ip)),
                port=axon_info.port,
                ip_type=axon_info.ip_type,
                placeholder1=axon_info.placeholder1,
                placeholder2=axon_info.placeholder2,
                protocol=axon_info.protocol,
                hotkey=hotkey,
                coldkey=coldkey,
            ),
            is_null=False,
        )


@dataclass
class NeuronInfoLite:
    """Dataclass for neuron metadata, but without the weights and bonds."""

    hotkey: str
    coldkey: str
    uid: int
    netuid: int
    active: int
    stake: Balance
    # mapping of coldkey to amount staked to this Neuron
    stake_dict: dict[str, Balance]
    total_stake: Balance
    rank: float
    emission: float
    incentive: float
    consensus: float
    trust: float
    validator_trust: float
    dividends: float
    last_update: int
    validator_permit: bool
    prometheus_info: Optional["PrometheusInfo"]
    axon_info: AxonInfo
    pruning_score: int
    is_null: bool = False

    @staticmethod
    def get_null_neuron() -> "NeuronInfoLite":
        neuron = NeuronInfoLite(
            uid=0,
            netuid=0,
            active=0,
            stake=Balance.from_rao(0),
            stake_dict={},
            total_stake=Balance.from_rao(0),
            rank=0,
            emission=0,
            incentive=0,
            consensus=0,
            trust=0,
            validator_trust=0,
            dividends=0,
            last_update=0,
            validator_permit=False,
            prometheus_info=None,
            axon_info=None,
            is_null=True,
            coldkey="000000000000000000000000000000000000000000000000",
            hotkey="000000000000000000000000000000000000000000000000",
            pruning_score=0,
        )
        return neuron

    @staticmethod
    def fix_decoded(neuron_info_decoded: dict) -> dict:
        neuron_info_decoded["hotkey"] = ss58_encode(
            neuron_info_decoded["hotkey"], SS58_FORMAT
        )
        neuron_info_decoded["coldkey"] = ss58_encode(
            neuron_info_decoded["coldkey"], SS58_FORMAT
        )
        stake_dict = {
            ss58_encode(coldkey, SS58_FORMAT): Balance.from_rao(int(stake))
            for coldkey, stake in neuron_info_decoded["stake"]
        }
        neuron_info_decoded["stake_dict"] = stake_dict
        neuron_info_decoded["stake"] = sum(stake_dict.values())
        neuron_info_decoded["total_stake"] = neuron_info_decoded["stake"]
        neuron_info_decoded["rank"] = u16_normalized_float(neuron_info_decoded["rank"])
        neuron_info_decoded["emission"] = neuron_info_decoded["emission"] / RAO_PER_TAO
        neuron_info_decoded["incentive"] = u16_normalized_float(
            neuron_info_decoded["incentive"]
        )
        neuron_info_decoded["consensus"] = u16_normalized_float(
            neuron_info_decoded["consensus"]
        )
        neuron_info_decoded["trust"] = u16_normalized_float(
            neuron_info_decoded["trust"]
        )
        neuron_info_decoded["validator_trust"] = u16_normalized_float(
            neuron_info_decoded["validator_trust"]
        )
        neuron_info_decoded["dividends"] = u16_normalized_float(
            neuron_info_decoded["dividends"]
        )
        neuron_info_decoded["prometheus_info"] = PrometheusInfo.fix_decoded_values(
            neuron_info_decoded["prometheus_info"]
        )
        neuron_info_decoded["axon_info"] = AxonInfo.from_neuron_info(
            neuron_info_decoded
        )
        return neuron_info_decoded

    @classmethod
    def fix_decoded_values(cls, neuron_info_decoded: Any) -> "NeuronInfoLite":
        """Fixes the values of the NeuronInfoLite object."""
        neuron_info_decoded = cls.fix_decoded(neuron_info_decoded)
        return cls(**neuron_info_decoded)

    @classmethod
    def list_from_vec_u8(cls, vec_u8: list[int]) -> list["NeuronInfoLite"]:
        """
        DEPRECATED
        Returns a list of NeuronInfoLite objects from a ``vec_u8``.
        """
        warnings.warn("This is deprecated. Use the list_from_vec_u8_new method")
        decoded_list = from_scale_encoding(
            vec_u8, ChainDataType.NeuronInfoLite, is_vec=True
        )
        if decoded_list is None:
            return []

        decoded_list = [
            NeuronInfoLite.fix_decoded_values(decoded) for decoded in decoded_list
        ]
        return decoded_list

    @classmethod
    def list_from_vec_u8_new(cls, vec_u8: bytes) -> list["NeuronInfoLite"]:
        decoded = bt_decode.NeuronInfoLite.decode_vec(vec_u8)
        results = []
        for item in decoded:
            active = item.active
            axon_info = item.axon_info
            coldkey = decode_account_id(item.coldkey)
            consensus = item.consensus
            dividends = item.dividends
            emission = item.emission
            hotkey = decode_account_id(item.hotkey)
            incentive = item.incentive
            last_update = item.last_update
            netuid = item.netuid
            prometheus_info = item.prometheus_info
            pruning_score = item.pruning_score
            rank = item.rank
            stake_dict = process_stake_data(item.stake)
            stake = sum(stake_dict.values())
            trust = item.trust
            uid = item.uid
            validator_permit = item.validator_permit
            validator_trust = item.validator_trust
            results.append(
                NeuronInfoLite(
                    active=active,
                    axon_info=AxonInfo(
                        version=axon_info.version,
                        ip=str(netaddr.IPAddress(axon_info.ip)),
                        port=axon_info.port,
                        ip_type=axon_info.ip_type,
                        placeholder1=axon_info.placeholder1,
                        placeholder2=axon_info.placeholder2,
                        protocol=axon_info.protocol,
                        hotkey=hotkey,
                        coldkey=coldkey,
                    ),
                    coldkey=coldkey,
                    consensus=u16_normalized_float(consensus),
                    dividends=u16_normalized_float(dividends),
                    emission=emission / 1e9,
                    hotkey=hotkey,
                    incentive=u16_normalized_float(incentive),
                    last_update=last_update,
                    netuid=netuid,
                    prometheus_info=PrometheusInfo(
                        version=prometheus_info.version,
                        ip=str(netaddr.IPAddress(prometheus_info.ip)),
                        port=prometheus_info.port,
                        ip_type=prometheus_info.ip_type,
                        block=prometheus_info.block,
                    ),
                    pruning_score=pruning_score,
                    rank=u16_normalized_float(rank),
                    stake_dict=stake_dict,
                    stake=stake,
                    total_stake=stake,
                    trust=u16_normalized_float(trust),
                    uid=uid,
                    validator_permit=validator_permit,
                    validator_trust=validator_trust,
                )
            )
        return results


@dataclass
class DelegateInfo:
    """
    Dataclass for delegate information. For a lighter version of this class, see :func:`DelegateInfoLite`.

    :param hotkey_ss58: Hotkey of the delegate for which the information is being fetched.
    :param total_stake: Total stake of the delegate.
    :param nominators: list of nominators of the delegate and their stake.
    :param take: Take of the delegate as a percentage.
    :param owner_ss58: Coldkey of the owner.
    :param registrations: list of subnets that the delegate is registered on.
    :param validator_permits: list of subnets that the delegate is allowed to validate on.
    :param return_per_1000: Return per 1000 TAO, for the delegate over a day.
    :param total_daily_return: Total daily return of the delegate.

    """

    hotkey_ss58: str  # Hotkey of delegate
    total_stake: Balance  # Total stake of the delegate
    nominators: list[
        tuple[str, Balance]
    ]  # list of nominators of the delegate and their stake
    owner_ss58: str  # Coldkey of owner
    take: float  # Take of the delegate as a percentage
    validator_permits: list[
        int
    ]  # list of subnets that the delegate is allowed to validate on
    registrations: list[int]  # list of subnets that the delegate is registered on
    return_per_1000: Balance  # Return per 1000 tao of the delegate over a day
    total_daily_return: Balance  # Total daily return of the delegate

    @classmethod
    def fix_decoded_values(cls, decoded: Any) -> "DelegateInfo":
        """Fixes the decoded values."""

        return cls(
            hotkey_ss58=ss58_encode(decoded["delegate_ss58"], SS58_FORMAT),
            owner_ss58=ss58_encode(decoded["owner_ss58"], SS58_FORMAT),
            take=u16_normalized_float(decoded["take"]),
            nominators=[
                (
                    ss58_encode(nom[0], SS58_FORMAT),
                    Balance.from_rao(nom[1]),
                )
                for nom in decoded["nominators"]
            ],
            total_stake=Balance.from_rao(
                sum([nom[1] for nom in decoded["nominators"]])
            ),
            validator_permits=decoded["validator_permits"],
            registrations=decoded["registrations"],
            return_per_1000=Balance.from_rao(decoded["return_per_1000"]),
            total_daily_return=Balance.from_rao(decoded["total_daily_return"]),
        )

    @classmethod
    def from_vec_u8(cls, vec_u8: list[int]) -> Optional["DelegateInfo"]:
        """Returns a DelegateInfo object from a ``vec_u8``."""
        if len(vec_u8) == 0:
            return None

        decoded = from_scale_encoding(vec_u8, ChainDataType.DelegateInfo)
        if decoded is None:
            return None

        return DelegateInfo.fix_decoded_values(decoded)

    @classmethod
    def list_from_vec_u8(cls, vec_u8: list[int]) -> list["DelegateInfo"]:
        """Returns a list of DelegateInfo objects from a ``vec_u8``."""
        decoded = from_scale_encoding(vec_u8, ChainDataType.DelegateInfo, is_vec=True)

        if decoded is None:
            return []

        return [DelegateInfo.fix_decoded_values(d) for d in decoded]

    @classmethod
    def delegated_list_from_vec_u8(
        cls, vec_u8: list[int]
    ) -> list[tuple["DelegateInfo", Balance]]:
        """Returns a list of Tuples of DelegateInfo objects, and Balance, from a ``vec_u8``.

        This is the list of delegates that the user has delegated to, and the amount of stake delegated.
        """
        decoded = from_scale_encoding(vec_u8, ChainDataType.DelegatedInfo, is_vec=True)
        if decoded is None:
            return []

        return [
            (DelegateInfo.fix_decoded_values(d), Balance.from_rao(s))
            for d, s in decoded
        ]


@dataclass
class SubnetInfo:
    """Dataclass for subnet info."""

    netuid: int
    rho: int
    kappa: int
    difficulty: int
    immunity_period: int
    max_allowed_validators: int
    min_allowed_weights: int
    max_weight_limit: float
    scaling_law_power: float
    subnetwork_n: int
    max_n: int
    blocks_since_epoch: int
    tempo: int
    modality: int
    connection_requirements: dict[str, float]
    emission_value: float
    burn: Balance
    owner_ss58: str

    @classmethod
    def from_vec_u8(cls, vec_u8: list[int]) -> Optional["SubnetInfo"]:
        """Returns a SubnetInfo object from a ``vec_u8``."""
        if len(vec_u8) == 0:
            return None

        decoded = from_scale_encoding(vec_u8, ChainDataType.SubnetInfo)
        if decoded is None:
            return None

        return SubnetInfo.fix_decoded_values(decoded)

    @classmethod
    def list_from_vec_u8(cls, vec_u8: list[int]) -> list["SubnetInfo"]:
        """Returns a list of SubnetInfo objects from a `vec_u8`."""
        decoded = from_scale_encoding(
            vec_u8, ChainDataType.SubnetInfo, is_vec=True, is_option=True
        )

        if decoded is None:
            return []

        return [SubnetInfo.fix_decoded_values(d) for d in decoded]

    @classmethod
    def fix_decoded_values(cls, decoded: dict) -> "SubnetInfo":
        """Returns a SubnetInfo object from a decoded SubnetInfo dictionary."""
        return SubnetInfo(
            netuid=decoded["netuid"],
            rho=decoded["rho"],
            kappa=decoded["kappa"],
            difficulty=decoded["difficulty"],
            immunity_period=decoded["immunity_period"],
            max_allowed_validators=decoded["max_allowed_validators"],
            min_allowed_weights=decoded["min_allowed_weights"],
            max_weight_limit=decoded["max_weights_limit"],
            scaling_law_power=decoded["scaling_law_power"],
            subnetwork_n=decoded["subnetwork_n"],
            max_n=decoded["max_allowed_uids"],
            blocks_since_epoch=decoded["blocks_since_last_step"],
            tempo=decoded["tempo"],
            modality=decoded["network_modality"],
            connection_requirements={
                str(int(netuid)): u16_normalized_float(int(req))
                for netuid, req in decoded["network_connect"]
            },
            emission_value=decoded["emission_values"],
            burn=Balance.from_rao(decoded["burn"]),
            owner_ss58=ss58_encode(decoded["owner"], SS58_FORMAT),
        )

    def to_parameter_dict(self) -> Union[dict[str, Any], "torch.nn.ParameterDict"]:
        """Returns a torch tensor or dict of the subnet info."""
        if use_torch():
            return torch.nn.ParameterDict(self.__dict__)
        else:
            return self.__dict__

    @classmethod
    def from_parameter_dict(
        cls, parameter_dict: Union[dict[str, Any], "torch.nn.ParameterDict"]
    ) -> "SubnetInfo":
        if use_torch():
            return cls(**dict(parameter_dict))
        else:
            return cls(**parameter_dict)


custom_rpc_type_registry = {
    "types": {
        "SubnetInfo": {
            "type": "struct",
            "type_mapping": [
                ["netuid", "Compact<u16>"],
                ["rho", "Compact<u16>"],
                ["kappa", "Compact<u16>"],
                ["difficulty", "Compact<u64>"],
                ["immunity_period", "Compact<u16>"],
                ["max_allowed_validators", "Compact<u16>"],
                ["min_allowed_weights", "Compact<u16>"],
                ["max_weights_limit", "Compact<u16>"],
                ["scaling_law_power", "Compact<u16>"],
                ["subnetwork_n", "Compact<u16>"],
                ["max_allowed_uids", "Compact<u16>"],
                ["blocks_since_last_step", "Compact<u64>"],
                ["tempo", "Compact<u16>"],
                ["network_modality", "Compact<u16>"],
                ["network_connect", "Vec<[u16; 2]>"],
                ["emission_values", "Compact<u64>"],
                ["burn", "Compact<u64>"],
                ["owner", "AccountId"],
            ],
        },
        "DelegateInfo": {
            "type": "struct",
            "type_mapping": [
                ["delegate_ss58", "AccountId"],
                ["take", "Compact<u16>"],
                ["nominators", "Vec<(AccountId, Compact<u64>)>"],
                ["owner_ss58", "AccountId"],
                ["registrations", "Vec<Compact<u16>>"],
                ["validator_permits", "Vec<Compact<u16>>"],
                ["return_per_1000", "Compact<u64>"],
                ["total_daily_return", "Compact<u64>"],
            ],
        },
        "NeuronInfo": {
            "type": "struct",
            "type_mapping": [
                ["hotkey", "AccountId"],
                ["coldkey", "AccountId"],
                ["uid", "Compact<u16>"],
                ["netuid", "Compact<u16>"],
                ["active", "bool"],
                ["axon_info", "axon_info"],
                ["prometheus_info", "PrometheusInfo"],
                ["stake", "Vec<(AccountId, Compact<u64>)>"],
                ["rank", "Compact<u16>"],
                ["emission", "Compact<u64>"],
                ["incentive", "Compact<u16>"],
                ["consensus", "Compact<u16>"],
                ["trust", "Compact<u16>"],
                ["validator_trust", "Compact<u16>"],
                ["dividends", "Compact<u16>"],
                ["last_update", "Compact<u64>"],
                ["validator_permit", "bool"],
                ["weights", "Vec<(Compact<u16>, Compact<u16>)>"],
                ["bonds", "Vec<(Compact<u16>, Compact<u16>)>"],
                ["pruning_score", "Compact<u16>"],
            ],
        },
        "NeuronInfoLite": {
            "type": "struct",
            "type_mapping": [
                ["hotkey", "AccountId"],
                ["coldkey", "AccountId"],
                ["uid", "Compact<u16>"],
                ["netuid", "Compact<u16>"],
                ["active", "bool"],
                ["axon_info", "axon_info"],
                ["prometheus_info", "PrometheusInfo"],
                ["stake", "Vec<(AccountId, Compact<u64>)>"],
                ["rank", "Compact<u16>"],
                ["emission", "Compact<u64>"],
                ["incentive", "Compact<u16>"],
                ["consensus", "Compact<u16>"],
                ["trust", "Compact<u16>"],
                ["validator_trust", "Compact<u16>"],
                ["dividends", "Compact<u16>"],
                ["last_update", "Compact<u64>"],
                ["validator_permit", "bool"],
                ["pruning_score", "Compact<u16>"],
            ],
        },
        "axon_info": {
            "type": "struct",
            "type_mapping": [
                ["block", "u64"],
                ["version", "u32"],
                ["ip", "u128"],
                ["port", "u16"],
                ["ip_type", "u8"],
                ["protocol", "u8"],
                ["placeholder1", "u8"],
                ["placeholder2", "u8"],
            ],
        },
        "PrometheusInfo": {
            "type": "struct",
            "type_mapping": [
                ["block", "u64"],
                ["version", "u32"],
                ["ip", "u128"],
                ["port", "u16"],
                ["ip_type", "u8"],
            ],
        },
        "IPInfo": {
            "type": "struct",
            "type_mapping": [
                ["ip", "Compact<u128>"],
                ["ip_type_and_protocol", "Compact<u8>"],
            ],
        },
        "StakeInfo": {
            "type": "struct",
            "type_mapping": [
                ["hotkey", "AccountId"],
                ["coldkey", "AccountId"],
                ["stake", "Compact<u64>"],
            ],
        },
        "SubnetHyperparameters": {
            "type": "struct",
            "type_mapping": [
                ["rho", "Compact<u16>"],
                ["kappa", "Compact<u16>"],
                ["immunity_period", "Compact<u16>"],
                ["min_allowed_weights", "Compact<u16>"],
                ["max_weights_limit", "Compact<u16>"],
                ["tempo", "Compact<u16>"],
                ["min_difficulty", "Compact<u64>"],
                ["max_difficulty", "Compact<u64>"],
                ["weights_version", "Compact<u64>"],
                ["weights_rate_limit", "Compact<u64>"],
                ["adjustment_interval", "Compact<u16>"],
                ["activity_cutoff", "Compact<u16>"],
                ["registration_allowed", "bool"],
                ["target_regs_per_interval", "Compact<u16>"],
                ["min_burn", "Compact<u64>"],
                ["max_burn", "Compact<u64>"],
                ["bonds_moving_avg", "Compact<u64>"],
                ["max_regs_per_block", "Compact<u16>"],
                ["serving_rate_limit", "Compact<u64>"],
                ["max_validators", "Compact<u16>"],
                ["adjustment_alpha", "Compact<u64>"],
                ["difficulty", "Compact<u64>"],
                ["commit_reveal_weights_interval", "Compact<u64>"],
                ["commit_reveal_weights_enabled", "bool"],
                ["alpha_high", "Compact<u16>"],
                ["alpha_low", "Compact<u16>"],
                ["liquid_alpha_enabled", "bool"],
            ],
        },
    }
}
