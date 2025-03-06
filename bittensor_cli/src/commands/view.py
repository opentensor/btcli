import asyncio
import json
import os
import tempfile
import webbrowser
import netaddr
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List
from pywry import PyWry

from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.utils import console, WalletLike
from bittensor_wallet import Wallet
from bittensor_cli.src import defaults

root_symbol_html = f"&#x{ord('τ'):X};"


class Encoder(json.JSONEncoder):
    """JSON encoder for serializing dataclasses and balances"""

    def default(self, obj):
        if is_dataclass(obj):
            return asdict(obj)

        elif isinstance(obj, Balance):
            return obj.tao

        return super().default(obj)


async def display_network_dashboard(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    use_wry: bool = False,
    save_file: bool = False,
    dashboard_path: str = None,
    coldkey_ss58: str = None,
) -> bool:
    """
    Generate and display the HTML interface.
    """
    if coldkey_ss58:
        wallet = WalletLike(coldkeypub_ss58=coldkey_ss58, name=coldkey_ss58[:7])
    try:
        with console.status("[dark_sea_green3]Fetching data...", spinner="earth"):
            _subnet_data = await fetch_subnet_data(wallet, subtensor)
            subnet_data = process_subnet_data(_subnet_data)
            html_content = generate_full_page(subnet_data)

        if use_wry:
            console.print(
                "[dark_sea_green3]Opening dashboard in a window. Press Ctrl+C to close.[/dark_sea_green3]"
            )
            window = PyWry()
            window.send_html(
                html=html_content,
                title="Bittensor View",
                width=1200,
                height=800,
            )
            window.start()
            await asyncio.sleep(10)
            try:
                while True:
                    if _has_exited(window):
                        break
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                console.print("\n[yellow]Closing Bittensor View...[/yellow]")
            finally:
                if not _has_exited(window):
                    try:
                        window.close()
                    except Exception:
                        pass
        else:
            if save_file:
                dir_path = os.path.expanduser(dashboard_path)
            else:
                dir_path = os.path.expanduser(defaults.dashboard.path)
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)

            with tempfile.NamedTemporaryFile(
                delete=not save_file,
                suffix=".html",
                mode="w",
                dir=dir_path,
                prefix=f"{wallet.name}_{subnet_data['block_number']}_",
            ) as f:
                f.write(html_content)
                temp_path = f.name
                file_url = f"file://{os.path.abspath(temp_path)}"

                if not save_file:
                    with console.status(
                        "[dark_sea_green3]Loading dashboard...[/dark_sea_green3]",
                        spinner="material",
                    ):
                        webbrowser.open(file_url)
                        await asyncio.sleep(10)
                        return True

            console.print("[green]Dashboard View opened in your browser[/green]")
            console.print(f"[yellow]The HTML file is saved at: {temp_path}[/yellow]")
            webbrowser.open(file_url)
            return True

    except Exception as e:
        print(f"Error: {e}")
        return False


def int_to_ip(int_val: int) -> str:
    """Maps to an ip string"""
    return str(netaddr.IPAddress(int_val))


def get_identity(
    hotkey_ss58: str,
    identities: dict,
    old_identities: dict,
    trucate_length: int = 4,
    return_bool: bool = False,
    lookup_hk: bool = True,
) -> str:
    """Fetch identity of hotkey from both sources"""
    if lookup_hk:
        if hk_identity := identities["hotkeys"].get(hotkey_ss58):
            return hk_identity.get("identity", {}).get("name", "") or hk_identity.get(
                "display", "~"
            )
    else:
        if ck_identity := identities["coldkeys"].get(hotkey_ss58):
            return ck_identity.get("identity", {}).get("name", "") or ck_identity.get(
                "display", "~"
            )

    if old_identity := old_identities.get(hotkey_ss58):
        return old_identity.display
    else:
        if return_bool:
            return False
        else:
            return f"{hotkey_ss58[:trucate_length]}...{hotkey_ss58[-trucate_length:]}"


async def fetch_subnet_data(
    wallet: Wallet, subtensor: "SubtensorInterface"
) -> Dict[str, Any]:
    """
    Fetch subnet data from the network.
    """
    block_hash = await subtensor.substrate.get_chain_head()

    (
        balance,
        stake_info,
        metagraphs_info,
        subnets_info,
        ck_hk_identities,
        old_identities,
        block_number,
    ) = await asyncio.gather(
        subtensor.get_balance(wallet.coldkeypub.ss58_address, block_hash=block_hash),
        subtensor.get_stake_for_coldkey(
            wallet.coldkeypub.ss58_address, block_hash=block_hash
        ),
        subtensor.get_all_metagraphs_info(block_hash=block_hash),
        subtensor.all_subnets(block_hash=block_hash),
        subtensor.fetch_coldkey_hotkey_identities(block_hash=block_hash),
        subtensor.get_delegate_identities(block_hash=block_hash),
        subtensor.substrate.get_block_number(block_hash=block_hash),
    )

    return {
        "balance": balance,
        "stake_info": stake_info,
        "metagraphs_info": metagraphs_info,
        "subnets_info": subnets_info,
        "ck_hk_identities": ck_hk_identities,
        "old_identities": old_identities,
        "wallet": wallet,
        "block_number": block_number,
    }


