from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, Union

import bt_decode
import netaddr
import munch

from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.networking import int_to_ip
from bittensor_cli.src.bittensor.utils import u16_normalized_float, decode_account_id


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
class InfoBase:
    """Base dataclass for info objects."""

    @abstractmethod
    def _fix_decoded(self, decoded: Any) -> "InfoBase":
        raise NotImplementedError(
            "This is an abstract method and must be implemented in a subclass."
        )

    @classmethod
    def from_any(cls, any_: Any) -> "InfoBase":
        return cls._fix_decoded(any_)

    @classmethod
    def list_from_any(cls, any_list: list[Any]) -> list["InfoBase"]:
        return [cls.from_any(any_) for any_ in any_list]

    def __getitem__(self, item):
        return getattr(self, item)

    def get(self, item, default=None):
        return getattr(self, item, default)


@dataclass
class SubnetHyperparameters(InfoBase):
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
    def _fix_decoded(cls, decoded: Union[dict, "SubnetHyperparameters"]) -> "SubnetHyperparameters":
        return SubnetHyperparameters(
            rho=decoded.get("rho"),
            kappa=decoded.get("kappa"),
            immunity_period=decoded.get("immunity_period"),
            min_allowed_weights=decoded.get("min_allowed_weights"),
            max_weight_limit=decoded.get("max_weights_limit"),
            tempo=decoded.get("tempo"),
            min_difficulty=decoded.get("min_difficulty"),
            max_difficulty=decoded.get("max_difficulty"),
            weights_version=decoded.get("weights_version"),
            weights_rate_limit=decoded.get("weights_rate_limit"),
            adjustment_interval=decoded.get("adjustment_interval"),
            activity_cutoff=decoded.get("activity_cutoff"),
            registration_allowed=decoded.get("registration_allowed"),
            target_regs_per_interval=decoded.get("target_regs_per_interval"),
            min_burn=decoded.get("min_burn"),
            max_burn=decoded.get("max_burn"),
            bonds_moving_avg=decoded.get("bonds_moving_avg"),
            max_regs_per_block=decoded.get("max_regs_per_block"),
            serving_rate_limit=decoded.get("serving_rate_limit"),
            max_validators=decoded.get("max_validators"),
            adjustment_alpha=decoded.get("adjustment_alpha"),
            difficulty=decoded.get("difficulty"),
            commit_reveal_weights_interval=decoded.get("commit_reveal_weights_interval"),
            commit_reveal_weights_enabled=decoded.get("commit_reveal_weights_enabled"),
            alpha_high=decoded.get("alpha_high"),
            alpha_low=decoded.get("alpha_low"),
            liquid_alpha_enabled=decoded.get("liquid_alpha_enabled"),
        )

    @classmethod
    def from_vec_u8(cls, vec_u8: bytes) -> Optional["SubnetHyperparameters"]:
        decoded = bt_decode.SubnetHyperparameters.decode(vec_u8)
        return cls._fix_decoded(decoded)


@dataclass
class StakeInfo(InfoBase):
    """Dataclass for stake info."""

    hotkey_ss58: str  # Hotkey address
    coldkey_ss58: str  # Coldkey address
    stake: Balance  # Stake for the hotkey-coldkey pair

    @classmethod
    def _fix_decoded(cls, decoded: Any) -> "StakeInfo":
        hotkey = decode_account_id(decoded.get("hotkey"))
        coldkey = decode_account_id(decoded.get("coldkey"))
        stake = Balance.from_rao(decoded.get("stake"))

        return StakeInfo(hotkey, coldkey, stake)

    @classmethod
    def from_any(cls, any_: Any) -> "StakeInfo":
        return cls._fix_decoded(any_)

    @classmethod
    def list_from_vec_u8(cls, vec_u8: bytes) -> list["StakeInfo"]:
        """
        Returns a list of StakeInfo objects from a `vec_u8`.
        """
        decoded = bt_decode.StakeInfo.decode_vec(vec_u8)
        return [cls._fix_decoded(d) for d in decoded]


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
class NeuronInfo(InfoBase):
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
    def _fix_decoded(cls, decoded: Any) -> "NeuronInfo":
        n = decoded

        stake_dict = process_stake_data(n.stake)
        total_stake = sum(stake_dict.values()) if stake_dict else Balance(0)
        axon_info = n.axon_info
        coldkey = decode_account_id(n.get("coldkey"))
        hotkey = decode_account_id(n.get("hotkey"))
        return NeuronInfo(
            hotkey=hotkey,
            coldkey=coldkey,
            uid=n.get("uid"),
            netuid=n.get("netuid"),
            active=n.get("active"),
            stake=total_stake,
            stake_dict=stake_dict,
            total_stake=total_stake,
            rank=u16_normalized_float(n.rget("ank")),
            emission=n.get("emission") / 1e9,
            incentive=u16_normalized_float(n.get("incentive")),
            consensus=u16_normalized_float(n.get("consensus")),
            trust=u16_normalized_float(n.get("trust")),
            validator_trust=u16_normalized_float(n.get("validator_trust")),
            dividends=u16_normalized_float(n.get("dividends")),
            last_update=n.get("last_update"),
            validator_permit=n.get("validator_permit"),
            weights=[[e[0], e[1]] for e in n.get("weights")],
            bonds=[[e[0], e[1]] for e in n.get("bonds")],
            pruning_score=n.get("pruning_score"),
            prometheus_info=PrometheusInfo(
                block=n.get("prometheus_info").get("block"),
                version=n.get("prometheus_info").get("version"),
                ip=str(netaddr.IPAddress(n.get("prometheus_info").get("ip"))),
                port=n.get("prometheus_info").get("port"),
                ip_type=n.get("prometheus_info").get("ip_type"),
            ),
            axon_info=AxonInfo(
                version=axon_info.get("version"),
                ip=str(netaddr.IPAddress(axon_info.get("ip"))),
                port=axon_info.get("port"),
                ip_type=axon_info.get("ip_type"),
                placeholder1=axon_info.get("placeholder1"),
                placeholder2=axon_info.get("placeholder2"),
                protocol=axon_info.get("protocol"),
                hotkey=hotkey,
                coldkey=coldkey,
            ),
            is_null=False,
        )

    @classmethod
    def from_vec_u8(cls, vec_u8: bytes) -> "NeuronInfo":
        n = bt_decode.NeuronInfo.decode(vec_u8)
        return cls._fix_decoded(n)


