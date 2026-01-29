![Screenshot](assets/vantacli.png)

<div align="center">

## Revolutionizing Financial Market Trading

</div>

**Vanta CLI** is a command-line tool that is a fork of bittensor-cli tool for Vanta Network operations. It provides collateral management functionality and extends all standard bittensor-cli operations. Help information can be invoked for every command and option with `--help` option.

## Note

Vanta CLI is under active development. Please report any issues or feedback on the [Vanta CLI GitHub repository](https://github.com/taoshidev/vanta-cli).

### Process Flow
From a high level, here is what happens to register with collateral on Vanta Network.

1. Register your hotkey with Vanta Network: `vanta subnets register`
2. Stake TAO into theta using your own hotkey: `vanta stake add`
3. Collateral deposit, which signs an extrinsic and sends the command off to the super validator. The super validator will then transfer the amount specified into the smart contract: `vanta collateral deposit`
4. (Optional) View collateral amount tracked in the contract: `vanta collateral list`

## Installation

### From Source
```bash
git clone <repository-url>
cd vanta-cli
pip install .
```
### Homebrew (macOS/Linux)
Coming soon

### Pip
Coming soon

## Commands

All commands are prefixed with `vanta`. For example: `vanta wallet list`

### Collateral Operations

#### Deposit Collateral
```bash
vanta collateral deposit [OPTIONS]
```
Deposit collateral to the Vanta Network.

**Options:**
- `--wallet-name, --name` - Name of the wallet to use for collateral (required)
- `--wallet-path` - Path to the wallet directory (default: `~/.bittensor/wallets`)
- `--hotkey, --wallet_hotkey` - Hotkey name or SS58 address of the hotkey
- `--network` - Network to connect to (default: `finney`)
- `--amount` - Amount of TAO to use for collateral (default: None)
- `--prompt/--no-prompt` - Whether to prompt for confirmation

#### List Collateral Balance
```bash
vanta collateral list [OPTIONS]
```
Check collateral balance for a miner address.

**Options:**
- `--wallet-name, --name` - Name of the wallet to use for collateral (required)
- `--wallet-path` - Path to the wallet directory (default: `~/.bittensor/wallets`)
- `--hotkey, --wallet_hotkey` - Hotkey name or SS58 address of the hotkey
- `--network` - Network to connect to (default: `finney`)

#### Withdraw Collateral
```bash
vanta collateral withdraw [OPTIONS]
```
Withdraw collateral from the Vanta Network.

**Options:**
- `--wallet-name, --name` - Name of the wallet (for display purposes)
- `--wallet-path` - Path to wallet directory (default: `~/.bittensor/wallets`)
- `--hotkey, --wallet_hotkey` - Hotkey name or SS58 address of the hotkey
- `--amount` - Amount to withdraw from collateral (required)
- `--prompt/--no-prompt` - Whether to prompt for confirmation

## License
The MIT License (MIT)
