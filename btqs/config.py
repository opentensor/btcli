import os

CONFIG_FILE_PATH = os.path.expanduser("~/.bittensor/btqs/btqs_config.yml")

BTQS_DIRECTORY = os.path.expanduser("~/.bittensor/btqs")
DEFAULT_WORKSPACE_DIRECTORY = os.path.expanduser("~/Desktop/Bittensor_quick_start")
BTQS_WALLETS_DIRECTORY = os.path.expanduser(os.path.join(DEFAULT_WORKSPACE_DIRECTORY, "wallets"))

SUBNET_TEMPLATE_REPO_URL = "https://github.com/opentensor/bittensor-subnet-template.git"
SUBNET_TEMPLATE_BRANCH = "ench/abe/commented-info"

SUBTENSOR_REPO_URL = "https://github.com/opentensor/subtensor.git"
WALLET_URIS = ["//Bob", "//Charlie"]
VALIDATOR_URI = "//Alice"
MINER_PORTS = [8101, 8102, 8103]

EPILOG = "Made with [bold red]:heart:[/bold red] by The Openτensor Foundaτion"

LOCALNET_ENDPOINT = "ws://127.0.0.1:9945"