def process_subnet_data(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process and prepare subnet data.
    """
    balance = raw_data["balance"]
    stake_info = raw_data["stake_info"]
    metagraphs_info = raw_data["metagraphs_info"]
    subnets_info = raw_data["subnets_info"]
    ck_hk_identities = raw_data["ck_hk_identities"]
    old_identities = raw_data["old_identities"]
    wallet = raw_data["wallet"]
    block_number = raw_data["block_number"]

    pool_info = {info.netuid: info for info in subnets_info}

    total_ideal_stake_value = Balance.from_tao(0)
    total_slippage_value = Balance.from_tao(0)

    # Process stake
    stake_dict: Dict[int, List[Dict[str, Any]]] = {}
    for stake in stake_info:
        if stake.stake.tao > 0:
            slippage_value, _, slippage_percentage = pool_info[
                stake.netuid
            ].alpha_to_tao_with_slippage(stake.stake)
            ideal_value = pool_info[stake.netuid].alpha_to_tao(stake.stake)
            total_ideal_stake_value += ideal_value
            total_slippage_value += slippage_value
            stake_dict.setdefault(stake.netuid, []).append(
                {
                    "hotkey": stake.hotkey_ss58,
                    "hotkey_identity": get_identity(
                        stake.hotkey_ss58, ck_hk_identities, old_identities
                    ),
                    "amount": stake.stake.tao,
                    "emission": stake.emission.tao,
                    "is_registered": stake.is_registered,
                    "tao_emission": stake.tao_emission.tao,
                    "ideal_value": ideal_value.tao,
                    "slippage_value": slippage_value.tao,
                    "slippage_percentage": slippage_percentage,
                }
            )

    # Process metagraph
    subnets = []
    for meta_info in metagraphs_info:
        subnet_stakes = stake_dict.get(meta_info.netuid, [])
        metagraph_info = {
            "netuid": meta_info.netuid,
            "name": meta_info.name,
            "symbol": meta_info.symbol,
            "alpha_in": 0 if meta_info.netuid == 0 else meta_info.alpha_in.tao,
            "alpha_out": meta_info.alpha_out.tao,
            "tao_in": 0 if meta_info.netuid == 0 else meta_info.tao_in.tao,
            "tao_in_emission": meta_info.tao_in_emission.tao,
            "num_uids": meta_info.num_uids,
            "max_uids": meta_info.max_uids,
            "moving_price": meta_info.moving_price.tao,
            "blocks_since_last_step": "~"
            if meta_info.netuid == 0
            else meta_info.blocks_since_last_step,
            "tempo": "~" if meta_info.netuid == 0 else meta_info.tempo,
            "registration_allowed": meta_info.registration_allowed,
            "commit_reveal_weights_enabled": meta_info.commit_reveal_weights_enabled,
            "hotkeys": meta_info.hotkeys,
            "coldkeys": meta_info.coldkeys,
            "updated_identities": [],
            "processed_axons": [],
            "rank": meta_info.rank,
            "trust": meta_info.trust,
            "consensus": meta_info.consensus,
            "incentives": meta_info.incentives,
            "dividends": meta_info.dividends,
            "active": meta_info.active,
            "validator_permit": meta_info.validator_permit,
            "pruning_score": meta_info.pruning_score,
            "last_update": meta_info.last_update,
            "block_at_registration": meta_info.block_at_registration,
        }

        # Process axon data and convert IPs
        for axon in meta_info.axons:
            if axon:
                processed_axon = {
                    "ip": int_to_ip(axon["ip"]) if axon["ip"] else "N/A",
                    "port": axon["port"],
                    "ip_type": axon["ip_type"],
                }
                metagraph_info["processed_axons"].append(processed_axon)
            else:
                metagraph_info["processed_axons"].append(None)

        # Add identities
        for hotkey in meta_info.hotkeys:
            identity = get_identity(
                hotkey, ck_hk_identities, old_identities, trucate_length=2
            )
            metagraph_info["updated_identities"].append(identity)

        # Balance conversion
        for field in [
            "emission",
            "alpha_stake",
            "tao_stake",
            "total_stake",
        ]:
            if hasattr(meta_info, field):
                raw_data = getattr(meta_info, field)
                if isinstance(raw_data, list):
                    metagraph_info[field] = [
                        x.tao if hasattr(x, "tao") else x for x in raw_data
                    ]
                else:
                    metagraph_info[field] = raw_data

        # Calculate price
        price = (
            1
            if metagraph_info["netuid"] == 0
            else metagraph_info["tao_in"] / metagraph_info["alpha_in"]
            if metagraph_info["alpha_in"] > 0
            else 0
        )

        # Package it all up
        symbol_html = f"&#x{ord(meta_info.symbol):X};"
        subnets.append(
            {
                "netuid": meta_info.netuid,
                "name": meta_info.name,
                "symbol": symbol_html,
                "price": price,
                "market_cap": float(
                    (metagraph_info["alpha_in"] + metagraph_info["alpha_out"]) * price
                )
                if price
                else 0,
                "emission": metagraph_info["tao_in_emission"],
                "total_stake": metagraph_info["alpha_out"],
                "your_stakes": subnet_stakes,
                "metagraph_info": metagraph_info,
            }
        )
    subnets.sort(key=lambda x: x["market_cap"], reverse=True)

    wallet_identity = get_identity(
        wallet.coldkeypub.ss58_address,
        ck_hk_identities,
        old_identities,
        return_bool=True,
        lookup_hk=False,
    )
    if not wallet_identity:
        wallet_identity = wallet.name
    else:
        wallet_identity = f"{wallet_identity} ({wallet.name})"

    return {
        "wallet_info": {
            "name": wallet_identity,
            "balance": balance.tao,
            "coldkey": wallet.coldkeypub.ss58_address,
            "total_ideal_stake_value": total_ideal_stake_value.tao,
            "total_slippage_value": total_slippage_value.tao,
        },
        "subnets": subnets,
        "block_number": block_number,
    }


def _has_exited(handler) -> bool:
    """Check if PyWry process has cleanly exited with returncode 0."""
    return (
        hasattr(handler, "runner")
        and handler.runner is not None
        and handler.runner.returncode == 0
    )


def generate_full_page(data: Dict[str, Any]) -> str:
    """
    Generate full HTML content for the interface.
    """
    serializable_data = {
        "wallet_info": data["wallet_info"],
        "subnets": data["subnets"],
    }
    wallet_info_json = json.dumps(
        serializable_data["wallet_info"], cls=Encoder
    ).replace("'", "&apos;")
    subnets_json = json.dumps(serializable_data["subnets"], cls=Encoder).replace(
        "'", "&apos;"
    )

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Bittensor CLI Interface</title>
        <style>
            {get_css_styles()}
        </style>
    </head>
    <body>
        <!-- Embedded JSON data used by JS -->
        <div id="initial-data" 
            data-wallet-info='{wallet_info_json}'
            data-subnets='{subnets_json}'>
        </div>
        <div id="splash-screen">
            <div class="splash-content">
                <div class="title-row">
                <h1 class="splash-title">Btcli View</h1>
                <span class="beta-text">Beta</span>
                </div>
            </div>
        </div>
        
        <!-- Main content area -->
        <div id="main-content">
            {generate_main_header(data["wallet_info"], data["block_number"])}
            {generate_main_filters()}
            {generate_subnets_table(data["subnets"])}
        </div>
        
        <!-- Subnet details page (hidden by default) -->
        <div id="subnet-page" style="display: none;">
            {generate_subnet_details_header()}
            {generate_subnet_metrics()}
            {generate_neuron_details()}
        </div>
        
        <script>
            {get_javascript()}
        </script>
    </body>
    </html>
    """


def generate_subnet_details_header() -> str:
    """
    Generates the header section for the subnet details page,
    including the back button, toggle controls, title, and network visualization.
    """
    return """
    <div class="subnet-header">
        <div class="header-row">
            <button class="back-button">&larr; Back</button>
            <div class="toggle-group">
                <label class="toggle-label">
                    <input type="checkbox" id="stake-toggle" onchange="toggleStakeView()">
                    Show Stakes
                </label>
                <label class="toggle-label">
                    <input type="checkbox" id="verbose-toggle" onchange="toggleVerboseNumbers()">
                    Precise Numbers
                </label>
            </div>
        </div>
        
        <div class="subnet-title-row">
            <div class="title-price">
                <h2 id="subnet-title"></h2>
                <div class="subnet-price" id="subnet-price"></div>
            </div>
            <div class="network-visualization-container">
                <div class="network-visualization">
                    <canvas id="network-canvas" width="700" height="80"></canvas>
                </div>
            </div>
        </div>
        <div class="network-metrics">
            <div class="metric-card network-card">
                <div class="metric-label">Moving Price</div>
                <div id="network-moving-price" class="metric-value"></div>
            </div>
            <div class="metric-card network-card">
                <div class="metric-label">Registration</div>
                <div id="network-registration" class="metric-value registration-status"></div>
            </div>
            <div class="metric-card network-card">
                <div class="metric-label">CR Weights</div>
                <div id="network-cr" class="metric-value cr-status"></div>
            </div>
            <div class="metric-card network-card">
                <div class="metric-label">Neurons</div>
                <div id="network-neurons" class="metric-value"></div>
            </div>
            <div class="metric-card network-card">
                <div class="metric-label">Blocks Since Step</div>
                <div id="network-blocks-since-step" class="metric-value"></div>
            </div>
        </div>
    </div>
    """


def generate_subnet_metrics() -> str:
    """
    Generates the metrics section for the subnet details page,
    including market metrics and the stakes table.
    """
    return """
    <div class="metrics-section">
        <div class="metrics-group market-metrics">
            <div class="metric-card">
                <div class="metric-label">Market Cap</div>
                <div id="subnet-market-cap" class="metric-value"></div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Total Stake</div>
                <div id="subnet-total-stake" class="metric-value"></div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Alpha Reserves</div>
                <div id="network-alpha-in" class="metric-value"></div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Tao Reserves</div>
                <div id="network-tau-in" class="metric-value"></div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Emission</div>
                <div id="subnet-emission" class="metric-value"></div>
            </div>
        </div>
    
        <div class="stakes-container">
            <div class="stakes-header">
                <h3 class="view-header">Metagraph</h3>
                <div class="button-group">
                    <button class="manage-button add-stake-button" disabled title="Coming soon">
                        Add Stake (Coming soon)
                    </button>
                    <button class="manage-button export-csv-button" disabled title="Coming soon">
                        Export CSV (Coming soon)
                    </button>
                </div>
            </div>
            
            <div class="stakes-table-container">
                <table class="stakes-table">
                    <thead>
                        <tr>
                            <th>Hotkey</th>
                            <th>Amount</th>
                            <th>Value</th>
                            <th>Value (w/ slippage)</th>
                            <th>Alpha emission</th>
                            <th>Tao emission</th>
                            <th>Registered</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody id="stakes-table-body">
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """


def generate_neuron_details() -> str:
    """
    Generates the neuron detail container, which is hidden by default.
    This section shows detailed information for a selected neuron.
    """
    return """
    <div id="neuron-detail-container" style="display: none;">
        <div class="neuron-detail-header">
            <button class="back-button neuron-detail-back" onclick="closeNeuronDetails()">&larr; Back</button>
        </div>
        <div class="neuron-detail-content">
            <div class="neuron-info-top">
                <h2 class="neuron-name" id="neuron-name"></h2>
                <div class="neuron-keys">
                    <div class="hotkey-label">
                        <span style="color: #FF9900;">Hotkey:</span>
                        <span id="neuron-hotkey" class="truncated-address"></span>
                    </div>
                    <div class="coldkey-label">
                        <span style="color: #FF9900;">Coldkey:</span>
                        <span id="neuron-coldkey" class="truncated-address"></span>
                    </div>
                </div>
            </div>
            <div class="neuron-cards-container">
                <!-- First row: Stakes, Dividends, Incentive, Emissions -->
                <div class="neuron-metrics-row">
                    <div class="metric-card">
                        <div class="metric-label">Stake Weight</div>
                        <div id="neuron-stake-total" class="metric-value formatted-number"
                            data-value="0" data-symbol=""></div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">Stake (Alpha)</div>
                        <div id="neuron-stake-token" class="metric-value formatted-number"
                            data-value="0" data-symbol=""></div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">Stake (Root)</div>
                        <div id="neuron-stake-root" class="metric-value formatted-number"
                            data-value="0" data-symbol="&#x03C4;"></div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">Dividends</div>
                        <div id="neuron-dividends" class="metric-value formatted-number"
                            data-value="0" data-symbol=""></div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">Incentive</div>
                        <div id="neuron-incentive" class="metric-value formatted-number"
                            data-value="0" data-symbol=""></div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">Emissions</div>
                        <div id="neuron-emissions" class="metric-value formatted-number"
                            data-value="0" data-symbol=""></div>
                    </div>
                </div>
                
                <!-- Second row: Rank, Trust, Pruning Score, Validator Permit, Consensus, Last Update -->
                <div class="neuron-metrics-row">
                    <div class="metric-card">
                        <div class="metric-label">Rank</div>
                        <div id="neuron-rank" class="metric-value"></div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">Trust</div>
                        <div id="neuron-trust" class="metric-value"></div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">Pruning Score</div>
                        <div id="neuron-pruning-score" class="metric-value"></div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">Validator Permit</div>
                        <div id="neuron-validator-permit" class="metric-value"></div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">Consensus</div>
                        <div id="neuron-consensus" class="metric-value"></div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">Last Update</div>
                        <div id="neuron-last-update" class="metric-value"></div>
                    </div>
                </div>
                
                <!-- Third row: Reg Block, IP Info, Active -->
                <div class="neuron-metrics-row last-row">
                    <div class="metric-card">
                        <div class="metric-label">Reg Block</div>
                        <div id="neuron-reg-block" class="metric-value"></div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">IP Info</div>
                        <div id="neuron-ipinfo" class="metric-value"></div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">Active</div>
                        <div id="neuron-active" class="metric-value"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """


def generate_main_header(wallet_info: Dict[str, Any], block_number: int) -> str:
    truncated_coldkey = f"{wallet_info['coldkey'][:6]}...{wallet_info['coldkey'][-6:]}"

    # Calculate slippage percentage
    ideal_value = wallet_info["total_ideal_stake_value"]
    slippage_value = wallet_info["total_slippage_value"]
    slippage_percentage = (
        ((ideal_value - slippage_value) / ideal_value * 100) if ideal_value > 0 else 0
    )

    return f"""
    <div class="header">
        <meta charset="UTF-8">
        <div class="wallet-info">
            <span class="wallet-name">{wallet_info["name"]}</span>
            <div class="wallet-address-container" onclick="copyToClipboard('{wallet_info["coldkey"]}', this)">
                <span class="wallet-address" title="Click to copy">{truncated_coldkey}</span>
                <span class="copy-indicator">Copy</span>
            </div>
        </div>
        <div class="stake-metrics">
            <div class="stake-metric">
                <span class="metric-label">Block</span>
                <span class="metric-value" style="color: #FF9900;">{block_number}</span>
            </div>
            <div class="stake-metric">
                <span class="metric-label">Balance</span>
                <span class="metric-value">{wallet_info["balance"]:.4f} {root_symbol_html}</span>
            </div>
            <div class="stake-metric">
                <span class="metric-label">Total Stake Value</span>
                <span class="metric-value">{wallet_info["total_ideal_stake_value"]:.4f} {root_symbol_html}</span>
            </div>
            <div class="stake-metric">
                <span class="metric-label">Slippage Impact</span>
                <span class="metric-value slippage-value">
                    {slippage_percentage:.2f}% <span class="slippage-detail">({wallet_info["total_slippage_value"]:.4f} {root_symbol_html})</span>
                </span>
            </div>
        </div>
    </div>
    """


def generate_main_filters() -> str:
    return """
    <div class="filters-section">
        <div class="search-box">
            <input type="text" id="subnet-search" placeholder="search for name, or netuid..." onkeyup="filterSubnets()">
        </div>
        <div class="filter-toggles">
            <label>
                <input type="checkbox" id="show-verbose" onchange="toggleVerboseNumbers()">
                Precise Numbers
            </label>
            <label>
                <input type="checkbox" id="show-staked" onchange="filterSubnets()">
                Show Only Staked
            </label>
            <label>
                <input type="checkbox" id="show-tiles" onchange="toggleTileView()" checked>
                Tile View
            </label>
            <label class="disabled-label" title="Coming soon">
                <input type="checkbox" id="live-mode" disabled>
                Live Mode (coming soon)
            </label>
        </div>
    </div>
    <div id="subnet-tiles-container" class="subnet-tiles-container"></div>
    """


def generate_subnets_table(subnets: List[Dict[str, Any]]) -> str:
    rows = []
    for subnet in subnets:
        total_your_stake = sum(stake["amount"] for stake in subnet["your_stakes"])
        stake_status = (
            '<span class="stake-status staked">Staked</span>'
            if total_your_stake > 0
            else '<span class="stake-status unstaked">Not Staked</span>'
        )
        rows.append(f"""
            <tr class="subnet-row" onclick="showSubnetPage({subnet["netuid"]})">
                <td class="subnet-name" data-value="{subnet["netuid"]}"><span style="color: #FF9900">{subnet["netuid"]}</span> - {subnet["name"]}</td>
                <td class="price" data-value="{subnet["price"]}"><span class="formatted-number" data-value="{subnet["price"]}" data-symbol="{subnet["symbol"]}"></span></td>
                <td class="market-cap" data-value="{subnet["market_cap"]}"><span class="formatted-number" data-value="{subnet["market_cap"]}" data-symbol="{root_symbol_html}"></span></td>
                <td class="your-stake" data-value="{total_your_stake}"><span class="formatted-number" data-value="{total_your_stake}" data-symbol="{subnet["symbol"]}"></span></td>
                <td class="emission" data-value="{subnet["emission"]}"><span class="formatted-number" data-value="{subnet["emission"]}" data-symbol="{root_symbol_html}"></span></td>
                <td class="stake-status-cell">{stake_status}</td>
            </tr>
        """)
    return f"""
    <div class="subnets-table-container">
        <table class="subnets-table">
            <thead>
                <tr>
                    <th class="sortable" onclick="sortMainTable(0)">Subnet</th>
                    <th class="sortable" onclick="sortMainTable(1)">Price</th>
                    <th class="sortable" onclick="sortMainTable(2)" data-sort="desc">Market Cap</th>
                    <th class="sortable" onclick="sortMainTable(3)">Your Stake</th>
                    <th class="sortable" onclick="sortMainTable(4)">Emission</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
    </div>
    """


def generate_subnet_details_html() -> str:
    return """
    <div id="subnet-modal" class="modal hidden">
        <div class="modal-content">
            <div class="modal-header">
                <h2 class="subnet-title"></h2>
                <button class="close-button" onclick="closeSubnetModal()">&times;</button>
            </div>
            <div class="subnet-overview">
                <div class="overview-item">
                    <span class="label">Price</span>
                    <span class="value price"></span>
                </div>
                <div class="overview-item">
                    <span class="label">Market Cap</span>
                    <span class="value market-cap"></span>
                </div>
                <div class="overview-item">
                    <span class="label">Emission Rate</span>
                    <span class="value emission"></span>
                </div>
                <div class="overview-item">
                    <span class="label">Your Total Stake</span>
                    <span class="value total-stake"></span>
                </div>
            </div>
            <div class="stakes-section">
                <h3>Your Stakes</h3>
                <div class="stakes-list"></div>
            </div>
        </div>
    </div>
    """


def get_css_styles() -> str:
    """Get CSS styles for the interface."""
    return """
        /* ===================== Base Styles & Typography ===================== */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Noto+Sans:wght@400;500;600&display=swap');

        body { 
            font-family: 'Inter', 'Noto Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Arial Unicode MS', sans-serif;
            margin: 0;
            padding: 24px;
            background: #000000;
            color: #ffffff;
        }
        
        input, button, select {
            font-family: inherit;
            font-feature-settings: normal;
        }

        /* ===================== Main Page Header ===================== */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 24px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            margin-bottom: 24px;
            backdrop-filter: blur(10px);
        }

        .wallet-info {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .wallet-name {
            font-size: 1.1em;
            font-weight: 500;
            color: #FF9900;
        }

        .wallet-address-container {
            position: relative;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }

        .wallet-address {
            font-size: 0.9em;
            color: rgba(255, 255, 255, 0.5);
            font-family: monospace;
            transition: color 0.2s ease;
        }
        
        .wallet-address-container:hover .wallet-address {
            color: rgba(255, 255, 255, 0.8);
        }
        
        .copy-indicator {
            background: rgba(255, 153, 0, 0.1);
            color: rgba(255, 153, 0, 0.8);
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.7em;
            transition: all 0.2s ease;
            opacity: 0;
        }
        
        .wallet-address-container:hover .copy-indicator {
            opacity: 1;
            background: rgba(255, 153, 0, 0.2);
        }
        
        .wallet-address-container.copied .copy-indicator {
            opacity: 1;
            background: rgba(255, 153, 0, 0.3);
            color: #FF9900;
        }
        
        .stake-metrics {
            display: flex;
            gap: 24px;
            align-items: center;
        }
        
        .stake-metric {
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 2px;
            position: relative;
            padding: 8px 16px;
            border-radius: 8px;
            transition: all 0.2s ease;
        }
        
        .stake-metric:hover {
            background: rgba(255, 153, 0, 0.05);
        }
        
        .stake-metric .metric-label {
            font-size: 0.8em;
            color: rgba(255, 255, 255, 0.6);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .stake-metric .metric-value {
            font-size: 1.1em;
            font-weight: 500;
            color: #FF9900;
            font-feature-settings: "tnum";
            font-variant-numeric: tabular-nums;
        }
        
        .slippage-value {
            display: flex;
            align-items: center;
            gap: 6px;
        }
        
        .slippage-detail {
            font-size: 0.8em;
            color: rgba(255, 255, 255, 0.5);
        }

        /* ===================== Main Page Filters ===================== */
        .filters-section {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin: 24px 0;
            gap: 16px;
        }

        .search-box input {
            padding: 10px 16px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            background: rgba(255, 255, 255, 0.03);
            color: rgba(255, 255, 255, 0.7);
            width: 240px;
            font-size: 0.9em;
            transition: all 0.2s ease;
        }
        .search-box input::placeholder {
            color: rgba(255, 255, 255, 0.4);
        }

        .search-box input:focus {
            outline: none;
            border-color: rgba(255, 153, 0, 0.5); 
            background: rgba(255, 255, 255, 0.06);
            color: rgba(255, 255, 255, 0.9);
        }

        .filter-toggles {
            display: flex;
            gap: 16px;
        }

        .filter-toggles label {
            display: flex;
            align-items: center;
            gap: 8px;
            color: rgba(255, 255, 255, 0.7);
            font-size: 0.9em;
            cursor: pointer;
            user-select: none;
        }

        /* Checkbox styling for both main page and subnet page */
        .filter-toggles input[type="checkbox"],
        .toggle-label input[type="checkbox"] {
            -webkit-appearance: none;
            -moz-appearance: none;
            appearance: none;
            width: 18px;
            height: 18px;
            border: 2px solid rgba(255, 153, 0, 0.3);
            border-radius: 4px;
            background: rgba(0, 0, 0, 0.2);
            cursor: pointer;
            position: relative;
            transition: all 0.2s ease;
        }

        .filter-toggles input[type="checkbox"]:hover,
        .toggle-label input[type="checkbox"]:hover {
            border-color: #FF9900;
        }

        .filter-toggles input[type="checkbox"]:checked,
        .toggle-label input[type="checkbox"]:checked {
            background: #FF9900;
            border-color: #FF9900;
        }

        .filter-toggles input[type="checkbox"]:checked::after,
        .toggle-label input[type="checkbox"]:checked::after {
            content: '';
            position: absolute;
            left: 5px;
            top: 2px;
            width: 4px;
            height: 8px;
            border: solid #000;
            border-width: 0 2px 2px 0;
            transform: rotate(45deg);
        }

        .filter-toggles label:hover,
        .toggle-label:hover {
            color: rgba(255, 255, 255, 0.9);
        }
        .disabled-label {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .add-stake-button {
            padding: 10px 20px;
            font-size: 0.8rem;
        }
        .export-csv-button {
            padding: 10px 20px;
            font-size: 0.8rem;
        }
        .button-group {
            display: flex;
            gap: 8px;
        }

        /* ===================== Main Page Subnet Table ===================== */
        .subnets-table-container {
            background: rgba(255, 255, 255, 0.02);
            border-radius: 12px;
            overflow: hidden;
        }

        .subnets-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.95em;
        }

        .subnets-table th {
            background: rgba(255, 255, 255, 0.05);
            font-weight: 500;
            text-align: left;
            padding: 16px;
            color: rgba(255, 255, 255, 0.7);
        }

        .subnets-table td {
            padding: 14px 16px;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
        }

        .subnet-row {
            cursor: pointer;
            transition: background-color 0.2s ease;
        }

        .subnet-row:hover {
            background: rgba(255, 255, 255, 0.05);
        }

        .subnet-name {
            color: #ffffff;
            font-weight: 500;
            font-size: 0.95em;
        }

        .price, .market-cap, .your-stake, .emission {
            font-family: 'Inter', monospace;
            font-size: 1.0em;
            font-feature-settings: "tnum";
            font-variant-numeric: tabular-nums;
            letter-spacing: 0.01em;
            white-space: nowrap;
        }

        .stake-status {
            font-size: 0.85em;
            padding: 4px 8px;
            border-radius: 4px;
            background: rgba(255, 255, 255, 0.05);
        }

        .stake-status.staked {
            background: rgba(255, 153, 0, 0.1);
            color: #FF9900;
        }

        .subnets-table th.sortable {
            cursor: pointer;
            position: relative;
            padding-right: 20px;
        }

        .subnets-table th.sortable:hover {
            color: #FF9900;
        }

        .subnets-table th[data-sort] {
            color: #FF9900;
        }

        /* ===================== Subnet Tiles View ===================== */
        .subnet-tiles-container {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 1rem;              
            padding: 1rem;          
        }

        .subnet-tile {
            width: clamp(75px, 6vw, 600px);
            height: clamp(75px, 6vw, 600px);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            position: relative;
            cursor: pointer;
            transition: all 0.2s ease;
            overflow: hidden;
            font-size: clamp(0.6rem, 1vw, 1.4rem);
        }

        .tile-netuid {
            position: absolute;
            top: 0.4em;
            left: 0.4em;
            font-size: 0.7em;
            color: rgba(255, 255, 255, 0.6);
        }

        .tile-symbol {
            font-size: 1.6em;
            margin-bottom: 0.4em;
            color: #FF9900;
        }

        .tile-name {
            display: block;
            width: 100%;                
            white-space: nowrap;        
            overflow: hidden;           
            text-overflow: ellipsis;    
            font-size: 1em;
            text-align: center;
            color: rgba(255, 255, 255, 0.9);
            margin: 0 0.4em;
        }

        .tile-market-cap {
            font-size: 0.9em;
            color: rgba(255, 255, 255, 0.5);
            margin-top: 2px;
        }

        .subnet-tile:hover {
            transform: translateY(-2px);
            box-shadow: 
                0 0 12px rgba(255, 153, 0, 0.6), 
                0 0 24px rgba(255, 153, 0, 0.3);
            background: rgba(255, 255, 255, 0.08);
        }

        .subnet-tile.staked {
            border: 1px solid rgba(255, 153, 0, 0.3);
        }

        .subnet-tile.staked::before {
            content: '';
            position: absolute;
            top: 0.4em;
            right: 0.4em;
            width: 0.5em;
            height: 0.5em;
            border-radius: 50%;
            background: #FF9900;
        }

        /* ===================== Subnet Detail Page Header ===================== */
        .subnet-header {
            padding: 16px;
            border-radius: 12px;
            margin-bottom: 0px;
        }

        .subnet-header h2 {
            margin: 0;
            font-size: 1.3em;
        }

        .subnet-price {
            font-size: 1.3em;
            color: #FF9900;
        }

        .subnet-title-row {
            display: grid;
            grid-template-columns: 300px 1fr 300px;
            align-items: start;
            margin: 0;
            position: relative;
            min-height: 60px;
        }

        .title-price {
            grid-column: 1;
            padding-top: 0;
            margin-top: -10px;
        }

        .header-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            width: 100%;
            margin-bottom: 16px;
        }

        .toggle-group {
            display: flex;
            flex-direction: column;
            gap: 8px;
            align-items: flex-end;
        }

        .toggle-label {
            display: flex;
            align-items: center;
            gap: 8px;
            color: rgba(255, 255, 255, 0.7);
            font-size: 0.9em;
            cursor: pointer;
            user-select: none;
        }

        .back-button {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: rgba(255, 255, 255, 0.8);
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.9em;
            transition: all 0.2s ease;
            margin-bottom: 16px;
        }
        
        .back-button:hover {
            background: rgba(255, 255, 255, 0.1);
            border-color: rgba(255, 255, 255, 0.2);
        }

        /* ===================== Network Visualization ===================== */
        .network-visualization-container {
            position: absolute;
            left: 50%;
            transform: translateX(-50%);
            top: -50px;
            width: 700px;
            height: 80px;
            z-index: 1;
        }

        .network-visualization {
            width: 700px;
            height: 80px;
            position: relative;
        }

        #network-canvas {
            background: transparent;
            position: relative;
            z-index: 1;
        }

        /* Gradient behind visualization */
        .network-visualization::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 100%;
            background: linear-gradient(to bottom, rgba(0, 0, 0, 0.95) 0%, rgba(0, 0, 0, 0.8) 100%);
            z-index: 0;
            pointer-events: none;
        }

        /* ===================== Subnet Detail Metrics ===================== */
        .network-metrics {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 12px;
            margin: 0;
            margin-top: 16px;
        }

        /* Base card styles - applied to both network and metric cards */
        .network-card, .metric-card {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            padding: 12px 16px;
            min-height: 50px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 4px;
        }

        /* Separate styling for moving price value */
        #network-moving-price {
            color: #FF9900;
        }

        .metrics-section {
            margin-top: 0px;
            margin-bottom: 16px;
        }

        .metrics-group {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 12px;
            margin: 0;
            margin-top: 2px;
        }

        .market-metrics .metric-card {
            background: rgba(255, 255, 255, 0.05);
            min-height: 70px;
        }

        .metric-label {
            font-size: 0.85em;
            color: rgba(255, 255, 255, 0.7);
            margin: 0;
        }

        .metric-value {
            font-size: 1.2em;
            line-height: 1.3;
            margin: 0;
        }

        /* Add status colors */
        .registration-status {
            color: #2ECC71;
        }

        .registration-status.closed {
            color: #ff4444;  /* Red color for closed status */
        }

        .cr-status {
            color: #2ECC71;
        }

        .cr-status.disabled {
            color: #ff4444;  /* Red color for disabled status */
        }

        /* ===================== Stakes Table ===================== */
        .stakes-container {
            margin-top: 24px;
            padding: 0 24px;
        }

        .stakes-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }

        .stakes-header h3 {
            font-size: 1.2em;
            color: #ffffff;
            margin: 0;
        }

        .stakes-table-container {
            background: rgba(255, 255, 255, 0.02);
            border-radius: 12px;
            overflow: hidden;
            margin-bottom: 24px;
            width: 100%;
        }

        .stakes-table {
            width: 100%;
            border-collapse: collapse;
        }

        .stakes-table th {
            background: rgba(255, 255, 255, 0.05);
            padding: 16px;
            text-align: left;
            font-weight: 500;
            color: rgba(255, 255, 255, 0.7);
        }

        .stakes-table td {
            padding: 16px;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
        }

        .stakes-table tr {
            transition: background-color 0.2s ease;
        }

        .stakes-table tr:nth-child(even) {
            background: rgba(255, 255, 255, 0.02);
        }

        .stakes-table tr:hover {
            background: transparent;
        }

        .no-stakes-row td {
            text-align: center;
            padding: 32px;
            color: rgba(255, 255, 255, 0.5);
        }

        /* Table styles consistency */
        .stakes-table th, .network-table th {
            background: rgba(255, 255, 255, 0.05);
            padding: 16px;
            text-align: left;
            font-weight: 500;
            color: rgba(255, 255, 255, 0.7);
            transition: color 0.2s ease;
        }

        /* Sortable columns */
        .stakes-table th.sortable, .network-table th.sortable {
            cursor: pointer;
        }

        /* Active sort column - only change color */
        .stakes-table th.sortable[data-sort], .network-table th.sortable[data-sort] {
            color: #FF9900;
        }

        /* Hover effects - only change color */
        .stakes-table th.sortable:hover, .network-table th.sortable:hover {
            color: #FF9900;
        }

        /* Remove hover background from table rows */
        .stakes-table tr:hover {
            background: transparent;
        }

        /* ===================== Network Table ===================== */
        .network-table-container {
            margin-top: 60px;
            position: relative;
            z-index: 2;
            background: rgba(0, 0, 0, 0.8);
        }

        .network-table {
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
        }

        .network-table th {
            background: rgba(255, 255, 255, 0.05);
            padding: 16px;
            text-align: left;
            font-weight: 500;
            color: rgba(255, 255, 255, 0.7);
        }

        .network-table td {
            padding: 16px;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
        }

        .network-table tr {
            cursor: pointer;
            transition: background-color 0.2s ease;
        }

        .network-table tr:hover {
            background-color: rgba(255, 255, 255, 0.05);
        }

        .network-table tr:nth-child(even) {
            background-color: rgba(255, 255, 255, 0.02);
        }

        .network-table tr:nth-child(even):hover {
            background-color: rgba(255, 255, 255, 0.05);
        }

        .network-search-container {
            display: flex;
            align-items: center;
            margin-bottom: 16px;
            padding: 0 16px;
        }

        .network-search {
            width: 100%;
            padding: 12px 16px;
            border: 1px solid rgba(255, 153, 0, 0.2);
            border-radius: 8px;
            background: rgba(0, 0, 0, 0.2);
            color: #ffffff;
            font-size: 0.95em;
            transition: all 0.2s ease;
        }

        .network-search:focus {
            outline: none;
            border-color: rgba(255, 153, 0, 0.5);
            background: rgba(0, 0, 0, 0.3);
            caret-color: #FF9900;
        }

        .network-search::placeholder {
            color: rgba(255, 255, 255, 0.3);
        }

        /* ===================== Cell Styles & Formatting ===================== */
        .hotkey-cell {
            max-width: 200px;
            position: relative;
        }

        .hotkey-container {
            position: relative;
            display: inline-block;
            max-width: 100%;
        }

        .hotkey-identity, .truncated-address {
            color: rgba(255, 255, 255, 0.8);
            display: inline-block;
            max-width: 100%;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .copy-button {
            position: absolute;
            top: -20px; /* Position above the text */
            right: 0;
            background: rgba(255, 153, 0, 0.1);
            color: rgba(255, 255, 255, 0.6);
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.7em;
            cursor: pointer;
            opacity: 0;
            transition: all 0.2s ease;
            transform: translateY(5px);
        }

        .hotkey-container:hover .copy-button {
            opacity: 1;
            transform: translateY(0);
        }

        .copy-button:hover {
            background: rgba(255, 153, 0, 0.2);
            color: #FF9900;
        }

        .address-cell {
            max-width: 150px;
            position: relative;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .address-container {
            display: flex;
            align-items: center;
            cursor: pointer;
            position: relative;
        }

        .address-container:hover::after {
            content: 'Click to copy';
            position: absolute;
            right: 0;
            top: 50%;
            transform: translateY(-50%);
            background: rgba(255, 153, 0, 0.1);
            color: #FF9900;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.8em;
            opacity: 0.8;
        }

        .truncated-address {
            font-family: monospace;
            color: rgba(255, 255, 255, 0.8);
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .truncated-address:hover {
            color: #FF9900;
        }

        .registered-yes {
            color: #FF9900;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 4px;
        }

        .registered-no {
            color: #ff4444;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 4px;
        }

        .manage-button {
            background: rgba(255, 153, 0, 0.1);
            border: 1px solid rgba(255, 153, 0, 0.2);
            color: #FF9900;
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .manage-button:hover {
            background: rgba(255, 153, 0, 0.2);
            transform: translateY(-1px);
        }

        .hotkey-identity {
            display: inline-block;
            max-width: 100%;
            overflow: hidden;
            text-overflow: ellipsis;
            color: #FF9900;
        }

        .identity-cell {
            max-width: 700px;
            font-size: 0.90em;
            letter-spacing: -0.2px;
            color: #FF9900;
        }

        .per-day {
            font-size: 0.75em;
            opacity: 0.7;
            margin-left: 4px;
        }

        /* ===================== Neuron Detail Panel ===================== */
        #neuron-detail-container {
            background: rgba(255, 255, 255, 0.02);
            border-radius: 12px;
            padding: 16px;
            margin-top: 16px;
        }
        
        .neuron-detail-header {
            display: flex;
            align-items: center;
            gap: 16px;
            margin-bottom: 16px;
        }
        
        .neuron-detail-content {
            display: flex;
            flex-direction: column;
            gap: 16px;
        }
        
        .neuron-info-top {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        
        .neuron-keys {
            display: flex;
            flex-direction: column;
            gap: 4px;
            font-size: 0.9em;
            color: rgba(255, 255, 255, 0.6);
            font-size: 1em;
            color: rgba(255, 255, 255, 0.7);
        }
        
        .neuron-cards-container {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .neuron-metrics-row {
            display: grid;
            grid-template-columns: repeat(6, 1fr);
            gap: 12px;
            margin: 0;
        }

        .neuron-metrics-row.last-row {
            grid-template-columns: repeat(3, 1fr);
        }

        /* IP Info styling */
        #neuron-ipinfo {
            font-size: 0.85em;
            line-height: 1.4;
            white-space: nowrap;
        }

        #neuron-ipinfo .no-connection {
            color: #ff4444;
            font-weight: 500;
        }

        /* Adjust metric card for IP info to accommodate multiple lines */
        .neuron-cards-container .metric-card:has(#neuron-ipinfo) {
            min-height: 85px;
        }

        /* ===================== Subnet Page Color Overrides ===================== */
        /* Subnet page specific style */
        .subnet-page .metric-card-title,
        .subnet-page .network-card-title {
            color: rgba(255, 255, 255, 0.7);
        }
        
        .subnet-page .metric-card .metric-value,
        .subnet-page .metric-value {
            color: white;
        }
        
        /* Green values */
        .subnet-page .validator-true,
        .subnet-page .active-yes,
        .subnet-page .registration-open,
        .subnet-page .cr-enabled,
        .subnet-page .ip-info {
            color: #FF9900;
        }
        
        /* Red values */
        .subnet-page .validator-false,
        .subnet-page .active-no,
        .subnet-page .registration-closed,
        .subnet-page .cr-disabled,
        .subnet-page .ip-na {
            color: #ff4444;
        }
        
        /* Keep symbols green in subnet page */
        .subnet-page .symbol {
            color: #FF9900;
        }

        /* ===================== Responsive Styles ===================== */
        @media (max-width: 1200px) {
            .stakes-table {
                display: block;
                overflow-x: auto;
            }
            
            .network-metrics {
                grid-template-columns: repeat(3, 1fr);
            }
        }
        
        @media (min-width: 1201px) {
            .network-metrics {
                                grid-template-columns: repeat(5, 1fr);
            }
        }
        /* ===== Splash Screen ===== */
        #splash-screen {
            position: fixed;
            top: 0; 
            left: 0; 
            width: 100vw;
            height: 100vh;
            background: #000000;
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 999999;
            opacity: 1;
            transition: opacity 1s ease;
        }

        #splash-screen.fade-out {
            opacity: 0;
        }

        .splash-content {
            text-align: center;
            color: #FF9900;
            opacity: 0; 
            animation: fadeIn 1.2s ease forwards;
        }
        @keyframes fadeIn {
            0% {
                opacity: 0;
                transform: scale(0.97);
            }
            100% {
                opacity: 1;
                transform: scale(1);
            }
        }

        /* Title & text styling */
        .title-row {
            display: flex;
            align-items: baseline;
            gap: 1rem;           
        }

        .splash-title {
            font-size: 2.4rem;
            margin: 0;
            padding: 0;
            font-weight: 600;
            color: #FF9900;
        }

        .beta-text {
            font-size: 0.9rem;
            color: #FF9900;
            background: rgba(255, 153, 0, 0.1);
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 500;
        }


    """


def get_javascript() -> str:
    return """
    /* ===================== Global Variables ===================== */
    const root_symbol_html = '&#x03C4;';
    let verboseNumbers = false;

    /* ===================== Clipboard Functions ===================== */
    /**
    * Copies text to clipboard and shows visual feedback
    * @param {string} text The text to copy
    * @param {HTMLElement} element Optional element to show feedback on
    */
    function copyToClipboard(text, element) {
        navigator.clipboard.writeText(text)
            .then(() => {
                const targetElement = element || (event && event.target);
                
                if (targetElement) {
                    const copyIndicator = targetElement.querySelector('.copy-indicator');
                    
                    if (copyIndicator) {
                        const originalText = copyIndicator.textContent;
                        copyIndicator.textContent = 'Copied!';
                        copyIndicator.style.color = '#FF9900';
                        
                        setTimeout(() => {
                            copyIndicator.textContent = originalText;
                            copyIndicator.style.color = '';
                        }, 1000);
                    } else {
                        const originalText = targetElement.textContent;
                        targetElement.textContent = 'Copied!';
                        targetElement.style.color = '#FF9900';
                        
                        setTimeout(() => {
                            targetElement.textContent = originalText;
                            targetElement.style.color = '';
                        }, 1000);
                    }
                }
            })
            .catch(err => {
                console.error('Failed to copy:', err);
            });
    }


    /* ===================== Initialization and DOMContentLoaded Handler ===================== */
    document.addEventListener('DOMContentLoaded', function() {
        try {
            const initialDataElement = document.getElementById('initial-data');
            if (!initialDataElement) {
                throw new Error('Initial data element (#initial-data) not found.');
            }
            window.initialData = {
                wallet_info: JSON.parse(initialDataElement.getAttribute('data-wallet-info')),
                subnets: JSON.parse(initialDataElement.getAttribute('data-subnets'))
            };
        } catch (error) {
            console.error('Error loading initial data:', error);
        }

        // Return to the main list of subnets.
        const backButton = document.querySelector('.back-button');
        if (backButton) {
            backButton.addEventListener('click', function() {
                // First check if neuron details are visible and close them if needed
                const neuronDetails = document.getElementById('neuron-detail-container');
                if (neuronDetails && neuronDetails.style.display !== 'none') {
                    closeNeuronDetails();
                    return; // Stop here, don't go back to main page yet
                }
                
                // Otherwise go back to main subnet list
                document.getElementById('main-content').style.display = 'block';
                document.getElementById('subnet-page').style.display = 'none';
            });
        }
        

        // Splash screen logic
        const splash = document.getElementById('splash-screen');
        const mainContent = document.getElementById('main-content');
        mainContent.style.display = 'none';

        setTimeout(() => {
            splash.classList.add('fade-out');
            splash.addEventListener('transitionend', () => {
                splash.style.display = 'none';
                mainContent.style.display = 'block';
            }, { once: true });
        }, 2000);

        initializeFormattedNumbers();

        // Keep main page's "verbose" checkbox and the Subnet page's "verbose" checkbox in sync
        const mainVerboseCheckbox = document.getElementById('show-verbose');
        const subnetVerboseCheckbox = document.getElementById('verbose-toggle');
        if (mainVerboseCheckbox && subnetVerboseCheckbox) {
            mainVerboseCheckbox.addEventListener('change', function() {
                subnetVerboseCheckbox.checked = this.checked;
                toggleVerboseNumbers();
            });
            subnetVerboseCheckbox.addEventListener('change', function() {
                mainVerboseCheckbox.checked = this.checked;
                toggleVerboseNumbers();
            });
        }

        // Initialize tile view as default
        const tilesContainer = document.getElementById('subnet-tiles-container');
        const tableContainer = document.querySelector('.subnets-table-container');

        // Generate and show tiles
        generateSubnetTiles();
        tilesContainer.style.display = 'flex';
        tableContainer.style.display = 'none';
    });

    /* ===================== Main Page Functions ===================== */
    /**
    * Sort the main Subnets table by the specified column index.
    * Toggles ascending/descending on each click.
    * @param {number} columnIndex Index of the column to sort.
    */
    function sortMainTable(columnIndex) {
        const table = document.querySelector('.subnets-table');
        const headers = table.querySelectorAll('th');
        const header = headers[columnIndex];

        // Determine new sort direction
        let isDescending = header.getAttribute('data-sort') !== 'desc';
        
        // Clear sort markers on all columns, then set the new one
        headers.forEach(th => { th.removeAttribute('data-sort'); });
        header.setAttribute('data-sort', isDescending ? 'desc' : 'asc');

        // Sort rows based on numeric value (or netuid in col 0)
        const tbody = table.querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));
        rows.sort((rowA, rowB) => {
            const cellA = rowA.cells[columnIndex];
            const cellB = rowB.cells[columnIndex];

            // Special handling for the first column with netuid in data-value
            if (columnIndex === 0) {
                const netuidA = parseInt(cellA.getAttribute('data-value'), 10);
                const netuidB = parseInt(cellB.getAttribute('data-value'), 10);
                return isDescending ? (netuidB - netuidA) : (netuidA - netuidB);
            }

            // Otherwise parse float from data-value
            const valueA = parseFloat(cellA.getAttribute('data-value')) || 0;
            const valueB = parseFloat(cellB.getAttribute('data-value')) || 0;
            return isDescending ? (valueB - valueA) : (valueA - valueB);
        });

        // Re-inject rows in sorted order
        tbody.innerHTML = '';
        rows.forEach(row => tbody.appendChild(row));
    }

    /**
    * Filters the main Subnets table rows based on user search and "Show Only Staked" checkbox.
    */
    function filterSubnets() {
        const searchText = document.getElementById('subnet-search').value.toLowerCase();
        const showStaked = document.getElementById('show-staked').checked;
        const showTiles = document.getElementById('show-tiles').checked;
        
        // Filter table rows
        const rows = document.querySelectorAll('.subnet-row');
        rows.forEach(row => {
            const name = row.querySelector('.subnet-name').textContent.toLowerCase();
            const stakeStatus = row.querySelector('.stake-status').textContent; // "Staked" or "Not Staked"

            let isVisible = name.includes(searchText);
            if (showStaked) {
                // If "Show only Staked" is checked, the row must have "Staked" to be visible
                isVisible = isVisible && (stakeStatus === 'Staked');
            }
            row.style.display = isVisible ? '' : 'none';
        });
        
        // Filter tiles if they're being shown
        if (showTiles) {
            const tiles = document.querySelectorAll('.subnet-tile');
            tiles.forEach(tile => {
                const name = tile.querySelector('.tile-name').textContent.toLowerCase();
                const netuid = tile.querySelector('.tile-netuid').textContent;
                const isStaked = tile.classList.contains('staked');
                
                let isVisible = name.includes(searchText) || netuid.includes(searchText);
                if (showStaked) {
                    isVisible = isVisible && isStaked;
                }
                tile.style.display = isVisible ? '' : 'none';
            });
        }
    }


    /* ===================== Subnet Detail Page Functions ===================== */
    /**
    * Displays the Subnet page (detailed view) for the selected netuid.
    * Hides the main content and populates all the metrics / stakes / network table.
    * @param {number} netuid The netuid of the subnet to show in detail.
    */
    function showSubnetPage(netuid) {
        try {
            window.currentSubnet = netuid;
            window.scrollTo(0, 0);

            const subnet = window.initialData.subnets.find(s => s.netuid === parseInt(netuid, 10));
            if (!subnet) {
                throw new Error(`Subnet not found for netuid: ${netuid}`);
            }
            window.currentSubnetSymbol = subnet.symbol;

            // Insert the "metagraph" table beneath the "stakes" table in the hidden container
            const networkTableHTML = `
                <div class="network-table-container" style="display: none;">
                    <div class="network-search-container">
                        <input type="text" class="network-search" placeholder="Search for name, hotkey, or coldkey ss58..."
                            oninput="filterNetworkTable(this.value)" id="network-search">
                    </div>
                    <table class="network-table">
                        <thead>
                            <tr>
                                <th>Name</th>
                                <th>Stake Weight</th>
                                <th>Stake <span style="color: #FF9900">${subnet.symbol}</span></th>
                                <th>Stake <span style="color: #FF9900">${root_symbol_html}</span></th>
                                <th>Dividends</th>
                                <th>Incentive</th>
                                <th>Emissions <span class="per-day">/day</span></th>
                                <th>Hotkey</th>
                                <th>Coldkey</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${generateNetworkTableRows(subnet.metagraph_info)}
                        </tbody>
                    </table>
                </div>
            `;

            // Show/hide main content vs. subnet detail
            document.getElementById('main-content').style.display = 'none';
            document.getElementById('subnet-page').style.display = 'block';

            document.querySelector('#subnet-title').textContent = `${subnet.netuid} - ${subnet.name}`;
            document.querySelector('#subnet-price').innerHTML      = formatNumber(subnet.price, subnet.symbol);
            document.querySelector('#subnet-market-cap').innerHTML = formatNumber(subnet.market_cap, root_symbol_html);
            document.querySelector('#subnet-total-stake').innerHTML= formatNumber(subnet.total_stake, subnet.symbol);
            document.querySelector('#subnet-emission').innerHTML   = formatNumber(subnet.emission, root_symbol_html);


            const metagraphInfo = subnet.metagraph_info;
            document.querySelector('#network-alpha-in').innerHTML  = formatNumber(metagraphInfo.alpha_in, subnet.symbol);
            document.querySelector('#network-tau-in').innerHTML    = formatNumber(metagraphInfo.tao_in, root_symbol_html);
            document.querySelector('#network-moving-price').innerHTML = formatNumber(metagraphInfo.moving_price, subnet.symbol);

            // Registration status
            const registrationElement = document.querySelector('#network-registration');
            registrationElement.textContent = metagraphInfo.registration_allowed ? 'Open' : 'Closed';
            registrationElement.classList.toggle('closed', !metagraphInfo.registration_allowed);

            // Commit-Reveal Weight status
            const crElement = document.querySelector('#network-cr');
            crElement.textContent = metagraphInfo.commit_reveal_weights_enabled ? 'Enabled' : 'Disabled';
            crElement.classList.toggle('disabled', !metagraphInfo.commit_reveal_weights_enabled);

            // Blocks since last step, out of tempo
            document.querySelector('#network-blocks-since-step').innerHTML = 
                `${metagraphInfo.blocks_since_last_step}/${metagraphInfo.tempo}`;

            // Number of neurons vs. max
            document.querySelector('#network-neurons').innerHTML =
                `${metagraphInfo.num_uids}/${metagraphInfo.max_uids}`;

            // Update "Your Stakes" table
            const stakesTableBody = document.querySelector('#stakes-table-body');
            stakesTableBody.innerHTML = '';
            if (subnet.your_stakes && subnet.your_stakes.length > 0) {
                subnet.your_stakes.forEach(stake => {
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td class="hotkey-cell">
                            <div class="hotkey-container">
                                <span class="hotkey-identity" style="color: #FF9900">${stake.hotkey_identity}</span>
                                <!-- Remove the unused event param -->
                                <span class="copy-button" onclick="copyToClipboard('${stake.hotkey}')">copy</span>
                            </div>
                        </td>
                        <td>${formatNumber(stake.amount, subnet.symbol)}</td>
                        <td>${formatNumber(stake.ideal_value, root_symbol_html)}</td>
                        <td>${formatNumber(stake.slippage_value, root_symbol_html)} (${stake.slippage_percentage.toFixed(2)}%)</td>
                        <td>${formatNumber(stake.emission, subnet.symbol + '/day')}</td>
                        <td>${formatNumber(stake.tao_emission, root_symbol_html + '/day')}</td>
                        <td class="registered-cell">
                            <span class="${stake.is_registered ? 'registered-yes' : 'registered-no'}">
                                ${stake.is_registered ? 'Yes' : 'No'}
                            </span>
                        </td>
                        <td class="actions-cell">
                            <button class="manage-button">Coming soon</button>
                        </td>
                    `;
                    stakesTableBody.appendChild(row);
                });
            } else {
                // If no user stake in this subnet
                stakesTableBody.innerHTML = `
                    <tr class="no-stakes-row">
                        <td colspan="8">No stakes found for this subnet</td>
                    </tr>
                `;
            }

            // Remove any previously injected network table then add the new one
            const existingNetworkTable = document.querySelector('.network-table-container');
            if (existingNetworkTable) {
                existingNetworkTable.remove();
            }
            document.querySelector('.stakes-table-container').insertAdjacentHTML('afterend', networkTableHTML);

            // Format the new numbers
            initializeFormattedNumbers();

            // Initialize connectivity visualization (the dots / lines "animation")
            setTimeout(() => { initNetworkVisualization(); }, 100);

            // Toggle whether we are showing the "Your Stakes" or "Metagraph" table
            toggleStakeView();

            // Initialize sorting on newly injected table columns
            initializeSorting();

            // Auto-sort by Stake descending on the network table for convenience
            setTimeout(() => {
                const networkTable = document.querySelector('.network-table');
                if (networkTable) {
                    const stakeColumn = networkTable.querySelector('th:nth-child(2)');
                    if (stakeColumn) {
                        sortTable(networkTable, 1, stakeColumn, true);
                        stakeColumn.setAttribute('data-sort', 'desc');
                    }
                }
            }, 100);

            console.log('Subnet page updated successfully');
        } catch (error) {
            console.error('Error updating subnet page:', error);
        }
    }

    /**
    * Generates the rows for the "Neurons" table (shown when the user unchecks "Show Stakes").
    * Each row, when clicked, calls showNeuronDetails(i).
    * @param {Object} metagraphInfo The "metagraph_info" of the subnet that holds hotkeys, etc.
    */
    function generateNetworkTableRows(metagraphInfo) {
        const rows = [];
        console.log('Generating network table rows with data:', metagraphInfo);

        for (let i = 0; i < metagraphInfo.hotkeys.length; i++) {
            // Subnet symbol is used to show token vs. root stake
            const subnet = window.initialData.subnets.find(s => s.netuid === window.currentSubnet);
            const subnetSymbol = subnet ? subnet.symbol : '';
            
            // Possibly show hotkey/coldkey truncated for readability
            const truncatedHotkey = truncateAddress(metagraphInfo.hotkeys[i]);
            const truncatedColdkey = truncateAddress(metagraphInfo.coldkeys[i]);
            const identityName = metagraphInfo.updated_identities[i] || '~';

            // Root stake is being scaled by 0.18 arbitrarily here
            const adjustedRootStake = metagraphInfo.tao_stake[i] * 0.18;

            rows.push(`
                <tr onclick="showNeuronDetails(${i})">
                    <td class="identity-cell">${identityName}</td>
                    <td data-value="${metagraphInfo.total_stake[i]}">
                        <span class="formatted-number" data-value="${metagraphInfo.total_stake[i]}" data-symbol="${subnetSymbol}"></span>
                    </td>
                    <td data-value="${metagraphInfo.alpha_stake[i]}">
                        <span class="formatted-number" data-value="${metagraphInfo.alpha_stake[i]}" data-symbol="${subnetSymbol}"></span>
                    </td>
                    <td data-value="${adjustedRootStake}">
                        <span class="formatted-number" data-value="${adjustedRootStake}" data-symbol="${root_symbol_html}"></span>
                    </td>
                    <td data-value="${metagraphInfo.dividends[i]}">
                        <span class="formatted-number" data-value="${metagraphInfo.dividends[i]}" data-symbol=""></span>
                    </td>
                    <td data-value="${metagraphInfo.incentives[i]}">
                        <span class="formatted-number" data-value="${metagraphInfo.incentives[i]}" data-symbol=""></span>
                    </td>
                    <td data-value="${metagraphInfo.emission[i]}">
                        <span class="formatted-number" data-value="${metagraphInfo.emission[i]}" data-symbol="${subnetSymbol}"></span>
                    </td>
                    <td class="address-cell">
                        <div class="hotkey-container" data-full-address="${metagraphInfo.hotkeys[i]}">
                            <span class="truncated-address">${truncatedHotkey}</span>
                            <span class="copy-button" onclick="event.stopPropagation(); copyToClipboard('${metagraphInfo.hotkeys[i]}')">copy</span>
                        </div>
                    </td>
                    <td class="address-cell">
                        <div class="hotkey-container" data-full-address="${metagraphInfo.coldkeys[i]}">
                            <span class="truncated-address">${truncatedColdkey}</span>
                            <span class="copy-button" onclick="event.stopPropagation(); copyToClipboard('${metagraphInfo.coldkeys[i]}')">copy</span>
                        </div>
                    </td>
                </tr>
            `);
        }
        return rows.join('');
    }

    /**
    * Handles toggling between the "Your Stakes" view and the "Neurons" view on the Subnet page.
    * The "Show Stakes" checkbox (#stake-toggle) controls which table is visible.
    */
    function toggleStakeView() {
        const showStakes = document.getElementById('stake-toggle').checked;
        const stakesTable = document.querySelector('.stakes-table-container');
        const networkTable = document.querySelector('.network-table-container');
        const sectionHeader = document.querySelector('.view-header');
        const neuronDetails = document.getElementById('neuron-detail-container');
        const addStakeButton = document.querySelector('.add-stake-button');
        const exportCsvButton = document.querySelector('.export-csv-button');
        const stakesHeader = document.querySelector('.stakes-header');

        // First, close neuron details if they're open
        if (neuronDetails && neuronDetails.style.display !== 'none') {
            neuronDetails.style.display = 'none';
        }
        
        // Always show the section header and stakes header when toggling views
        if (sectionHeader) sectionHeader.style.display = 'block';
        if (stakesHeader) stakesHeader.style.display = 'flex';

        if (showStakes) {
            // Show the Stakes table, hide the Neurons table
            stakesTable.style.display = 'block';
            networkTable.style.display = 'none';
            sectionHeader.textContent = 'Your Stakes';
            if (addStakeButton) {
                addStakeButton.style.display = 'none';
            }
            if (exportCsvButton) {
                exportCsvButton.style.display = 'none';
            }
        } else {
            // Show the Neurons table, hide the Stakes table
            stakesTable.style.display = 'none';
            networkTable.style.display = 'block';
            sectionHeader.textContent = 'Metagraph';
            if (addStakeButton) {
                addStakeButton.style.display = 'block';
            }
            if (exportCsvButton) {
                exportCsvButton.style.display = 'block';
            }
        }
    }
    
    /**
    * Called when you click a row in the "Neurons" table, to display more detail about that neuron.
    * This hides the "Neurons" table and shows the #neuron-detail-container.
    * @param {number} rowIndex The index of the neuron in the arrays (hotkeys, coldkeys, etc.)
    */
    function showNeuronDetails(rowIndex) {
        try {
            // Hide the network table & stakes table
            const networkTable = document.querySelector('.network-table-container');
            if (networkTable) networkTable.style.display = 'none';
            const stakesTable = document.querySelector('.stakes-table-container');
            if (stakesTable) stakesTable.style.display = 'none';
            
            // Hide the stakes header with the action buttons
            const stakesHeader = document.querySelector('.stakes-header');
            if (stakesHeader) stakesHeader.style.display = 'none';
            
            // Hide the view header that says "Neurons"
            const viewHeader = document.querySelector('.view-header');
            if (viewHeader) viewHeader.style.display = 'none';

            // Show the neuron detail panel
            const detailContainer = document.getElementById('neuron-detail-container');
            if (detailContainer) detailContainer.style.display = 'block';

            // Pull out the current subnet
            const subnet = window.initialData.subnets.find(s => s.netuid === window.currentSubnet);
            if (!subnet) {
                console.error('No subnet data for netuid:', window.currentSubnet);
                return;
            }

            const metagraphInfo = subnet.metagraph_info;
            const subnetSymbol = subnet.symbol || '';

            // Pull axon data, for IP info
            const axonData = metagraphInfo.processed_axons ? metagraphInfo.processed_axons[rowIndex] : null;
            let ipInfoString;
            
            // Update IP info card - hide header if IP info is present
            const ipInfoCard = document.getElementById('neuron-ipinfo').closest('.metric-card');
            if (axonData && axonData.ip !== 'N/A') {
                // If we have valid IP info, hide the "IP Info" label
                if (ipInfoCard && ipInfoCard.querySelector('.metric-label')) {
                    ipInfoCard.querySelector('.metric-label').style.display = 'none';
                }
                // Format IP info with green labels
                ipInfoString = `<span style="color: #FF9900">IP:</span> ${axonData.ip}<br>` +
                            `<span style="color: #FF9900">Port:</span> ${axonData.port}<br>` +
                            `<span style="color: #FF9900">Type:</span> ${axonData.ip_type}`;
        } else {
                // If no IP info, show the label
                if (ipInfoCard && ipInfoCard.querySelector('.metric-label')) {
                    ipInfoCard.querySelector('.metric-label').style.display = 'block';
                }
                ipInfoString = '<span style="color: #ff4444; font-size: 1.2em;">N/A</span>';
            }
            
            // Basic identity and hotkey/coldkey info
            const name      = metagraphInfo.updated_identities[rowIndex] || '~';
            const hotkey    = metagraphInfo.hotkeys[rowIndex];
            const coldkey   = metagraphInfo.coldkeys[rowIndex];
            const rank      = metagraphInfo.rank ? metagraphInfo.rank[rowIndex] : 0;
            const trust     = metagraphInfo.trust ? metagraphInfo.trust[rowIndex] : 0;
            const pruning   = metagraphInfo.pruning_score ? metagraphInfo.pruning_score[rowIndex] : 0;
            const vPermit   = metagraphInfo.validator_permit ? metagraphInfo.validator_permit[rowIndex] : false;
            const lastUpd   = metagraphInfo.last_update ? metagraphInfo.last_update[rowIndex] : 0;
            const consensus = metagraphInfo.consensus ? metagraphInfo.consensus[rowIndex] : 0;
            const regBlock  = metagraphInfo.block_at_registration ? metagraphInfo.block_at_registration[rowIndex] : 0;
            const active    = metagraphInfo.active ? metagraphInfo.active[rowIndex] : false;

            // Update UI fields
            document.getElementById('neuron-name').textContent = name;
            document.getElementById('neuron-name').style.color = '#FF9900';

            document.getElementById('neuron-hotkey').textContent = hotkey;
            document.getElementById('neuron-coldkey').textContent = coldkey;
            document.getElementById('neuron-trust').textContent = trust.toFixed(4);
            document.getElementById('neuron-pruning-score').textContent = pruning.toFixed(4);

            // Validator
            const validatorElem = document.getElementById('neuron-validator-permit');
            if (vPermit) {
                validatorElem.style.color = '#2ECC71';
                validatorElem.textContent = 'True';
            } else {
                validatorElem.style.color = '#ff4444';
                validatorElem.textContent = 'False';
            }

            document.getElementById('neuron-last-update').textContent = lastUpd;
            document.getElementById('neuron-consensus').textContent = consensus.toFixed(4);
            document.getElementById('neuron-reg-block').textContent = regBlock;
            document.getElementById('neuron-ipinfo').innerHTML = ipInfoString;

            const activeElem = document.getElementById('neuron-active');
            if (active) {
                activeElem.style.color = '#2ECC71';
                activeElem.textContent = 'Yes';
            } else {
                activeElem.style.color = '#ff4444';
                activeElem.textContent = 'No';
            }

            // Add stake data ("total_stake", "alpha_stake", "tao_stake")
            document.getElementById('neuron-stake-total').setAttribute(
                'data-value', metagraphInfo.total_stake[rowIndex]
            );
            document.getElementById('neuron-stake-total').setAttribute(
                'data-symbol', subnetSymbol
            );

            document.getElementById('neuron-stake-token').setAttribute(
                'data-value', metagraphInfo.alpha_stake[rowIndex]
            );
            document.getElementById('neuron-stake-token').setAttribute(
                'data-symbol', subnetSymbol
            );

            // Multiply tao_stake by 0.18
            const originalStakeRoot = metagraphInfo.tao_stake[rowIndex];
            const calculatedStakeRoot = originalStakeRoot * 0.18;

            document.getElementById('neuron-stake-root').setAttribute(
                'data-value', calculatedStakeRoot
            );
            document.getElementById('neuron-stake-root').setAttribute(
                'data-symbol', root_symbol_html
            );
            // Also set the inner text right away, so we show a correct format on load
            document.getElementById('neuron-stake-root').innerHTML =
                formatNumber(calculatedStakeRoot, root_symbol_html);

            // Dividends, Incentive
            document.getElementById('neuron-dividends').setAttribute(
                'data-value', metagraphInfo.dividends[rowIndex]
            );
            document.getElementById('neuron-dividends').setAttribute('data-symbol', '');

            document.getElementById('neuron-incentive').setAttribute(
                'data-value', metagraphInfo.incentives[rowIndex]
            );
            document.getElementById('neuron-incentive').setAttribute('data-symbol', '');

            // Emissions
            document.getElementById('neuron-emissions').setAttribute(
                'data-value', metagraphInfo.emission[rowIndex]
            );
            document.getElementById('neuron-emissions').setAttribute('data-symbol', subnetSymbol);

            // Rank
            document.getElementById('neuron-rank').textContent = rank.toFixed(4);

            // Re-run formatting so the newly updated data-values appear in numeric form
            initializeFormattedNumbers();
        } catch (err) {
            console.error('Error showing neuron details:', err);
        }
    }

    /**
    * Closes the neuron detail panel and goes back to whichever table was selected ("Stakes" or "Metagraph").
    */
    function closeNeuronDetails() {
        // Hide neuron details
        const detailContainer = document.getElementById('neuron-detail-container');
        if (detailContainer) detailContainer.style.display = 'none';
        
        // Show the stakes header with action buttons
        const stakesHeader = document.querySelector('.stakes-header');
        if (stakesHeader) stakesHeader.style.display = 'flex';
        
        // Show the view header again
        const viewHeader = document.querySelector('.view-header');
        if (viewHeader) viewHeader.style.display = 'block';
        
        // Show the appropriate table based on toggle state
        const showStakes = document.getElementById('stake-toggle').checked;
        const stakesTable = document.querySelector('.stakes-table-container');
        const networkTable = document.querySelector('.network-table-container');
        
        if (showStakes) {
            stakesTable.style.display = 'block';
            networkTable.style.display = 'none';
            
            // Hide action buttons when showing stakes
            const addStakeButton = document.querySelector('.add-stake-button');
            const exportCsvButton = document.querySelector('.export-csv-button');
            if (addStakeButton) addStakeButton.style.display = 'none';
            if (exportCsvButton) exportCsvButton.style.display = 'none';
        } else {
            stakesTable.style.display = 'none';
            networkTable.style.display = 'block';
            
            // Show action buttons when showing metagraph
            const addStakeButton = document.querySelector('.add-stake-button');
            const exportCsvButton = document.querySelector('.export-csv-button');
            if (addStakeButton) addStakeButton.style.display = 'block';
            if (exportCsvButton) exportCsvButton.style.display = 'block';
        }
    }


    /* ===================== Number Formatting Functions ===================== */
    /**
     * Toggles the numeric display between "verbose" and "short" notations
     * across all .formatted-number elements on the page.
     */
    function toggleVerboseNumbers() {
        // We read from the main or subnet checkboxes
        verboseNumbers =
            document.getElementById('verbose-toggle')?.checked ||
            document.getElementById('show-verbose')?.checked ||
            false;

        // Reformat all visible .formatted-number elements
        document.querySelectorAll('.formatted-number').forEach(element => {
            const value = parseFloat(element.dataset.value);
            const symbol = element.dataset.symbol;
            element.innerHTML = formatNumber(value, symbol);
        });

        // If we're currently on the Subnet detail page, update those numbers too
        if (document.getElementById('subnet-page').style.display !== 'none') {
            updateAllNumbers();
        }
    }

    /**
     * Scans all .formatted-number elements and replaces their text with
     * the properly formatted version (short or verbose).
     */
    function initializeFormattedNumbers() {
        document.querySelectorAll('.formatted-number').forEach(element => {
            const value = parseFloat(element.dataset.value);
            const symbol = element.dataset.symbol;
            element.innerHTML = formatNumber(value, symbol);
        });
    }

    /**
     * Called by toggleVerboseNumbers() to reformat key metrics on the Subnet page
     * that might not be directly wrapped in .formatted-number but need to be updated anyway.
     */
    function updateAllNumbers() {
        try {
            const subnet = window.initialData.subnets.find(s => s.netuid === window.currentSubnet);
            if (!subnet) {
                console.error('Could not find subnet data for netuid:', window.currentSubnet);
                return;
            }
            // Reformat a few items in the Subnet detail header
            document.querySelector('#subnet-market-cap').innerHTML =
                formatNumber(subnet.market_cap, root_symbol_html);
            document.querySelector('#subnet-total-stake').innerHTML =
                formatNumber(subnet.total_stake, subnet.symbol);
            document.querySelector('#subnet-emission').innerHTML =
                formatNumber(subnet.emission, root_symbol_html);

            // Reformat the Metagraph table data
            const netinfo = subnet.metagraph_info;
            document.querySelector('#network-alpha-in').innerHTML =
                formatNumber(netinfo.alpha_in, subnet.symbol);
            document.querySelector('#network-tau-in').innerHTML =
                formatNumber(netinfo.tao_in, root_symbol_html);

            // Reformat items in "Your Stakes" table
            document.querySelectorAll('#stakes-table-body .formatted-number').forEach(element => {
                const value = parseFloat(element.dataset.value);
                const symbol = element.dataset.symbol;
                element.innerHTML = formatNumber(value, symbol);
            });
        } catch (error) {
            console.error('Error updating numbers:', error);
        }
    }
    
    /**
    * Format a numeric value into either:
    *  - a short format (e.g. 1.23k, 3.45m) if verboseNumbers==false
    *  - a more precise format (1,234.5678) if verboseNumbers==true
    * @param {number} num The numeric value to format.
    * @param {string} symbol A short suffix or currency symbol (e.g. 'τ') that we append.
    */
    function formatNumber(num, symbol = '') {
        if (num === undefined || num === null || isNaN(num)) {
            return '0.00 ' + `<span style="color: #FF9900">${symbol}</span>`;
        }
        num = parseFloat(num);
        if (num === 0) {
            return '0.00 ' + `<span style="color: #FF9900">${symbol}</span>`;
        }

        // If user requested verbose
        if (verboseNumbers) {
            return num.toLocaleString('en-US', { 
                minimumFractionDigits: 4, 
                maximumFractionDigits: 4 
            }) + ' ' + `<span style="color: #FF9900">${symbol}</span>`;
        }

        // Otherwise show short scale for large numbers
        const absNum = Math.abs(num);
        if (absNum >= 1000) {
            const suffixes = ['', 'k', 'm', 'b', 't'];
            const magnitude = Math.min(4, Math.floor(Math.log10(absNum) / 3));
            const scaledNum = num / Math.pow(10, magnitude * 3);
            return scaledNum.toFixed(2) + suffixes[magnitude] + ' ' +
                `<span style="color: #FF9900">${symbol}</span>`;
        } else {
            // For small numbers <1000, just show 4 decimals
            return num.toFixed(4) + ' ' + `<span style="color: #FF9900">${symbol}</span>`;
        }
    }

    /**
    * Truncates a string address into the format "ABC..XYZ" for a bit more readability
    * @param {string} address 
    * @returns {string} truncated address form
    */
    function truncateAddress(address) {
        if (!address || address.length <= 7) {
            return address; // no need to truncate if very short
        }
        return `${address.substring(0, 3)}..${address.substring(address.length - 3)}`;
    }

    /**
    * Format a number in compact notation (K, M, B) for tile display
    */
    function formatTileNumbers(num) {
        if (num >= 1000000000) {
            return (num / 1000000000).toFixed(1) + 'B';
        } else if (num >= 1000000) {
            return (num / 1000000).toFixed(1) + 'M';
        } else if (num >= 1000) {
            return (num / 1000).toFixed(1) + 'K';
        } else {
            return num.toFixed(1);
        }
    }


    /* ===================== Table Sorting and Filtering Functions ===================== */
    /**
    * Switches the Metagraph or Stakes table from sorting ascending to descending on a column, and vice versa.
    * @param {HTMLTableElement} table The table element itself
    * @param {number} columnIndex The column index to sort by
    * @param {HTMLTableHeaderCellElement} header The <th> element clicked
    * @param {boolean} forceDescending If true and no existing sort marker, will do a descending sort by default
    */
    function sortTable(table, columnIndex, header, forceDescending = false) {
        const tbody = table.querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));

        // If forcing descending and the header has no 'data-sort', default to 'desc'
        let isDescending;
        if (forceDescending && !header.hasAttribute('data-sort')) {
            isDescending = true;
        } else {
            isDescending = header.getAttribute('data-sort') !== 'desc';
        }

        // Clear data-sort from all headers in the table
        table.querySelectorAll('th').forEach(th => {
            th.removeAttribute('data-sort');
        });
        // Mark the clicked header with new direction
        header.setAttribute('data-sort', isDescending ? 'desc' : 'asc');

        // Sort numerically
        rows.sort((rowA, rowB) => {
            const cellA = rowA.cells[columnIndex];
            const cellB = rowB.cells[columnIndex];

            // Attempt to parse float from data-value or fallback to textContent
            let valueA = parseFloat(cellA.getAttribute('data-value')) ||
                        parseFloat(cellA.textContent.replace(/[^\\d.-]/g, '')) ||
                        0;
            let valueB = parseFloat(cellB.getAttribute('data-value')) ||
                        parseFloat(cellB.textContent.replace(/[^\\d.-]/g, '')) ||
                        0;

            return isDescending ? (valueB - valueA) : (valueA - valueB);
        });

        // Reinsert sorted rows
        tbody.innerHTML = '';
        rows.forEach(row => tbody.appendChild(row));
    }

    /**
    * Adds sortable behavior to certain columns in the "stakes-table" or "network-table".
    * Called after these tables are created in showSubnetPage().
    */
    function initializeSorting() {
        const networkTable = document.querySelector('.network-table');
        if (networkTable) {
            initializeTableSorting(networkTable);
        }
        const stakesTable = document.querySelector('.stakes-table');
        if (stakesTable) {
            initializeTableSorting(stakesTable);
        }
    }

    /**
    * Helper function that attaches sort handlers to appropriate columns in a table.
    * @param {HTMLTableElement} table The table element to set up sorting for.
    */
    function initializeTableSorting(table) {
        const headers = table.querySelectorAll('th');
        headers.forEach((header, index) => {
            // We only want some columns to be sortable, as in original code
            if (table.classList.contains('stakes-table') && index >= 1 && index <= 5) {
                header.classList.add('sortable');
                header.addEventListener('click', () => {
                    sortTable(table, index, header, true);
                });
            } else if (table.classList.contains('network-table') && index < 6) {
                header.classList.add('sortable');
                header.addEventListener('click', () => {
                    sortTable(table, index, header, true);
                });
            }
        });
    }

    /**
    * Filters rows in the Metagraph table by name, hotkey, or coldkey.
    * Invoked by the oninput event of the #network-search field.
    * @param {string} searchValue The substring typed by the user.
    */
    function filterNetworkTable(searchValue) {
        const searchTerm = searchValue.toLowerCase().trim();
        const rows = document.querySelectorAll('.network-table tbody tr');

        rows.forEach(row => {
            const nameCell = row.querySelector('.identity-cell');
            const hotkeyContainer = row.querySelector('.hotkey-container[data-full-address]');
            const coldkeyContainer = row.querySelectorAll('.hotkey-container[data-full-address]')[1];

            const name   = nameCell ? nameCell.textContent.toLowerCase() : '';
            const hotkey = hotkeyContainer ? hotkeyContainer.getAttribute('data-full-address').toLowerCase() : '';
            const coldkey= coldkeyContainer ? coldkeyContainer.getAttribute('data-full-address').toLowerCase() : '';

            const matches = (name.includes(searchTerm) || hotkey.includes(searchTerm) || coldkey.includes(searchTerm));
            row.style.display = matches ? '' : 'none';
        });
    }


    /* ===================== Network Visualization Functions ===================== */
    /**
    * Initializes the network visualization on the canvas element.
    */
    function initNetworkVisualization() {
        try {
            const canvas = document.getElementById('network-canvas');
            if (!canvas) {
                console.error('Canvas element (#network-canvas) not found');
                return;
            }
            const ctx = canvas.getContext('2d');

            const subnet = window.initialData.subnets.find(s => s.netuid === window.currentSubnet);
            if (!subnet) {
                console.error('Could not find subnet data for netuid:', window.currentSubnet);
                return;
            }
            const numNeurons = subnet.metagraph_info.num_uids;
            const nodes = [];

            // Randomly place nodes, each with a small velocity
            for (let i = 0; i < numNeurons; i++) {
                nodes.push({
                    x: Math.random() * canvas.width,
                    y: Math.random() * canvas.height,
                    radius: 2,
                    vx: (Math.random() - 0.5) * 0.5,
                    vy: (Math.random() - 0.5) * 0.5
                });
            }

            // Animation loop
            function animate() {
                ctx.clearRect(0, 0, canvas.width, canvas.height);

                ctx.beginPath();
                ctx.strokeStyle = 'rgba(255, 153, 0, 0.2)';
                for (let i = 0; i < nodes.length; i++) {
                    for (let j = i + 1; j < nodes.length; j++) {
                        const dx = nodes[i].x - nodes[j].x;
                        const dy = nodes[i].y - nodes[j].y;
                        const distance = Math.sqrt(dx * dx + dy * dy);
                        if (distance < 30) {
                            ctx.moveTo(nodes[i].x, nodes[i].y);
                            ctx.lineTo(nodes[j].x, nodes[j].y);
                        }
                    }
                }
                ctx.stroke();

                nodes.forEach(node => {
                    node.x += node.vx;
                    node.y += node.vy;

                    // Bounce them off the edges
                    if (node.x <= 0 || node.x >= canvas.width)  node.vx *= -1;
                    if (node.y <= 0 || node.y >= canvas.height) node.vy *= -1;

                    ctx.beginPath();
                    ctx.fillStyle = '#FF9900';
                    ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
                    ctx.fill();
                });

                requestAnimationFrame(animate);
            }
            animate();
        } catch (error) {
            console.error('Error in network visualization:', error);
        }
    }


    /* ===================== Tile View Functions ===================== */
    /**
    * Toggles between the tile view and table view of subnets.
     */
    function toggleTileView() {
        const showTiles = document.getElementById('show-tiles').checked;
        const tilesContainer = document.getElementById('subnet-tiles-container');
        const tableContainer = document.querySelector('.subnets-table-container');
        
        if (showTiles) {
            // Show tiles, hide table
            tilesContainer.style.display = 'flex';
            tableContainer.style.display = 'none';
            
            // Generate tiles if they don't exist yet
            if (tilesContainer.children.length === 0) {
                generateSubnetTiles();
            }
            
            // Apply current filters to the tiles
            filterSubnets();
        } else {
            // Show table, hide tiles
            tilesContainer.style.display = 'none';
            tableContainer.style.display = 'block';
        }
    }
    
    /**
    * Generates the subnet tiles based on the initialData.
     */
    function generateSubnetTiles() {
        const tilesContainer = document.getElementById('subnet-tiles-container');
        tilesContainer.innerHTML = ''; // Clear existing tiles
        
        // Sort subnets by market cap (descending)
        const sortedSubnets = [...window.initialData.subnets].sort((a, b) => b.market_cap - a.market_cap);
        
        sortedSubnets.forEach(subnet => {
            const isStaked = subnet.your_stakes && subnet.your_stakes.length > 0;
            const marketCapFormatted = formatTileNumbers(subnet.market_cap);
            
            const tile = document.createElement('div');
            tile.className = `subnet-tile ${isStaked ? 'staked' : ''}`;
            tile.onclick = () => showSubnetPage(subnet.netuid);
            
            // Calculate background intensity based on market cap relative to max
            const maxMarketCap = sortedSubnets[0].market_cap;
            const intensity = Math.max(5, Math.min(15, 5 + (subnet.market_cap / maxMarketCap) * 10));
            
            tile.innerHTML = `
                <span class="tile-netuid">${subnet.netuid}</span>
                <span class="tile-symbol">${subnet.symbol}</span>
                <span class="tile-name">${subnet.name}</span>
                <span class="tile-market-cap">${marketCapFormatted} ${root_symbol_html}</span>
            `;
            
            // Set background intensity
            tile.style.background = `rgba(255, 255, 255, 0.0${intensity.toFixed(0)})`;
            
            tilesContainer.appendChild(tile);
        });
    }
    """
