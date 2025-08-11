![Screenshot](assets/ptncli.png)

<div align="center">

## Revolutionizing Financial Market Trading

</div>

**PTNCLI** is a command-line tool that is a fork of bittensor-cli tool for Proprietary Trading Network (PTN) operations. It provides collateral management functionality and extends all standard bittensor-cli opeartions. Help information can be invoked for every command and option with `--help` option.

## Note

PTNCLI is in beta and is still under active development. Please report any issues or feedback on the [PTNCLI GitHub repository](https://github.com/proprietary-trading-network/ptncli).

### Process Flow
From a high level, here is what happens to register with collateral on PTN.

1. Register your hotkey with PTN: `ptncli subnets register`
2. Stake TAO into theta using your own hotkey: `ptncli stake add`
3. Collateral deposit, which under the hood signs an extensic and sends the command off to the super validator. The super validator will then transfer the amount specified into our smart contract: `ptncli collateral deposit`
4. (Optional) View collateral amount tracked in the contract: `ptncli collateral list`

## Installation

### From Source
```bash
git clone <repository-url>
cd ptncli
pip install .
```
### Homebrew (macOS/Linux)
Coming soon

### Pip
Coming soon

## Commands

All commands are prefixed with `ptncli`. For example: `ptncli wallet list`

### Collateral Operations

#### Deposit Collateral
```bash
ptncli collateral deposit [OPTIONS]
```
Deposit collateral to the Proprietary Trading Network.

**Options:**
- `--wallet-name, --name` - Name of the wallet to use for collateral (required)
- `--wallet-path` - Path to the wallet directory (default: `~/.bittensor/wallets`)
- `--hotkey, --wallet_hotkey` - Hotkey name or SS58 address of the hotkey
- `--network` - Network to connect to (default: `finney`)
- `--amount` - Amount of TAO to use for collateral (default: None)
- `--prompt/--no-prompt` - Whether to prompt for confirmation

#### List Collateral Balance
```bash
ptncli collateral list [OPTIONS]
```
Check collateral balance for a miner address.

**Options:**
- `--wallet-name, --name` - Name of the wallet to use for collateral (required)
- `--wallet-path` - Path to the wallet directory (default: `~/.bittensor/wallets`)
- `--hotkey, --wallet_hotkey` - Hotkey name or SS58 address of the hotkey
- `--network` - Network to connect to (default: `finney`)

#### Withdraw Collateral
```bash
ptncli collateral withdraw [OPTIONS]
```
Withdraw collateral from the Proprietary Trading Network.

**Options:**
- `--wallet-name, --name` - Name of the wallet (for display purposes)
- `--wallet-path` - Path to wallet directory (default: `~/.bittensor/wallets`)
- `--hotkey, --wallet_hotkey` - Hotkey name or SS58 address of the hotkey
- `--amount` - Amount to withdraw from collateral (required)
- `--prompt/--no-prompt` - Whether to prompt for confirmation

## License
The MIT License (MIT)