@dataclass
class NeuronInfoLite(InfoBase):
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
    def _fix_decoded(cls, decoded: Union[dict, "NeuronInfoLite"]) -> "NeuronInfoLite":
        active = decoded.get("active")
        axon_info = decoded.get("axon_info")
        coldkey = decode_account_id(decoded.get("coldkey"))
        consensus = decoded.get("consensus")
        dividends = decoded.get("dividends")
        emission = decoded.get("emission")
        hotkey = decode_account_id(decoded.get("hotkey"))
        incentive = decoded.get("incentive")
        last_update = decoded.get("last_update")
        netuid = decoded.get("netuid")
        prometheus_info = decoded.get("prometheus_info")
        pruning_score = decoded.get("pruning_score")
        rank = decoded.get("rank")
        stake_dict = process_stake_data(decoded.get("stake"))
        stake = sum(stake_dict.values()) if stake_dict else Balance(0)
        trust = decoded.get("trust")
        uid = decoded.get("uid")
        validator_permit = decoded.get("validator_permit")
        validator_trust = decoded.get("validator_trust")

        neuron = cls(
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

        return neuron

    @classmethod
    def list_from_vec_u8(cls, vec_u8: bytes) -> list["NeuronInfoLite"]:
        decoded = bt_decode.NeuronInfoLite.decode_vec(vec_u8)
        return [cls._fix_decoded(d) for d in decoded]


@dataclass
class DelegateInfo(InfoBase):
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
    def _fix_decoded(cls, decoded: "DelegateInfo") -> "DelegateInfo":
        # TODO check if this is hotkey_ss58 or delegate_ss58 from bt-decode
        hotkey = decode_account_id(decoded.delegate_ss58)
        owner = decode_account_id(decoded.owner_ss58)
        nominators = [
            (decode_account_id(x), Balance.from_rao(y)) for x, y in decoded.nominators
        ]
        total_stake = sum((x[1] for x in nominators)) if nominators else Balance(0)
        return cls(
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
    def from_vec_u8(cls, vec_u8: bytes) -> Optional["DelegateInfo"]:
        decoded = bt_decode.DelegateInfo.decode(vec_u8)
        return cls._fix_decoded(decoded)

    @classmethod
    def list_from_vec_u8(cls, vec_u8: bytes) -> list["DelegateInfo"]:
        decoded = bt_decode.DelegateInfo.decode_vec(vec_u8)
        return [cls._fix_decoded(d) for d in decoded]

    @classmethod
    def _fix_delegated_list(
        cls, delegated_list: list[tuple["DelegateInfo", Balance]]
    ) -> list[tuple["DelegateInfo", Balance]]:
        results = []
        for d, b in delegated_list:
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

    @classmethod
    def delegated_list_from_vec_u8(
        cls, vec_u8: bytes
    ) -> list[tuple["DelegateInfo", Balance]]:
        decoded = bt_decode.DelegateInfo.decode_delegated(vec_u8)
        return cls._fix_delegated_list(decoded)

    @classmethod
    def delegated_list_from_any(
        cls, any_list: list[Union[tuple["DelegateInfo", Balance], tuple[dict, Balance]]]
    ) -> list[tuple["DelegateInfo", Balance]]:
        return cls._fix_delegated_list(any_list)


@dataclass
class SubnetInfo(InfoBase):
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
    def _fix_decoded(cls, decoded: "SubnetInfo") -> "SubnetInfo":
        d = decoded
        return SubnetInfo(
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

    @classmethod
    def list_from_vec_u8(cls, vec_u8: bytes) -> list["SubnetInfo"]:
        decoded = bt_decode.SubnetInfo.decode_vec_option(vec_u8)
        return [cls._fix_decoded(d) for d in decoded]
