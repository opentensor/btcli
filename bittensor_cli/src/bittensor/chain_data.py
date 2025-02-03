from dataclasses import dataclass
from enum import Enum
from typing import Optional, Any, Union

import bt_decode
import netaddr
from scalecodec import ScaleBytes
from scalecodec.base import RuntimeConfiguration
from scalecodec.type_registry import load_type_registry_preset
from scalecodec.utils.ss58 import ss58_encode

from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.networking import int_to_ip
from bittensor_cli.src.bittensor.utils import SS58_FORMAT, u16_normalized_float


class ChainDataType(Enum):
    NeuronInfo = 1
    SubnetInfoV2 = 2
    DelegateInfo = 3
    NeuronInfoLite = 4
    DelegatedInfo = 5
    StakeInfo = 6
    IPInfo = 7
    SubnetHyperparameters = 8
    SubstakeElements = 9
    DynamicPoolInfoV2 = 10
    DelegateInfoLite = 11
    DynamicInfo = 12
    ScheduledColdkeySwapInfo = 13
    SubnetInfo = 14
    SubnetState = 15
    SubnetIdentity = 16


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
            raise TypeError(
                f"input must be a list[int], bytes, or ScaleBytes, not {type(input_)}"
            )
        as_scale_bytes = ScaleBytes(as_bytes)
    rpc_runtime_config = RuntimeConfiguration()
    rpc_runtime_config.update_type_registry(load_type_registry_preset("legacy"))
    rpc_runtime_config.update_type_registry(custom_rpc_type_registry)
    obj = rpc_runtime_config.create_scale_object(type_string, data=as_scale_bytes)
    return obj.decode()


def from_scale_encoding(
    input_: Union[list[int], bytes, ScaleBytes],
    type_name: ChainDataType,
    is_vec: bool = False,
    is_option: bool = False,
) -> Optional[dict]:
    type_string = type_name.name
    if type_name == ChainDataType.DelegatedInfo:
        # DelegatedInfo is a tuple of (DelegateInfo, Compact<u64>)
        type_string = f"({ChainDataType.DelegateInfo.name}, Compact<u64>)"
    if is_option:
        type_string = f"Option<{type_string}>"
    if is_vec:
        type_string = f"Vec<{type_string}>"

    return from_scale_encoding_using_type_string(input_, type_string)


def decode_account_id(account_id_bytes: tuple):
    # Convert the AccountId bytes to a Base64 string
    return ss58_encode(bytes(account_id_bytes).hex(), SS58_FORMAT)


def decode_hex_identity(info_dictionary):
    decoded_info = {}
    for k, v in info_dictionary.items():
        if isinstance(v, dict):
            item = next(iter(v.values()))
        else:
            item = v

        if isinstance(item, tuple):
            try:
                decoded_info[k] = bytes(item).decode()
            except UnicodeDecodeError:
                print(f"Could not decode: {k}: {item}")
        else:
            decoded_info[k] = item
    return decoded_info


def process_stake_data(stake_data, netuid):
    decoded_stake_data = {}
    for account_id_bytes, stake_ in stake_data:
        account_id = decode_account_id(account_id_bytes)
        decoded_stake_data.update(
            {account_id: Balance.from_rao(stake_).set_unit(netuid)}
        )
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
    def from_vec_u8(cls, vec_u8: bytes) -> Optional["SubnetHyperparameters"]:
        decoded = bt_decode.SubnetHyperparameters.decode(vec_u8)
        return SubnetHyperparameters(
            rho=decoded.rho,
            kappa=decoded.kappa,
            immunity_period=decoded.immunity_period,
            min_allowed_weights=decoded.min_allowed_weights,
            max_weight_limit=decoded.max_weights_limit,
            tempo=decoded.tempo,
            min_difficulty=decoded.min_difficulty,
            max_difficulty=decoded.max_difficulty,
            weights_version=decoded.weights_version,
            weights_rate_limit=decoded.weights_rate_limit,
            adjustment_interval=decoded.adjustment_interval,
            activity_cutoff=decoded.activity_cutoff,
            registration_allowed=decoded.registration_allowed,
            target_regs_per_interval=decoded.target_regs_per_interval,
            min_burn=decoded.min_burn,
            max_burn=decoded.max_burn,
            bonds_moving_avg=decoded.bonds_moving_avg,
            max_regs_per_block=decoded.max_regs_per_block,
            serving_rate_limit=decoded.serving_rate_limit,
            max_validators=decoded.max_validators,
            adjustment_alpha=decoded.adjustment_alpha,
            difficulty=decoded.difficulty,
            commit_reveal_weights_interval=decoded.commit_reveal_weights_interval,
            commit_reveal_weights_enabled=decoded.commit_reveal_weights_enabled,
            alpha_high=decoded.alpha_high,
            alpha_low=decoded.alpha_low,
            liquid_alpha_enabled=decoded.liquid_alpha_enabled,
        )


