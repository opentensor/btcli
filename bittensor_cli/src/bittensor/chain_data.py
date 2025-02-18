from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Any, Union

import netaddr
from scalecodec.utils.ss58 import ss58_encode

from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.networking import int_to_ip
from bittensor_cli.src.bittensor.utils import (
    SS58_FORMAT,
    u16_normalized_float,
    decode_account_id,
)


class ChainDataType(Enum):
    NeuronInfo = 1
    DelegateInfo = 2
    NeuronInfoLite = 3
    StakeInfo = 4
    SubnetHyperparameters = 5
    DelegateInfoLite = 6
    DynamicInfo = 7
    ScheduledColdkeySwapInfo = 8
    SubnetInfo = 9
    SubnetState = 10
    SubnetIdentity = 11


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
class InfoBase:
    """Base dataclass for info objects."""

    @abstractmethod
    def _fix_decoded(self, decoded: Any) -> "InfoBase":
        raise NotImplementedError(
            "This is an abstract method and must be implemented in a subclass."
        )

    @classmethod
    def from_any(cls, data: Any) -> "InfoBase":
        return cls._fix_decoded(data)

    @classmethod
    def list_from_any(cls, data_list: list[Any]) -> list["InfoBase"]:
        return [cls.from_any(data) for data in data_list]

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
    max_weights_limit: float
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
    commit_reveal_period: int
    commit_reveal_weights_enabled: bool
    alpha_high: int
    alpha_low: int
    liquid_alpha_enabled: bool

    @classmethod
    def _fix_decoded(
        cls, decoded: Union[dict, "SubnetHyperparameters"]
    ) -> "SubnetHyperparameters":
        return cls(
            rho=decoded.get("rho"),
            kappa=decoded.get("kappa"),
            immunity_period=decoded.get("immunity_period"),
            min_allowed_weights=decoded.get("min_allowed_weights"),
            max_weights_limit=decoded.get("max_weights_limit"),
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
            commit_reveal_period=decoded.get("commit_reveal_period"),
            commit_reveal_weights_enabled=decoded.get("commit_reveal_weights_enabled"),
            alpha_high=decoded.get("alpha_high"),
            alpha_low=decoded.get("alpha_low"),
            liquid_alpha_enabled=decoded.get("liquid_alpha_enabled"),
        )


