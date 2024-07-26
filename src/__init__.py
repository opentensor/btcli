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