@dataclass
class StakeInfo:
    """Dataclass for stake info."""

    hotkey_ss58: str  # Hotkey address
    coldkey_ss58: str  # Coldkey address
    netuid: int
    stake: Balance  # Stake for the hotkey-coldkey pair
    locked: Balance  # Stake which is locked.
    emission: Balance  # Emission for the hotkey-coldkey pair
    drain: int
    is_registered: bool

    @classmethod
    def fix_decoded_values(cls, decoded: Any) -> "StakeInfo":
        """Fixes the decoded values."""
        return cls(
            hotkey_ss58=ss58_encode(decoded["hotkey"], SS58_FORMAT),
            coldkey_ss58=ss58_encode(decoded["coldkey"], SS58_FORMAT),
            netuid=int(decoded["netuid"]),
            stake=Balance.from_rao(decoded["stake"]).set_unit(decoded["netuid"]),
            locked=Balance.from_rao(decoded["locked"]).set_unit(decoded["netuid"]),
            emission=Balance.from_rao(decoded["emission"]).set_unit(decoded["netuid"]),
            drain=int(decoded["drain"]),
            is_registered=bool(decoded["is_registered"]),
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
                vec_u8, type_string="Vec<(AccountId, Vec<StakeInfo>)>"
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
    def from_vec_u8(cls, vec_u8: bytes) -> "NeuronInfo":
        n = bt_decode.NeuronInfo.decode(vec_u8)
        stake_dict = process_stake_data(n.stake, n.netuid)
        total_stake = sum(stake_dict.values()) if stake_dict else Balance(0)
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

    @classmethod
    def list_from_vec_u8(cls, vec_u8: bytes) -> list["NeuronInfoLite"]:
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
            stake_dict = process_stake_data(item.stake, item.netuid)
            stake = (
                sum(stake_dict.values())
                if stake_dict
                else Balance(0).set_unit(item.netuid)
            )
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
                    validator_trust=u16_normalized_float(validator_trust),
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
    def from_vec_u8(cls, vec_u8: bytes) -> Optional["DelegateInfo"]:
        decoded = bt_decode.DelegateInfo.decode(vec_u8)
        hotkey = decode_account_id(decoded.delegate_ss58)
        owner = decode_account_id(decoded.owner_ss58)
        nominators = [
            (decode_account_id(x), Balance.from_rao(y)) for x, y in decoded.nominators
        ]
        total_stake = sum((x[1] for x in nominators)) if nominators else Balance(0)
        return DelegateInfo(
            hotkey_ss58=hotkey,
            total_stake=total_stake,
            nominators=nominators,
            owner_ss58=owner,
            take=u16_normalized_float(decoded.take),
            validator_permits=decoded.validator_permits,
            registrations=decoded.registrations,
            return_per_1000=Balance.from_rao(decoded.return_per_1000),
            total_daily_return=Balance.from_rao(decoded.total_daily_return),
        )

    @classmethod
    def list_from_vec_u8(cls, vec_u8: bytes) -> list["DelegateInfo"]:
        decoded = bt_decode.DelegateInfo.decode_vec(vec_u8)
        results = []
        for d in decoded:
            hotkey = decode_account_id(d.delegate_ss58)
            owner = decode_account_id(d.owner_ss58)
            nominators = [
                (decode_account_id(x), Balance.from_rao(y)) for x, y in d.nominators
            ]
            total_stake = sum((x[1] for x in nominators)) if nominators else Balance(0)
            results.append(
                DelegateInfo(
                    hotkey_ss58=hotkey,
                    total_stake=total_stake,
                    nominators=nominators,
                    owner_ss58=owner,
                    take=u16_normalized_float(d.take),
                    validator_permits=d.validator_permits,
                    registrations=d.registrations,
                    return_per_1000=Balance.from_rao(d.return_per_1000),
                    total_daily_return=Balance.from_rao(d.total_daily_return),
                )
            )
        return results

    @classmethod
    def delegated_list_from_vec_u8(
        cls, vec_u8: bytes
    ) -> list[tuple["DelegateInfo", Balance]]:
        decoded = bt_decode.DelegateInfo.decode_delegated(vec_u8)
        results = []
        for d, b in decoded:
            nominators = [
                (decode_account_id(x), Balance.from_rao(y)) for x, y in d.nominators
            ]
            total_stake = sum((x[1] for x in nominators)) if nominators else Balance(0)
            delegate = DelegateInfo(
                hotkey_ss58=decode_account_id(d.delegate_ss58),
                total_stake=total_stake,
                nominators=nominators,
                owner_ss58=decode_account_id(d.owner_ss58),
                take=u16_normalized_float(d.take),
                validator_permits=d.validator_permits,
                registrations=d.registrations,
                return_per_1000=Balance.from_rao(d.return_per_1000),
                total_daily_return=Balance.from_rao(d.total_daily_return),
            )
            results.append((delegate, Balance.from_rao(b)))
        return results


@dataclass
class DelegateInfoLite:
    """
    Dataclass for light delegate information.

    Args:
        hotkey_ss58 (str): Hotkey of the delegate for which the information is being fetched.
        owner_ss58 (str): Coldkey of the owner.
        total_stake (int): Total stake of the delegate.
        owner_stake (int): Own stake of the delegate.
        take (float): Take of the delegate as a percentage. None if custom
    """

    hotkey_ss58: str  # Hotkey of delegate
    owner_ss58: str  # Coldkey of owner
    take: Optional[float]
    total_stake: Balance  # Total stake of the delegate
    previous_total_stake: Optional[Balance]  # Total stake of the delegate
    owner_stake: Balance  # Own stake of the delegate

    @classmethod
    def fix_decoded_values(cls, decoded: Any) -> "DelegateInfoLite":
        """Fixes the decoded values."""
        decoded_take = decoded["take"]

        if decoded_take == 65535:
            fixed_take = None
        else:
            fixed_take = u16_normalized_float(decoded_take)

        return cls(
            hotkey_ss58=ss58_encode(decoded["delegate_ss58"], SS58_FORMAT),
            owner_ss58=ss58_encode(decoded["owner_ss58"], SS58_FORMAT),
            take=fixed_take,
            total_stake=Balance.from_rao(decoded["total_stake"]),
            owner_stake=Balance.from_rao(decoded["owner_stake"]),
            previous_total_stake=None,
        )

    @classmethod
    def from_vec_u8(cls, vec_u8: list[int]) -> Optional["DelegateInfoLite"]:
        """Returns a DelegateInfoLite object from a ``vec_u8``."""
        if len(vec_u8) == 0:
            return None

        decoded = from_scale_encoding(vec_u8, ChainDataType.DelegateInfoLite)

        if decoded is None:
            return None

        decoded = DelegateInfoLite.fix_decoded_values(decoded)

        return decoded

    @classmethod
    def list_from_vec_u8(cls, vec_u8: list[int]) -> list["DelegateInfoLite"]:
        """Returns a list of DelegateInfoLite objects from a ``vec_u8``."""
        decoded = from_scale_encoding(
            vec_u8, ChainDataType.DelegateInfoLite, is_vec=True
        )

        if decoded is None:
            return []

        decoded = [DelegateInfoLite.fix_decoded_values(d) for d in decoded]

        return decoded


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
    def list_from_vec_u8(cls, vec_u8: bytes) -> list["SubnetInfo"]:
        decoded = bt_decode.SubnetInfo.decode_vec_option(vec_u8)
        result = []
        for d in decoded:
            result.append(
                SubnetInfo(
                    netuid=d.netuid,
                    rho=d.rho,
                    kappa=d.kappa,
                    difficulty=d.difficulty,
                    immunity_period=d.immunity_period,
                    max_allowed_validators=d.max_allowed_validators,
                    min_allowed_weights=d.min_allowed_weights,
                    max_weight_limit=d.max_weights_limit,
                    scaling_law_power=d.scaling_law_power,
                    subnetwork_n=d.subnetwork_n,
                    max_n=d.max_allowed_uids,
                    blocks_since_epoch=d.blocks_since_last_step,
                    tempo=d.tempo,
                    modality=d.network_modality,
                    connection_requirements={
                        str(int(netuid)): u16_normalized_float(int(req))
                        for (netuid, req) in d.network_connect
                    },
                    emission_value=d.emission_values,
                    burn=Balance.from_rao(d.burn),
                    owner_ss58=decode_account_id(d.owner),
                )
            )
        return result


@dataclass
class SubnetInfoV2:
    """Dataclass for subnet info."""

    netuid: int
    owner_ss58: str
    max_allowed_validators: int
    scaling_law_power: float
    subnetwork_n: int
    max_n: int
    blocks_since_epoch: int
    modality: int
    emission_value: float
    burn: Balance
    tao_locked: Balance
    hyperparameters: "SubnetHyperparameters"
    dynamic_pool: "DynamicPool"

    @classmethod
    def from_vec_u8(cls, vec_u8: bytes) -> Optional["SubnetInfoV2"]:
        """Returns a SubnetInfoV2 object from a ``vec_u8``."""
        if len(vec_u8) == 0:
            return None
        decoded = bt_decode.SubnetInfoV2.decode(vec_u8)  # TODO fix values

        if decoded is None:
            return None

        return cls.fix_decoded_values(decoded)

    @classmethod
    def list_from_vec_u8(cls, vec_u8: bytes) -> list["SubnetInfoV2"]:
        """Returns a list of SubnetInfoV2 objects from a ``vec_u8``."""
        decoded = bt_decode.SubnetInfoV2.decode_vec(vec_u8)  # TODO fix values

        if decoded is None:
            return []

        decoded = [cls.fix_decoded_values(d) for d in decoded]

        return decoded

    @classmethod
    def fix_decoded_values(cls, decoded: dict) -> "SubnetInfoV2":
        """Returns a SubnetInfoV2 object from a decoded SubnetInfoV2 dictionary."""
        # init dynamic pool object
        pool_info = decoded["dynamic_pool"]
        if pool_info:
            pool = DynamicPool(
                True,
                pool_info["netuid"],
                pool_info["alpha_issuance"],
                pool_info["alpha_outstanding"],
                pool_info["alpha_reserve"],
                pool_info["tao_reserve"],
                pool_info["k"],
            )
        else:
            pool = DynamicPool(False, decoded["netuid"], 0, 0, 0, 0, 0)

        return SubnetInfoV2(
            netuid=decoded["netuid"],
            owner_ss58=ss58_encode(decoded["owner"], SS58_FORMAT),
            max_allowed_validators=decoded["max_allowed_validators"],
            scaling_law_power=decoded["scaling_law_power"],
            subnetwork_n=decoded["subnetwork_n"],
            max_n=decoded["max_allowed_uids"],
            blocks_since_epoch=decoded["blocks_since_last_step"],
            modality=decoded["network_modality"],
            emission_value=decoded["emission_values"],
            burn=Balance.from_rao(decoded["burn"]),
            tao_locked=Balance.from_rao(decoded["tao_locked"]),
            hyperparameters=decoded["hyperparameters"],
            dynamic_pool=pool,
        )


@dataclass
class SubnetIdentity:
    """Dataclass for subnet identity information."""

    subnet_name: str
    github_repo: str
    subnet_contact: str

    @classmethod
    def from_vec_u8(cls, vec_u8: list[int]) -> Optional["SubnetIdentity"]:
        if len(vec_u8) == 0:
            return None

        decoded = from_scale_encoding(vec_u8, ChainDataType.SubnetIdentity)
        if decoded is None:
            return None

        return SubnetIdentity(
            subnet_name=bytes(decoded["subnet_name"]).decode(),
            github_repo=bytes(decoded["github_repo"]).decode(),
            subnet_contact=bytes(decoded["subnet_contact"]).decode(),
        )


@dataclass
class DynamicInfo:
    netuid: int
    owner_hotkey: str
    owner_coldkey: str
    subnet_name: str
    symbol: str
    tempo: int
    last_step: int
    blocks_since_last_step: int
    emission: Balance
    alpha_in: Balance
    alpha_out: Balance
    tao_in: Balance
    price: Balance
    k: float
    is_dynamic: bool
    alpha_out_emission: Balance
    alpha_in_emission: Balance
    tao_in_emission: Balance
    pending_alpha_emission: Balance
    pending_root_emission: Balance
    network_registered_at: int
    subnet_identity: Optional[SubnetIdentity]
    subnet_volume: float

    @classmethod
    def from_vec_u8(cls, vec_u8: list[int]) -> Optional["DynamicInfo"]:
        if len(vec_u8) == 0:
            return None
        decoded = from_scale_encoding(vec_u8, ChainDataType.DynamicInfo)
        if decoded is None:
            return None
        return DynamicInfo.fix_decoded_values(decoded)

    @classmethod
    def list_from_vec_u8(cls, vec_u8: Union[list[int], bytes]) -> list["DynamicInfo"]:
        decoded = from_scale_encoding(
            vec_u8, ChainDataType.DynamicInfo, is_vec=True, is_option=True
        )
        if decoded is None:
            return []
        decoded = [DynamicInfo.fix_decoded_values(d) for d in decoded]
        return decoded

    @classmethod
    def fix_decoded_values(cls, decoded: dict) -> "DynamicInfo":
        """Returns a DynamicInfo object from a decoded DynamicInfo dictionary."""

        netuid = int(decoded["netuid"])
        symbol = bytes([int(b) for b in decoded["token_symbol"]]).decode()
        subnet_name = bytes([int(b) for b in decoded["subnet_name"]]).decode()
        is_dynamic = (
            True if int(decoded["netuid"]) > 0 else False
        )  # TODO: Patching this temporarily for netuid 0

        owner_hotkey = ss58_encode(decoded["owner_hotkey"], SS58_FORMAT)
        owner_coldkey = ss58_encode(decoded["owner_coldkey"], SS58_FORMAT)

        emission = Balance.from_rao(decoded["emission"]).set_unit(0)
        alpha_in = Balance.from_rao(decoded["alpha_in"]).set_unit(netuid)
        alpha_out = Balance.from_rao(decoded["alpha_out"]).set_unit(netuid)
        tao_in = Balance.from_rao(decoded["tao_in"]).set_unit(0)
        subnet_volume = Balance.from_rao(decoded["subnet_volume"]).set_unit(netuid)
        alpha_out_emission = Balance.from_rao(decoded["alpha_out_emission"]).set_unit(
            netuid
        )
        alpha_in_emission = Balance.from_rao(decoded["alpha_in_emission"]).set_unit(
            netuid
        )
        tao_in_emission = Balance.from_rao(decoded["tao_in_emission"]).set_unit(0)
        pending_alpha_emission = Balance.from_rao(
            decoded["pending_alpha_emission"]
        ).set_unit(netuid)
        pending_root_emission = Balance.from_rao(
            decoded["pending_root_emission"]
        ).set_unit(0)
        price = (
            Balance.from_tao(1.0)
            if netuid == 0
            else Balance.from_tao(tao_in.tao / alpha_in.tao)
            if alpha_in.tao > 0
            else Balance.from_tao(1)
        )  # TODO: Patching this temporarily for netuid 0

        if decoded.get("subnet_identity"):
            subnet_identity = SubnetIdentity(
                subnet_name=decoded["subnet_identity"]["subnet_name"],
                github_repo=decoded["subnet_identity"]["github_repo"],
                subnet_contact=decoded["subnet_identity"]["subnet_contact"],
            )
        else:
            subnet_identity = None

        return cls(
            netuid=netuid,
            owner_hotkey=owner_hotkey,
            owner_coldkey=owner_coldkey,
            subnet_name=subnet_name,
            symbol=symbol,
            tempo=int(decoded["tempo"]),
            last_step=int(decoded["last_step"]),
            blocks_since_last_step=int(decoded["blocks_since_last_step"]),
            emission=emission,
            alpha_in=alpha_in,
            alpha_out=alpha_out,
            tao_in=tao_in,
            k=tao_in.rao * alpha_in.rao,
            is_dynamic=is_dynamic,
            price=price,
            alpha_out_emission=alpha_out_emission,
            alpha_in_emission=alpha_in_emission,
            tao_in_emission=tao_in_emission,
            pending_alpha_emission=pending_alpha_emission,
            pending_root_emission=pending_root_emission,
            network_registered_at=int(decoded["network_registered_at"]),
            subnet_identity=subnet_identity,
            subnet_volume=subnet_volume,
        )

    def tao_to_alpha(self, tao: Balance) -> Balance:
        if self.price.tao != 0:
            return Balance.from_tao(tao.tao / self.price.tao).set_unit(self.netuid)
        else:
            return Balance.from_tao(0)

    def alpha_to_tao(self, alpha: Balance) -> Balance:
        return Balance.from_tao(alpha.tao * self.price.tao)

    def tao_to_alpha_with_slippage(self, tao: Balance) -> tuple[Balance, Balance]:
        """
        Returns an estimate of how much Alpha would a staker receive if they stake their tao using the current pool state.
        Args:
            tao: Amount of TAO to stake.
        Returns:
            Tuple of balances where the first part is the amount of Alpha received, and the
            second part (slippage) is the difference between the estimated amount and ideal
            amount as if there was no slippage
        """
        if self.is_dynamic:
            new_tao_in = self.tao_in + tao
            if new_tao_in == 0:
                return tao, Balance.from_rao(0)
            new_alpha_in = self.k / new_tao_in

            # Amount of alpha given to the staker
            alpha_returned = Balance.from_rao(
                self.alpha_in.rao - new_alpha_in.rao
            ).set_unit(self.netuid)

            # Ideal conversion as if there is no slippage, just price
            alpha_ideal = self.tao_to_alpha(tao)

            if alpha_ideal.tao > alpha_returned.tao:
                slippage = Balance.from_tao(
                    alpha_ideal.tao - alpha_returned.tao
                ).set_unit(self.netuid)
            else:
                slippage = Balance.from_tao(0)
        else:
            alpha_returned = tao.set_unit(self.netuid)
            slippage = Balance.from_tao(0)

        slippage_pct_float = (
            100 * float(slippage) / float(slippage + alpha_returned)
            if slippage + alpha_returned != 0
            else 0
        )
        return alpha_returned, slippage, slippage_pct_float

    def alpha_to_tao_with_slippage(self, alpha: Balance) -> tuple[Balance, Balance]:
        """
        Returns an estimate of how much TAO would a staker receive if they unstake their alpha using the current pool state.
        Args:
            alpha: Amount of Alpha to stake.
        Returns:
            Tuple of balances where the first part is the amount of TAO received, and the
            second part (slippage) is the difference between the estimated amount and ideal
            amount as if there was no slippage
        """
        if self.is_dynamic:
            new_alpha_in = self.alpha_in + alpha
            new_tao_reserve = self.k / new_alpha_in
            # Amount of TAO given to the unstaker
            tao_returned = Balance.from_rao(self.tao_in - new_tao_reserve)

            # Ideal conversion as if there is no slippage, just price
            tao_ideal = self.alpha_to_tao(alpha)

            if tao_ideal > tao_returned:
                slippage = Balance.from_tao(tao_ideal.tao - tao_returned.tao)
            else:
                slippage = Balance.from_tao(0)
        else:
            tao_returned = alpha.set_unit(0)
            slippage = Balance.from_tao(0)
        slippage_pct_float = (
            100 * float(slippage) / float(slippage + tao_returned)
            if slippage + tao_returned != 0
            else 0
        )
        return tao_returned, slippage, slippage_pct_float


@dataclass
class DynamicPoolInfoV2:
    """Dataclass for dynamic pool info."""

    netuid: int
    alpha_issuance: int
    alpha_outstanding: int
    alpha_reserve: int
    tao_reserve: int
    k: int

    @classmethod
    def from_vec_u8(cls, vec_u8: list[int]) -> Optional["DynamicPoolInfoV2"]:
        """Returns a DynamicPoolInfoV2 object from a ``vec_u8``."""
        if len(vec_u8) == 0:
            return None
        return from_scale_encoding(vec_u8, ChainDataType.DynamicPoolInfoV2)


@dataclass
class DynamicPool:
    is_dynamic: bool
    alpha_issuance: Balance
    alpha_outstanding: Balance
    alpha_reserve: Balance
    tao_reserve: Balance
    k: int
    price: Balance
    netuid: int

    def __init__(
        self,
        is_dynamic: bool,
        netuid: int,
        alpha_issuance: Union[int, Balance],
        alpha_outstanding: Union[int, Balance],
        alpha_reserve: Union[int, Balance],
        tao_reserve: Union[int, Balance],
        k: int,
    ):
        self.is_dynamic = is_dynamic
        self.netuid = netuid
        self.alpha_issuance = (
            alpha_issuance
            if isinstance(alpha_issuance, Balance)
            else Balance.from_rao(alpha_issuance).set_unit(netuid)
        )
        self.alpha_outstanding = (
            alpha_outstanding
            if isinstance(alpha_outstanding, Balance)
            else Balance.from_rao(alpha_outstanding).set_unit(netuid)
        )
        self.alpha_reserve = (
            alpha_reserve
            if isinstance(alpha_reserve, Balance)
            else Balance.from_rao(alpha_reserve).set_unit(netuid)
        )
        self.tao_reserve = (
            tao_reserve
            if isinstance(tao_reserve, Balance)
            else Balance.from_rao(tao_reserve).set_unit(0)
        )
        self.k = k
        if is_dynamic:
            if self.alpha_reserve.tao > 0:
                self.price = Balance.from_tao(
                    self.tao_reserve.tao / self.alpha_reserve.tao
                )
            else:
                self.price = Balance.from_tao(0.0)
        else:
            self.price = Balance.from_tao(1.0)

    def __str__(self) -> str:
        return (
            f"DynamicPool( alpha_issuance={self.alpha_issuance}, "
            f"alpha_outstanding={self.alpha_outstanding}, "
            f"alpha_reserve={self.alpha_reserve}, "
            f"tao_reserve={self.tao_reserve}, k={self.k}, price={self.price} )"
        )

    def __repr__(self) -> str:
        return self.__str__()

    def tao_to_alpha(self, tao: Balance) -> Balance:
        if self.price.tao != 0:
            return Balance.from_tao(tao.tao / self.price.tao).set_unit(self.netuid)
        else:
            return Balance.from_tao(0)

    def alpha_to_tao(self, alpha: Balance) -> Balance:
        return Balance.from_tao(alpha.tao * self.price.tao)

    def tao_to_alpha_with_slippage(self, tao: Balance) -> tuple[Balance, Balance]:
        """
        Returns an estimate of how much Alpha would a staker receive if they stake their tao
        using the current pool state
        Args:
            tao: Amount of TAO to stake.
        Returns:
            Tuple of balances where the first part is the amount of Alpha received, and the
            second part (slippage) is the difference between the estimated amount and ideal
            amount as if there was no slippage
        """
        if self.is_dynamic:
            new_tao_in = self.tao_reserve + tao
            if new_tao_in == 0:
                return tao, Balance.from_rao(0)
            new_alpha_in = self.k / new_tao_in

            # Amount of alpha given to the staker
            alpha_returned = Balance.from_rao(
                self.alpha_reserve.rao - new_alpha_in.rao
            ).set_unit(self.netuid)

            # Ideal conversion as if there is no slippage, just price
            alpha_ideal = self.tao_to_alpha(tao)

            if alpha_ideal.tao > alpha_returned.tao:
                slippage = Balance.from_tao(
                    alpha_ideal.tao - alpha_returned.tao
                ).set_unit(self.netuid)
            else:
                slippage = Balance.from_tao(0)
        else:
            alpha_returned = tao.set_unit(self.netuid)
            slippage = Balance.from_tao(0)
        return alpha_returned, slippage

    def alpha_to_tao_with_slippage(self, alpha: Balance) -> tuple[Balance, Balance]:
        """
        Returns an estimate of how much TAO would a staker receive if they unstake their
        alpha using the current pool state
        Args:
            alpha: Amount of Alpha to stake.
        Returns:
            Tuple of balances where the first part is the amount of TAO received, and the
            second part (slippage) is the difference between the estimated amount and ideal
            amount as if there was no slippage
        """
        if self.is_dynamic:
            new_alpha_in = self.alpha_reserve + alpha
            new_tao_reserve = self.k / new_alpha_in
            # Amount of TAO given to the unstaker
            tao_returned = Balance.from_rao(self.tao_reserve - new_tao_reserve)

            # Ideal conversion as if there is no slippage, just price
            tao_ideal = self.alpha_to_tao(alpha)

            if tao_ideal > tao_returned:
                slippage = Balance.from_tao(tao_ideal.tao - tao_returned.tao)
            else:
                slippage = Balance.from_tao(0)
        else:
            tao_returned = alpha.set_unit(0)
            slippage = Balance.from_tao(0)
        return tao_returned, slippage


@dataclass
class ScheduledColdkeySwapInfo:
    """Dataclass for scheduled coldkey swap information."""

    old_coldkey: str
    new_coldkey: str
    arbitration_block: int

    @classmethod
    def fix_decoded_values(cls, decoded: Any) -> "ScheduledColdkeySwapInfo":
        """Fixes the decoded values."""
        return cls(
            old_coldkey=ss58_encode(decoded["old_coldkey"], SS58_FORMAT),
            new_coldkey=ss58_encode(decoded["new_coldkey"], SS58_FORMAT),
            arbitration_block=decoded["arbitration_block"],
        )

    @classmethod
    def from_vec_u8(cls, vec_u8: list[int]) -> Optional["ScheduledColdkeySwapInfo"]:
        """Returns a ScheduledColdkeySwapInfo object from a ``vec_u8``."""
        if len(vec_u8) == 0:
            return None

        decoded = from_scale_encoding(vec_u8, ChainDataType.ScheduledColdkeySwapInfo)
        if decoded is None:
            return None

        return ScheduledColdkeySwapInfo.fix_decoded_values(decoded)

    @classmethod
    def list_from_vec_u8(cls, vec_u8: list[int]) -> list["ScheduledColdkeySwapInfo"]:
        """Returns a list of ScheduledColdkeySwapInfo objects from a ``vec_u8``."""
        decoded = from_scale_encoding(
            vec_u8, ChainDataType.ScheduledColdkeySwapInfo, is_vec=True
        )
        if decoded is None:
            return []

        return [ScheduledColdkeySwapInfo.fix_decoded_values(d) for d in decoded]

    @classmethod
    def decode_account_id_list(cls, vec_u8: list[int]) -> Optional[list[str]]:
        """Decodes a list of AccountIds from vec_u8."""
        decoded = from_scale_encoding(
            vec_u8, ChainDataType.ScheduledColdkeySwapInfo.AccountId, is_vec=True
        )
        if decoded is None:
            return None
        return [ss58_encode(account_id, SS58_FORMAT) for account_id in decoded]


@dataclass
class SubnetState:
    netuid: int
    hotkeys: list[str]
    coldkeys: list[str]
    active: list[bool]
    validator_permit: list[bool]
    pruning_score: list[float]
    last_update: list[int]
    emission: list[Balance]
    dividends: list[float]
    incentives: list[float]
    consensus: list[float]
    trust: list[float]
    rank: list[float]
    block_at_registration: list[int]
    alpha_stake: list[Balance]
    tao_stake: list[Balance]
    total_stake: list[Balance]
    emission_history: list[list[int]]

    @classmethod
    def from_vec_u8(cls, vec_u8: list[int]) -> Optional["SubnetState"]:
        if len(vec_u8) == 0:
            return None
        decoded = from_scale_encoding(vec_u8, ChainDataType.SubnetState)
        if decoded is None:
            return None
        return SubnetState.fix_decoded_values(decoded)

    @classmethod
    def list_from_vec_u8(cls, vec_u8: list[int]) -> list["SubnetState"]:
        decoded = from_scale_encoding(
            vec_u8, ChainDataType.SubnetState, is_vec=True, is_option=True
        )
        if decoded is None:
            return []
        decoded = [SubnetState.fix_decoded_values(d) for d in decoded]
        return decoded

    @classmethod
    def fix_decoded_values(cls, decoded: dict) -> "SubnetState":
        netuid = decoded["netuid"]
        return SubnetState(
            netuid=netuid,
            hotkeys=[ss58_encode(val, SS58_FORMAT) for val in decoded["hotkeys"]],
            coldkeys=[ss58_encode(val, SS58_FORMAT) for val in decoded["coldkeys"]],
            active=decoded["active"],
            validator_permit=decoded["validator_permit"],
            pruning_score=[
                u16_normalized_float(val) for val in decoded["pruning_score"]
            ],
            last_update=decoded["last_update"],
            emission=[
                Balance.from_rao(val).set_unit(netuid) for val in decoded["emission"]
            ],
            dividends=[u16_normalized_float(val) for val in decoded["dividends"]],
            incentives=[u16_normalized_float(val) for val in decoded["incentives"]],
            consensus=[u16_normalized_float(val) for val in decoded["consensus"]],
            trust=[u16_normalized_float(val) for val in decoded["trust"]],
            rank=[u16_normalized_float(val) for val in decoded["rank"]],
            block_at_registration=decoded["block_at_registration"],
            alpha_stake=[
                Balance.from_rao(val).set_unit(netuid) for val in decoded["alpha_stake"]
            ],
            tao_stake=[
                Balance.from_rao(val).set_unit(0) for val in decoded["tao_stake"]
            ],
            total_stake=[
                Balance.from_rao(val).set_unit(netuid) for val in decoded["total_stake"]
            ],
            emission_history=decoded["emission_history"],
        )


class SubstakeElements:
    @staticmethod
    def decode(result: list[int]) -> list[dict]:
        descaled = from_scale_encoding(
            input_=result, type_name=ChainDataType.SubstakeElements, is_vec=True
        )
        result = []
        for item in descaled:
            result.append(
                {
                    "hotkey": ss58_encode(item["hotkey"], SS58_FORMAT),
                    "coldkey": ss58_encode(item["coldkey"], SS58_FORMAT),
                    "netuid": item["netuid"],
                    "stake": Balance.from_rao(item["stake"]),
                }
            )
        return result


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
        "DynamicPoolInfoV2": {
            "type": "struct",
            "type_mapping": [
                ["netuid", "u16"],
                ["alpha_issuance", "u64"],
                ["alpha_outstanding", "u64"],
                ["alpha_reserve", "u64"],
                ["tao_reserve", "u64"],
                ["k", "u128"],
            ],
        },
        "SubnetInfoV2": {
            "type": "struct",
            "type_mapping": [
                ["netuid", "u16"],
                ["owner", "AccountId"],
                ["max_allowed_validators", "u16"],
                ["scaling_law_power", "u16"],
                ["subnetwork_n", "u16"],
                ["max_allowed_uids", "u16"],
                ["blocks_since_last_step", "Compact<u32>"],
                ["network_modality", "u16"],
                ["emission_values", "Compact<u64>"],
                ["burn", "Compact<u64>"],
                ["tao_locked", "Compact<u64>"],
                ["hyperparameters", "SubnetHyperparameters"],
                ["dynamic_pool", "Option<DynamicPoolInfoV2>"],
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
        "DelegateInfoLite": {
            "type": "struct",
            "type_mapping": [
                ["delegate_ss58", "AccountId"],
                ["owner_ss58", "AccountId"],
                ["take", "u16"],
                ["owner_stake", "Compact<u64>"],
                ["total_stake", "Compact<u64>"],
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
        "ScheduledColdkeySwapInfo": {
            "type": "struct",
            "type_mapping": [
                ["old_coldkey", "AccountId"],
                ["new_coldkey", "AccountId"],
                ["arbitration_block", "Compact<u64>"],
            ],
        },
        "SubnetState": {
            "type": "struct",
            "type_mapping": [
                ["netuid", "Compact<u16>"],
                ["hotkeys", "Vec<AccountId>"],
                ["coldkeys", "Vec<AccountId>"],
                ["active", "Vec<bool>"],
                ["validator_permit", "Vec<bool>"],
                ["pruning_score", "Vec<Compact<u16>>"],
                ["last_update", "Vec<Compact<u64>>"],
                ["emission", "Vec<Compact<u64>>"],
                ["dividends", "Vec<Compact<u16>>"],
                ["incentives", "Vec<Compact<u16>>"],
                ["consensus", "Vec<Compact<u16>>"],
                ["trust", "Vec<Compact<u16>>"],
                ["rank", "Vec<Compact<u16>>"],
                ["block_at_registration", "Vec<Compact<u64>>"],
                ["alpha_stake", "Vec<Compact<u64>>"],
                ["tao_stake", "Vec<Compact<u64>>"],
                ["total_stake", "Vec<Compact<u64>>"],
                ["emission_history", "Vec<Vec<Compact<u64>>>"],
            ],
        },
        "StakeInfo": {
            "type": "struct",
            "type_mapping": [
                ["hotkey", "AccountId"],
                ["coldkey", "AccountId"],
                ["netuid", "Compact<u16>"],
                ["stake", "Compact<u64>"],
                ["locked", "Compact<u64>"],
                ["emission", "Compact<u64>"],
                ["drain", "Compact<u64>"],
                ["is_registered", "bool"],
            ],
        },
        "DynamicInfo": {
            "type": "struct",
            "type_mapping": [
                ["netuid", "Compact<u16>"],
                ["owner_hotkey", "AccountId"],
                ["owner_coldkey", "AccountId"],
                ["subnet_name", "Vec<Compact<u8>>"],
                ["token_symbol", "Vec<Compact<u8>>"],
                ["tempo", "Compact<u16>"],
                ["last_step", "Compact<u64>"],
                ["blocks_since_last_step", "Compact<u64>"],
                ["emission", "Compact<u64>"],
                ["alpha_in", "Compact<u64>"],
                ["alpha_out", "Compact<u64>"],
                ["tao_in", "Compact<u64>"],
                ["alpha_out_emission", "Compact<u64>"],
                ["alpha_in_emission", "Compact<u64>"],
                ["tao_in_emission", "Compact<u64>"],
                ["pending_alpha_emission", "Compact<u64>"],
                ["pending_root_emission", "Compact<u64>"],
                ["network_registered_at", "Compact<u64>"],
                ["subnet_volume", "Compact<u128>"],
                ["subnet_identity", "Option<SubnetIdentity>"],
            ],
        },
        "SubstakeElements": {
            "type": "struct",
            "type_mapping": [
                ["hotkey", "AccountId"],
                ["coldkey", "AccountId"],
                ["netuid", "Compact<u16>"],
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
        "SubnetIdentity": {
            "type": "struct",
            "type_mapping": [
                ["subnet_name", "Vec<u8>"],
                ["github_repo", "Vec<u8>"],
                ["subnet_contact", "Vec<u8>"],
            ],
        },
    }
}