@dataclass
class StakeInfo(InfoBase):
    """Dataclass for stake info."""

    hotkey_ss58: str  # Hotkey address
    coldkey_ss58: str  # Coldkey address
    netuid: int
    stake: Balance  # Stake for the hotkey-coldkey pair
    locked: Balance  # Stake which is locked.
    emission: Balance  # Emission for the hotkey-coldkey pair
    tao_emission: Balance  # TAO emission for the hotkey-coldkey pair
    drain: int
    is_registered: bool

    @classmethod
    def _fix_decoded(cls, decoded: Any) -> "StakeInfo":
        hotkey = decode_account_id(decoded.get("hotkey"))
        coldkey = decode_account_id(decoded.get("coldkey"))
        netuid = int(decoded.get("netuid"))
        stake = Balance.from_rao(decoded.get("stake")).set_unit(netuid)
        locked = Balance.from_rao(decoded.get("locked")).set_unit(netuid)
        emission = Balance.from_rao(decoded.get("emission")).set_unit(netuid)
        tao_emission = Balance.from_rao(decoded.get("tao_emission"))
        drain = int(decoded.get("drain"))
        is_registered = bool(decoded.get("is_registered"))

        return cls(
            hotkey,
            coldkey,
            netuid,
            stake,
            locked,
            emission,
            tao_emission,
            drain,
            is_registered,
        )


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
            axon_info=None,
            is_null=True,
            coldkey="000000000000000000000000000000000000000000000000",
            hotkey="000000000000000000000000000000000000000000000000",
            pruning_score=0,
        )
        return neuron

    @classmethod
    def _fix_decoded(cls, decoded: Any) -> "NeuronInfo":
        netuid = decoded.get("netuid")
        stake_dict = process_stake_data(decoded.get("stake"), netuid=netuid)
        total_stake = sum(stake_dict.values()) if stake_dict else Balance(0)
        axon_info = decoded.get("axon_info", {})
        coldkey = decode_account_id(decoded.get("coldkey"))
        hotkey = decode_account_id(decoded.get("hotkey"))
        return cls(
            hotkey=hotkey,
            coldkey=coldkey,
            uid=decoded.get("uid"),
            netuid=netuid,
            active=decoded.get("active"),
            stake=total_stake,
            stake_dict=stake_dict,
            total_stake=total_stake,
            rank=u16_normalized_float(decoded.get("rank")),
            emission=decoded.get("emission") / 1e9,
            incentive=u16_normalized_float(decoded.get("incentive")),
            consensus=u16_normalized_float(decoded.get("consensus")),
            trust=u16_normalized_float(decoded.get("trust")),
            validator_trust=u16_normalized_float(decoded.get("validator_trust")),
            dividends=u16_normalized_float(decoded.get("dividends")),
            last_update=decoded.get("last_update"),
            validator_permit=decoded.get("validator_permit"),
            weights=[[e[0], e[1]] for e in decoded.get("weights")],
            bonds=[[e[0], e[1]] for e in decoded.get("bonds")],
            pruning_score=decoded.get("pruning_score"),
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
        axon_info = decoded.get("axon_info", {})
        coldkey = decode_account_id(decoded.get("coldkey"))
        consensus = decoded.get("consensus")
        dividends = decoded.get("dividends")
        emission = decoded.get("emission")
        hotkey = decode_account_id(decoded.get("hotkey"))
        incentive = decoded.get("incentive")
        last_update = decoded.get("last_update")
        netuid = decoded.get("netuid")
        pruning_score = decoded.get("pruning_score")
        rank = decoded.get("rank")
        stake_dict = process_stake_data(decoded.get("stake"), netuid)
        stake = sum(stake_dict.values()) if stake_dict else Balance(0)
        trust = decoded.get("trust")
        uid = decoded.get("uid")
        validator_permit = decoded.get("validator_permit")
        validator_trust = decoded.get("validator_trust")

        neuron = cls(
            active=active,
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
            coldkey=coldkey,
            consensus=u16_normalized_float(consensus),
            dividends=u16_normalized_float(dividends),
            emission=emission / 1e9,
            hotkey=hotkey,
            incentive=u16_normalized_float(incentive),
            last_update=last_update,
            netuid=netuid,
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
        hotkey = decode_account_id(decoded.get("hotkey_ss58"))
        owner = decode_account_id(decoded.get("owner_ss58"))
        nominators = [
            (decode_account_id(x), Balance.from_rao(y))
            for x, y in decoded.get("nominators")
        ]
        total_stake = sum((x[1] for x in nominators)) if nominators else Balance(0)
        return cls(
            hotkey_ss58=hotkey,
            total_stake=total_stake,
            nominators=nominators,
            owner_ss58=owner,
            take=u16_normalized_float(decoded.get("take")),
            validator_permits=decoded.get("validator_permits"),
            registrations=decoded.get("registrations"),
            return_per_1000=Balance.from_rao(decoded.get("return_per_1000")),
            total_daily_return=Balance.from_rao(decoded.get("total_daily_return")),
        )


@dataclass
class DelegateInfoLite(InfoBase):
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
    def _fix_decoded(cls, decoded: Any) -> "DelegateInfoLite":
        """Fixes the decoded values."""
        decoded_take = decoded.get("take")

        if decoded_take == 65535:
            fixed_take = None
        else:
            fixed_take = u16_normalized_float(decoded_take)

        return cls(
            hotkey_ss58=ss58_encode(decoded.get("delegate_ss58"), SS58_FORMAT),
            owner_ss58=ss58_encode(decoded.get("owner_ss58"), SS58_FORMAT),
            take=fixed_take,
            total_stake=Balance.from_rao(decoded.get("total_stake")),
            owner_stake=Balance.from_rao(decoded.get("owner_stake")),
            previous_total_stake=None,
        )


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
    max_weights_limit: float
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
        return cls(
            netuid=decoded.get("netuid"),
            rho=decoded.get("rho"),
            kappa=decoded.get("kappa"),
            difficulty=decoded.get("difficulty"),
            immunity_period=decoded.get("immunity_period"),
            max_allowed_validators=decoded.get("max_allowed_validators"),
            min_allowed_weights=decoded.get("min_allowed_weights"),
            max_weights_limit=decoded.get("max_weights_limit"),
            scaling_law_power=decoded.get("scaling_law_power"),
            subnetwork_n=decoded.get("subnetwork_n"),
            max_n=decoded.get("max_allowed_uids"),
            blocks_since_epoch=decoded.get("blocks_since_last_step"),
            tempo=decoded.get("tempo"),
            modality=decoded.get("network_modality"),
            connection_requirements={
                str(int(netuid)): u16_normalized_float(int(req))
                for (netuid, req) in decoded.get("network_connect")
            },
            emission_value=decoded.get("emission_value"),
            burn=Balance.from_rao(decoded.get("burn")),
            owner_ss58=decode_account_id(decoded.get("owner")),
        )


@dataclass
class SubnetIdentity(InfoBase):
    """Dataclass for subnet identity information."""

    subnet_name: str
    github_repo: str
    subnet_contact: str
    subnet_url: str
    discord: str
    description: str
    additional: str

    @classmethod
    def _fix_decoded(cls, decoded: dict) -> "SubnetIdentity":
        return cls(
            subnet_name=bytes(decoded["subnet_name"]).decode(),
            github_repo=bytes(decoded["github_repo"]).decode(),
            subnet_contact=bytes(decoded["subnet_contact"]).decode(),
            subnet_url=bytes(decoded["subnet_url"]).decode(),
            discord=bytes(decoded["discord"]).decode(),
            description=bytes(decoded["description"]).decode(),
            additional=bytes(decoded["additional"]).decode(),
        )


@dataclass
class DynamicInfo(InfoBase):
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
    subnet_volume: Balance

    @classmethod
    def _fix_decoded(cls, decoded: Any) -> "DynamicInfo":
        """Returns a DynamicInfo object from a decoded DynamicInfo dictionary."""

        netuid = int(decoded.get("netuid"))
        symbol = bytes([int(b) for b in decoded.get("token_symbol")]).decode()
        subnet_name = bytes([int(b) for b in decoded.get("subnet_name")]).decode()
        is_dynamic = True if netuid > 0 else False  # Patching for netuid 0

        owner_hotkey = decode_account_id(decoded.get("owner_hotkey"))
        owner_coldkey = decode_account_id(decoded.get("owner_coldkey"))

        emission = Balance.from_rao(decoded.get("emission")).set_unit(0)
        alpha_in = Balance.from_rao(decoded.get("alpha_in")).set_unit(netuid)
        alpha_out = Balance.from_rao(decoded.get("alpha_out")).set_unit(netuid)
        tao_in = Balance.from_rao(decoded.get("tao_in")).set_unit(0)
        alpha_out_emission = Balance.from_rao(
            decoded.get("alpha_out_emission")
        ).set_unit(netuid)
        alpha_in_emission = Balance.from_rao(decoded.get("alpha_in_emission")).set_unit(
            netuid
        )
        subnet_volume = Balance.from_rao(decoded.get("subnet_volume")).set_unit(netuid)
        tao_in_emission = Balance.from_rao(decoded.get("tao_in_emission")).set_unit(0)
        pending_alpha_emission = Balance.from_rao(
            decoded.get("pending_alpha_emission")
        ).set_unit(netuid)
        pending_root_emission = Balance.from_rao(
            decoded.get("pending_root_emission")
        ).set_unit(0)
        price = (
            Balance.from_tao(1.0)
            if netuid == 0
            else Balance.from_tao(tao_in.tao / alpha_in.tao)
            if alpha_in.tao > 0
            else Balance.from_tao(1)
        )  # TODO: Patching this temporarily for netuid 0

        if decoded.get("subnet_identity"):
            subnet_identity = SubnetIdentity.from_any(decoded.get("subnet_identity"))
        else:
            subnet_identity = None

        return cls(
            netuid=netuid,
            owner_hotkey=owner_hotkey,
            owner_coldkey=owner_coldkey,
            subnet_name=subnet_name,
            symbol=symbol,
            tempo=int(decoded.get("tempo")),
            last_step=int(decoded.get("last_step")),
            blocks_since_last_step=int(decoded.get("blocks_since_last_step")),
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
            network_registered_at=int(decoded.get("network_registered_at")),
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

    def alpha_to_tao_with_slippage(
        self, alpha: Balance
    ) -> tuple[Balance, Balance, float]:
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
class ScheduledColdkeySwapInfo(InfoBase):
    """Dataclass for scheduled coldkey swap information."""

    old_coldkey: str
    new_coldkey: str
    arbitration_block: int

    @classmethod
    def _fix_decoded(cls, decoded: Any) -> "ScheduledColdkeySwapInfo":
        """Fixes the decoded values."""
        return cls(
            old_coldkey=decode_account_id(decoded.get("old_coldkey")),
            new_coldkey=decode_account_id(decoded.get("new_coldkey")),
            arbitration_block=decoded.get("arbitration_block"),
        )


@dataclass
class SubnetState(InfoBase):
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
    def _fix_decoded(cls, decoded: Any) -> "SubnetState":
        netuid = decoded.get("netuid")
        return cls(
            netuid=netuid,
            hotkeys=[decode_account_id(val) for val in decoded.get("hotkeys")],
            coldkeys=[decode_account_id(val) for val in decoded.get("coldkeys")],
            active=decoded.get("active"),
            validator_permit=decoded.get("validator_permit"),
            pruning_score=[
                u16_normalized_float(val) for val in decoded.get("pruning_score")
            ],
            last_update=decoded.get("last_update"),
            emission=[
                Balance.from_rao(val).set_unit(netuid)
                for val in decoded.get("emission")
            ],
            dividends=[u16_normalized_float(val) for val in decoded.get("dividends")],
            incentives=[u16_normalized_float(val) for val in decoded.get("incentives")],
            consensus=[u16_normalized_float(val) for val in decoded.get("consensus")],
            trust=[u16_normalized_float(val) for val in decoded.get("trust")],
            rank=[u16_normalized_float(val) for val in decoded.get("rank")],
            block_at_registration=decoded.get("block_at_registration"),
            alpha_stake=[
                Balance.from_rao(val).set_unit(netuid)
                for val in decoded.get("alpha_stake")
            ],
            tao_stake=[
                Balance.from_rao(val).set_unit(0) for val in decoded.get("tao_stake")
            ],
            total_stake=[
                Balance.from_rao(val).set_unit(netuid)
                for val in decoded.get("total_stake")
            ],
            emission_history=decoded.get("emission_history"),
        )
