import os

BTQS_LOCK_CONFIG_FILE_PATH = os.path.expanduser("~/.bittensor/btqs/btqs-lock.yml")
DEFAULT_WORKSPACE_DIRECTORY = os.path.expanduser("~/Desktop/bittensor_quick_start")

SUBNET_REPO_URL = "https://github.com/opentensor/bittensor-subnet-template.git"
SUBNET_REPO_BRANCH = "ench/abe/commented-info"

# You can add commands with args. Eg: "./neurons/miner.py --model="openai" --safe-mode"
DEFAULT_MINER_COMMAND = "./neurons/miner.py"
DEFAULT_VALIDATOR_COMMAND = "./neurons/validator.py"

SUBTENSOR_REPO_URL = "https://github.com/opentensor/subtensor.git"
SUBTENSOR_BRANCH = "junius/feat-localnet-improve"
RUST_INSTALLATION_VERSION = "nightly-2024-03-05"
RUST_CHECK_VERSION = "rustc 1.78.0-nightly"
RUST_TARGETS = [
    ["rustup", "target", "add", "wasm32-unknown-unknown", "--toolchain", "stable"],
    ["rustup", "component", "add", "rust-src", "--toolchain", "stable"],
]
SUBTENSOR_MACOS_DEPS = ["protobuf"]
SUBTENSOR_LINUX_DEPS = [
    "clang",
    "curl",
    "libssl-dev",
    "llvm",
    "libudev-dev",
    "protobuf-compiler",
]

MINER_URIS = [
    "//Bob",
    "//Charlie",
    "//Dave",
    "//Eve",
    "//Ferdie",
    "//Grace",
    "//Tom",
    "//Ivy",
    "//Judy",
    "//Jerry",
    "//Harry",
    "//Oscar",
    "//Trent",
    "//Victor",
    "//Wendy",
]
VALIDATOR_URI = "//Alice"
SUDO_URI = "//Alice"
MINER_PORTS = [
    8101,
    8102,
    8103,
    8104,
    8105,
    8106,
    8107,
    8108,
    8109,
    8110,
    8111,
    8112,
    8113,
    8114,
    8115,
]
VALIDATOR_PORT = 8100
LOCALNET_ENDPOINT = "ws://127.0.0.1:9945"

EPILOG = "Made with [bold red]:heart:[/bold red] by The Openτensor Foundaτion"
