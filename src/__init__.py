from dataclasses import dataclass
from typing import Optional


class Constants:
    networks = ["local", "finney", "test", "archive"]
    finney_entrypoint = "wss://entrypoint-finney.opentensor.ai:443"
    finney_test_entrypoint = "wss://test.finney.opentensor.ai:443/"
    archive_entrypoint = "wss://archive.chain.opentensor.ai:443/"
    network_map = {
        "finney": finney_entrypoint,
        "test": finney_test_entrypoint,
        "archive": archive_entrypoint,
    }
    delegates_details_url = (
        "https://raw.githubusercontent.com/opentensor/"
        "bittensor-delegates/main/public/delegates.json"
    )


@dataclass
class DelegatesDetails:
    name: str
    url: str
    description: str
    signature: str

    @classmethod
    def from_json(cls, json: dict[str, any]) -> "DelegatesDetails":
        return cls(
            name=json["name"],
            url=json["url"],
            description=json["description"],
            signature=json["signature"],
        )


@dataclass
class CUDA:
    dev_id: list[int]
    use_cuda: bool
    tpb: int


@dataclass
class PoWRegister:
    num_processes: Optional[int]
    update_interval: int
    output_in_place: bool
    verbose: bool
    cuda: CUDA


@dataclass
class Wallet:
    name: str
    hotkey: str
    path: str


@dataclass
class Logging:
    # likely needs to be changed
    debug: bool
    trace: bool
    record_log: bool
    logging_dir: str


@dataclass
class Subtensor:
    network: str
    chain_endpoint: Optional[str]
    _mock: bool


@dataclass
class Defaults:
    netuid: int
    subtensor: Subtensor
    pow_register: PoWRegister
    wallet: Wallet
    logging: Logging


defaults = Defaults(
    netuid=1,
    subtensor=Subtensor(network="finney", chain_endpoint=None, _mock=False),
    pow_register=PoWRegister(
        num_processes=None,
        update_interval=50000,
        output_in_place=True,
        verbose=False,
        cuda=CUDA(dev_id=[0], use_cuda=False, tpb=256),
    ),
    wallet=Wallet(name="default", hotkey="default", path="~/.bittensor/wallets/"),
    logging=Logging(
        debug=False, trace=False, record_log=False, logging_dir="~/.bittensor/miners"
    ),
)


TYPE_REGISTRY = {
    "types": {
        "Balance": "u64",  # Need to override default u128
    },
    "runtime_api": {
        "NeuronInfoRuntimeApi": {
            "methods": {
                "get_neuron_lite": {
                    "params": [
                        {
                            "name": "netuid",
                            "type": "u16",
                        },
                        {
                            "name": "uid",
                            "type": "u16",
                        },
                    ],
                    "type": "Vec<u8>",
                },
                "get_neurons_lite": {
                    "params": [
                        {
                            "name": "netuid",
                            "type": "u16",
                        },
                    ],
                    "type": "Vec<u8>",
                },
            }
        },
        "StakeInfoRuntimeApi": {
            "methods": {
                "get_stake_info_for_coldkey": {
                    "params": [
                        {
                            "name": "coldkey_account_vec",
                            "type": "Vec<u8>",
                        },
                    ],
                    "type": "Vec<u8>",
                },
                "get_stake_info_for_coldkeys": {
                    "params": [
                        {
                            "name": "coldkey_account_vecs",
                            "type": "Vec<Vec<u8>>",
                        },
                    ],
                    "type": "Vec<u8>",
                },
            },
        },
        "ValidatorIPRuntimeApi": {
            "methods": {
                "get_associated_validator_ip_info_for_subnet": {
                    "params": [
                        {
                            "name": "netuid",
                            "type": "u16",
                        },
                    ],
                    "type": "Vec<u8>",
                },
            },
        },
        "SubnetInfoRuntimeApi": {
            "methods": {
                "get_subnet_hyperparams": {
                    "params": [
                        {
                            "name": "netuid",
                            "type": "u16",
                        },
                    ],
                    "type": "Vec<u8>",
                }
            }
        },
        "SubnetRegistrationRuntimeApi": {
            "methods": {"get_network_registration_cost": {"params": [], "type": "u64"}}
        },
    },
}

NETWORK_EXPLORER_MAP = {
    "opentensor": {
        "local": "https://polkadot.js.org/apps/?rpc=wss%3A%2F%2Fentrypoint-finney.opentensor.ai%3A443#/explorer",
        "endpoint": "https://polkadot.js.org/apps/?rpc=wss%3A%2F%2Fentrypoint-finney.opentensor.ai%3A443#/explorer",
        "finney": "https://polkadot.js.org/apps/?rpc=wss%3A%2F%2Fentrypoint-finney.opentensor.ai%3A443#/explorer",
    },
    "taostats": {
        "local": "https://x.taostats.io",
        "endpoint": "https://x.taostats.io",
        "finney": "https://x.taostats.io",
    },
}
