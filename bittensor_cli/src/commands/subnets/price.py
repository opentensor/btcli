import asyncio
import json
import math
from pywry import PyWry
from typing import TYPE_CHECKING

import plotille
import plotly.graph_objects as go

from bittensor_cli.src import COLOR_PALETTE
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    get_subnet_name,
    print_error,
    json_console,
)

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


async def price(
    subtensor: "SubtensorInterface",
    netuids: list[int],
    all_netuids: bool = False,
    interval_hours: int = 24,
    html_output: bool = False,
    log_scale: bool = False,
    json_output: bool = False,
):
    """
    Fetch historical price data for subnets and display it in a chart.
    """
    if all_netuids:
        netuids = [nid for nid in await subtensor.get_all_subnet_netuids() if nid != 0]

    blocks_per_hour = int(3600 / 12)  # ~300 blocks per hour
    total_blocks = blocks_per_hour * interval_hours

    with console.status(":chart_increasing: Fetching historical price data..."):
        current_block_hash = await subtensor.substrate.get_chain_head()
        current_block = await subtensor.substrate.get_block_number(current_block_hash)

        step = 300
        start_block = max(0, current_block - total_blocks)
        block_numbers = list(range(start_block, current_block + 1, step))

        # Block hashes
        block_hash_cors = [
            subtensor.substrate.get_block_hash(bn) for bn in block_numbers
        ]
        block_hashes = await asyncio.gather(*block_hash_cors)

        # We fetch all subnets when there is more than one netuid
        if all_netuids or len(netuids) > 1:
            subnet_info_cors = [subtensor.all_subnets(bh) for bh in block_hashes]
        else:
            # If there is only one netuid, we fetch the subnet info for that netuid
            netuid = netuids[0]
            subnet_info_cors = [subtensor.subnet(netuid, bh) for bh in block_hashes]
        all_subnet_infos = await asyncio.gather(*subnet_info_cors)

        subnet_data = _process_subnet_data(
            block_numbers, all_subnet_infos, netuids, all_netuids
        )

    if not subnet_data:
        err_console.print("[red]No valid price data found for any subnet[/red]")
        return

    if html_output:
        await _generate_html_output(
            subnet_data, block_numbers, interval_hours, log_scale
        )
    elif json_output:
        json_console.print(json.dumps(_generate_json_output(subnet_data)))
    else:
        _generate_cli_output(subnet_data, block_numbers, interval_hours, log_scale)


def _process_subnet_data(block_numbers, all_subnet_infos, netuids, all_netuids):
    """
    Process subnet data into a structured format for price analysis.
    """
    subnet_data = {}
    if all_netuids or len(netuids) > 1:
        for netuid in netuids:
            prices = []
            valid_subnet_infos = []
            for _, subnet_infos in zip(block_numbers, all_subnet_infos):
                subnet_info = next(
                    (s for s in subnet_infos if s.netuid == netuid), None
                )
                if subnet_info:
                    prices.append(subnet_info.price.tao)
                    valid_subnet_infos.append(subnet_info)

            if not valid_subnet_infos or not prices:
                # No valid data found for this netuid
                continue

            if len(prices) < 5:
                err_console.print(
                    f"[red]Insufficient price data for subnet {netuid}. "
                    f"Need at least 5 data points but only found {len(prices)}.[/red]"
                )
                continue

            # Most recent data for statistics
            latest_subnet_data = valid_subnet_infos[-1]
            stats = {
                "current_price": prices[-1],
                "high": max(prices),
                "low": min(prices),
                "change_pct": ((prices[-1] - prices[0]) / prices[0] * 100),
                "supply": latest_subnet_data.alpha_in.tao
                + latest_subnet_data.alpha_out.tao,
                "market_cap": latest_subnet_data.price.tao
                * (latest_subnet_data.alpha_in.tao + latest_subnet_data.alpha_out.tao),
                "emission": latest_subnet_data.emission.tao,
                "stake": latest_subnet_data.alpha_out.tao,
                "symbol": latest_subnet_data.symbol,
                "name": get_subnet_name(latest_subnet_data),
            }
            subnet_data[netuid] = {
                "prices": prices,
                "stats": stats,
            }

    else:
        prices = []
        valid_subnet_infos = []
        for _, subnet_info in zip(block_numbers, all_subnet_infos):
            if subnet_info:
                prices.append(subnet_info.price.tao)
                valid_subnet_infos.append(subnet_info)

        if not valid_subnet_infos or not prices:
            err_console.print("[red]No valid price data found for any subnet[/red]")
            return {}

        if len(prices) < 5:
            err_console.print(
                f"[red]Insufficient price data for subnet {netuids[0]}. "
                f"Need at least 5 data points but only found {len(prices)}.[/red]"
            )
            return {}

        # Most recent data for statistics
        latest_subnet_data = valid_subnet_infos[-1]
        stats = {
            "current_price": prices[-1],
            "high": max(prices),
            "low": min(prices),
            "change_pct": ((prices[-1] - prices[0]) / prices[0] * 100),
            "supply": latest_subnet_data.alpha_in.tao
            + latest_subnet_data.alpha_out.tao,
            "market_cap": latest_subnet_data.price.tao
            * (latest_subnet_data.alpha_in.tao + latest_subnet_data.alpha_out.tao),
            "emission": latest_subnet_data.emission.tao,
            "stake": latest_subnet_data.alpha_out.tao,
            "symbol": latest_subnet_data.symbol,
            "name": get_subnet_name(latest_subnet_data),
        }
        subnet_data[netuids[0]] = {
            "prices": prices,
            "stats": stats,
        }

    # Sort results by market cap
    sorted_subnet_data = dict(
        sorted(
            subnet_data.items(),
            key=lambda x: x[1]["stats"]["market_cap"],
            reverse=True,
        )
    )
    return sorted_subnet_data


def _generate_html_single_subnet(
    netuid,
    data,
    block_numbers,
    interval_hours,
    log_scale,
):
    """
    Generate an HTML chart for a single subnet.
    """
    stats = data["stats"]
    prices = data["prices"]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=block_numbers,
            y=prices,
            mode="lines",
            name=f"Subnet {netuid} - {stats['name']}"
            if stats["name"]
            else f"Subnet {netuid}",
            line=dict(width=2, color="#50C878"),
        )
    )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#000000",
        plot_bgcolor="#000000",
        font=dict(color="white"),
        showlegend=True,
        legend=dict(
            x=1.02,
            y=1.0,
            xanchor="left",
            yanchor="top",
            bgcolor="rgba(0,0,0,0)",
            bordercolor="rgba(255,255,255,0.2)",
            borderwidth=1,
        ),
        margin=dict(t=160, r=50, b=50, l=50),
        height=600,
    )

    price_title = f"Price ({stats['symbol']})"
    if log_scale:
        price_title += " Log Scale"

    # Label axes
    fig.update_xaxes(
        title="Block",
        gridcolor="rgba(128,128,128,0.2)",
        zerolinecolor="rgba(128,128,128,0.2)",
        type="log" if log_scale else "linear",
    )
    fig.update_yaxes(
        title=price_title,
        gridcolor="rgba(128,128,128,0.2)",
        zerolinecolor="rgba(128,128,128,0.2)",
        type="log" if log_scale else "linear",
    )

    # Price change color
    price_change_class = "text-green" if stats["change_pct"] > 0 else "text-red"
    # Change sign
    sign_icon = "▲" if stats["change_pct"] > 0 else "▼"

    fig_dict = fig.to_dict()
    fig_json = json.dumps(fig_dict)
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Subnet Price View</title>
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        <style>
            body {{
                background-color: #000;
                color: #fff;
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
            }}
            .header-container {{
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                margin-bottom: 20px;
            }}
            .price-info {{
                max-width: 60%;
            }}
            .main-price {{
                font-size: 36px;
                font-weight: 600;
                margin-bottom: 5px;
            }}
            .price-change {{
                font-size: 18px;
                margin-left: 8px;
                font-weight: 500;
            }}
            .text-green {{ color: #00FF00; }}
            .text-red   {{ color: #FF5555; }}
            .text-blue  {{ color: #87CEEB; }}
            .text-steel {{ color: #4682B4; }}
            .text-purple{{ color: #DDA0DD; }}
            .text-gold  {{ color: #FFD700; }}

            .sub-stats-row {{
                display: flex;
                flex-wrap: wrap;
                margin-top: 10px;
            }}
            .stat-item {{
                margin-right: 20px;
                margin-bottom: 6px;
                font-size: 14px;
            }}
            .side-stats {{
                min-width: 220px;
                display: flex;
                flex-direction: column;
                align-items: flex-start;
            }}
            .side-stats div {{
                margin-bottom: 6px;
                font-size: 14px;
            }}
            #chart-container {{
                margin-top: 20px;
                width: 100%;
                height: 600px;
            }}
        </style>
    </head>
    <body>
        <div class="header-container">
            <div class="price-info">
                <div class="main-price">
                    {stats['current_price']:.6f} {stats['symbol']}
                    <span class="price-change {price_change_class}">
                        {sign_icon} {abs(stats['change_pct']):.2f}%
                    </span>
                </div>
                <div class="sub-stats-row">
                    <div class="stat-item">
                        {interval_hours}h High: <span class="text-green">{stats['high']:.6f} {stats['symbol']}</span>
                    </div>
                    <div class="stat-item">
                        {interval_hours}h Low: <span class="text-red">{stats['low']:.6f} {stats['symbol']}</span>
                    </div>
                </div>
            </div>
            <div class="side-stats">
                <div>Supply: <span class="text-blue">{stats['supply']:.2f} {stats['symbol']}</span></div>
                <div>Market Cap: <span class="text-steel">{stats['market_cap']:.2f} τ</span></div>
                <div>Emission: <span class="text-purple">{stats['emission']:.2f} {stats['symbol']}</span></div>
                <div>Stake: <span class="text-gold">{stats['stake']:.2f} {stats['symbol']}</span></div>
            </div>
        </div>
        <div id="chart-container"></div>
        <script>
            var figData = {fig_json}; 
            Plotly.newPlot('chart-container', figData.data, figData.layout);
        </script>
    </body>
    </html>
    """

    return html_content


def _generate_html_multi_subnet(subnet_data, block_numbers, interval_hours, log_scale):
    """
    Generate an HTML chart for multiple subnets.
    """
    # Pick top subnet by market cap
    top_subnet_netuid = max(
        subnet_data.keys(),
        key=lambda k: subnet_data[k]["stats"]["market_cap"],
    )
    top_subnet_stats = subnet_data[top_subnet_netuid]["stats"]

    fig = go.Figure()
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#000000",
        plot_bgcolor="#000000",
        font=dict(color="white"),
        showlegend=True,
        legend=dict(
            x=1.02,
            y=1.0,
            xanchor="left",
            yanchor="top",
            bgcolor="rgba(0,0,0,0)",
            bordercolor="rgba(255,255,255,0.2)",
            borderwidth=1,
        ),
        margin=dict(t=200, r=80, b=50, l=50),
        height=700,
    )

    price_title = "Price (τ)"
    if log_scale:
        price_title += " Log Scale"

    # Label axes
    fig.update_xaxes(
        title="Block",
        gridcolor="rgba(128,128,128,0.2)",
        zerolinecolor="rgba(128,128,128,0.2)",
        type="log" if log_scale else "linear",
    )
    fig.update_yaxes(
        title=price_title,
        gridcolor="rgba(128,128,128,0.2)",
        zerolinecolor="rgba(128,128,128,0.2)",
        type="log" if log_scale else "linear",
    )

    # Create annotation for top subnet
    sign_icon = "▲" if top_subnet_stats["change_pct"] > 0 else "▼"
    change_color = "#00FF00" if top_subnet_stats["change_pct"] > 0 else "#FF5555"

    left_text = (
        f"Top subnet: Subnet {top_subnet_netuid}"
        + (f" - {top_subnet_stats['name']}" if top_subnet_stats["name"] else "")
        + "<br><br>"
        + f"<span style='font-size: 24px'>{top_subnet_stats['current_price']:.6f} {top_subnet_stats['symbol']}"
        + f"<span style='color: {change_color}'> {sign_icon} {abs(top_subnet_stats['change_pct']):.2f}%</span></span><br><br>"
        + f"{interval_hours}h High: <span style='color: #00FF00'>{top_subnet_stats['high']:.6f}</span>, "
        + f"Low: <span style='color: #FF5555'>{top_subnet_stats['low']:.6f}</span>"
    )

    right_text = (
        f"Supply: <span style='color: #87CEEB'>{top_subnet_stats['supply']:.2f} {top_subnet_stats['symbol']}</span><br>"
        f"Market Cap: <span style='color: #4682B4'>{top_subnet_stats['market_cap']:.2f} τ</span><br>"
        f"Emission: <span style='color: #DDA0DD'>{top_subnet_stats['emission']:.2f} {top_subnet_stats['symbol']}</span><br>"
        f"Stake: <span style='color: #FFD700'>{top_subnet_stats['stake']:.2f} {top_subnet_stats['symbol']}</span>"
    )

    all_annotations = [
        dict(
            text=left_text,
            x=0.0,
            y=1.3,
            xref="paper",
            yref="paper",
            align="left",
            showarrow=False,
            font=dict(size=14),
            xanchor="left",
            yanchor="top",
        ),
        dict(
            text=right_text,
            x=1.02,
            y=1.3,
            xref="paper",
            yref="paper",
            align="left",
            showarrow=False,
            font=dict(size=14),
            xanchor="left",
            yanchor="top",
        ),
    ]

    fig.update_layout(annotations=all_annotations)

    # Generate colors for subnets
    def generate_color_palette(n):
        """Generate n distinct colors using a variation of HSV color space."""
        colors = []
        for i in range(n):
            hue = i * 0.618033988749895 % 1
            saturation = 0.6 + (i % 3) * 0.2
            value = 0.8 + (i % 2) * 0.2  # Brightness

            h = hue * 6
            c = value * saturation
            x = c * (1 - abs(h % 2 - 1))
            m = value - c

            if h < 1:
                r, g, b = c, x, 0
            elif h < 2:
                r, g, b = x, c, 0
            elif h < 3:
                r, g, b = 0, c, x
            elif h < 4:
                r, g, b = 0, x, c
            elif h < 5:
                r, g, b = x, 0, c
            else:
                r, g, b = c, 0, x

            rgb = (
                int((r + m) * 255),
                int((g + m) * 255),
                int((b + m) * 255),
            )
            colors.append(f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}")
        return colors

    base_colors = generate_color_palette(len(subnet_data) + 1)

    # Plot each subnet as a separate trace
    subnet_keys = list(subnet_data.keys())
    for i, netuid in enumerate(subnet_keys):
        d = subnet_data[netuid]
        fig.add_trace(
            go.Scatter(
                x=block_numbers,
                y=d["prices"],
                mode="lines",
                name=(
                    f"Subnet {netuid} - {d['stats']['name']}"
                    if d["stats"]["name"]
                    else f"Subnet {netuid}"
                ),
                line=dict(width=2, color=base_colors[i]),
                visible=True,
            )
        )

    # Annotations for each subnet
    def build_single_subnet_annotations(netuid):
        s = subnet_data[netuid]["stats"]
        name_line = f"Subnet {netuid}" + (f" - {s['name']}" if s["name"] else "")

        sign_icon = "▲" if s["change_pct"] > 0 else "▼"
        change_color = "#00FF00" if s["change_pct"] > 0 else "#FF5555"

        left_text = (
            f"{name_line}<br><br>"
            f"<span style='font-size: 24px'>{s['current_price']:.6f} {s['symbol']}"
            f"<span style='color: {change_color}'> {sign_icon} {abs(s['change_pct']):.2f}%</span></span><br><br>"
            f"{interval_hours}h High: <span style='color: #00FF00'>{s['high']:.6f}</span>, "
            f"Low: <span style='color: #FF5555'>{s['low']:.6f}</span>"
        )

        right_text = (
            f"Supply: <span style='color: #87CEEB'>{s['supply']:.2f} {s['symbol']}</span><br>"
            f"Market Cap: <span style='color: #4682B4'>{s['market_cap']:.2f} τ</span><br>"
            f"Emission: <span style='color: #DDA0DD'>{s['emission']:.2f} {s['symbol']}</span><br>"
            f"Stake: <span style='color: #FFD700'>{s['stake']:.2f} {s['symbol']}</span>"
        )

        left_annot = dict(
            text=left_text,
            x=0.0,
            y=1.3,
            xref="paper",
            yref="paper",
            align="left",
            showarrow=False,
            font=dict(size=14),
            xanchor="left",
            yanchor="top",
        )
        right_annot = dict(
            text=right_text,
            x=1.02,
            y=1.3,
            xref="paper",
            yref="paper",
            align="left",
            showarrow=False,
            font=dict(size=14),
            xanchor="left",
            yanchor="top",
        )
        return [left_annot, right_annot]

    # "All" visibility mask
    all_visibility = [True] * len(subnet_keys)

    # Build visibility masks for each subnet
    subnet_modes = {}
    for idx, netuid in enumerate(subnet_keys):
        single_vis = [False] * len(subnet_keys)
        single_vis[idx] = True
        single_annots = build_single_subnet_annotations(netuid)
        subnet_modes[netuid] = {
            "visible": single_vis,
            "annotations": single_annots,
        }

    fig_json = fig.to_json()
    all_visibility_json = json.dumps(all_visibility)
    all_annotations_json = json.dumps(all_annotations)

    subnet_modes_json = {}
    for netuid, mode_data in subnet_modes.items():
        subnet_modes_json[netuid] = {
            "visible": json.dumps(mode_data["visible"]),
            "annotations": json.dumps(mode_data["annotations"]),
        }

    # We sort netuids by market cap but for buttons, they are ordered by netuid
    sorted_subnet_keys = sorted(subnet_data.keys())
    all_button_html = (
        '<button class="subnet-button active" onclick="setAll()">All</button>'
    )
    subnet_buttons_html = ""
    for netuid in sorted_subnet_keys:
        subnet_buttons_html += f'<button class="subnet-button" onclick="setSubnet({netuid})">S{netuid}</button> '

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Multi-Subnet Price Chart</title>
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        <style>
            body {{
                background-color: #000;
                color: #fff;
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
            }}
            .container {{
                display: flex;
                flex-direction: column;
                gap: 60px;
            }}
            #multi-subnet-chart {{
                width: 90vw;
                height: 70vh;
                margin-bottom: 40px;
            }}
            .subnet-buttons {{
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(80px, 1fr));
                gap: 8px;
                max-height: 120px;
                overflow-y: auto;
                padding-right: 10px;
                margin-top: 50px;
                border-top: 1px solid rgba(255,255,255,0.1);
                padding-top: 50px;
                position: relative;
                bottom: 0;
            }}
            .subnet-buttons::-webkit-scrollbar {{
                width: 8px;
            }}
            .subnet-buttons::-webkit-scrollbar-track {{
                background: rgba(50,50,50,0.3);
                border-radius: 4px;
            }}
            .subnet-buttons::-webkit-scrollbar-thumb {{
                background: rgba(100,100,100,0.8);
                border-radius: 4px;
            }}
            .subnet-button {{
                background-color: rgba(50,50,50,0.8);
                border: 1px solid rgba(70,70,70,0.9);
                color: white;
                padding: 8px 16px;
                cursor: pointer;
                border-radius: 4px;
                font-size: 14px;
                transition: background-color 0.2s;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }}
            .subnet-button:hover {{
                background-color: rgba(70,70,70,0.9);
            }}
            .subnet-button.active {{
                background-color: rgba(100,100,100,0.9);
                border-color: rgba(120,120,120,1);
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div id="multi-subnet-chart"></div>
            <div class="subnet-buttons">
                {all_button_html}
                {subnet_buttons_html}
            </div>
        </div>
        <script>
            var figData = {fig_json};
            var allVisibility = {all_visibility_json};
            var allAnnotations = {all_annotations_json};

            var subnetModes = {json.dumps(subnet_modes_json)};
            // parse back to arrays/objects
            for (var netuid in subnetModes) {{
                subnetModes[netuid].visible = JSON.parse(subnetModes[netuid].visible);
                subnetModes[netuid].annotations = JSON.parse(subnetModes[netuid].annotations);
            }}

            Plotly.newPlot('multi-subnet-chart', figData.data, figData.layout);

            function clearActiveButtons() {{
                document.querySelectorAll('.subnet-button').forEach(btn => btn.classList.remove('active'));
            }}

            function setAll() {{
                clearActiveButtons();
                event.currentTarget.classList.add('active');
                Plotly.update('multi-subnet-chart',
                    {{visible: allVisibility}},
                    {{annotations: allAnnotations}}
                );
            }}

            function setSubnet(netuid) {{
                clearActiveButtons();
                event.currentTarget.classList.add('active');
                var mode = subnetModes[netuid];
                Plotly.update('multi-subnet-chart',
                    {{visible: mode.visible}},
                    {{annotations: mode.annotations}}
                );
            }}
        </script>
    </body>
    </html>
    """
    return html_content


async def _generate_html_output(
    subnet_data,
    block_numbers,
    interval_hours,
    log_scale: bool = False,
):
    """
    Start PyWry and display the price chart in a window.
    """
    try:
        subnet_keys = list(subnet_data.keys())

        # Single subnet
        if len(subnet_keys) == 1:
            netuid = subnet_keys[0]
            data = subnet_data[netuid]
            html_content = _generate_html_single_subnet(
                netuid, data, block_numbers, interval_hours, log_scale
            )
            title = f"Subnet {netuid} Price View"
        else:
            # Multi-subnet
            html_content = _generate_html_multi_subnet(
                subnet_data, block_numbers, interval_hours, log_scale
            )
            title = "Subnets Price Chart"
        console.print(
            "[dark_sea_green3]Opening price chart in a window. Press Ctrl+C to close.[/dark_sea_green3]"
        )
        handler = PyWry()
        handler.send_html(
            html=html_content,
            title=title,
            width=1200,
            height=800,
        )
        handler.start()
        await asyncio.sleep(5)

        # TODO: Improve this logic
        try:
            while True:
                if _has_exited(handler):
                    break
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            if not _has_exited(handler):
                try:
                    handler.close()
                except Exception:
                    pass
    except Exception as e:
        print_error(f"Error generating price chart: {e}")


def _generate_json_output(subnet_data):
    return {netuid: data for netuid, data in subnet_data.items()}


def _generate_cli_output(subnet_data, block_numbers, interval_hours, log_scale):
    """
    Render the price data in a textual CLI style with plotille ASCII charts.
    """
    for netuid, data in subnet_data.items():
        fig = plotille.Figure()
        fig.width = 60
        fig.height = 20
        fig.color_mode = "rgb"
        fig.background = None

        def color_label(text):
            return plotille.color(text, fg=(186, 233, 143), mode="rgb")

        fig.x_label = color_label("Block")
        y_label_text = f"Price ({data['stats']['symbol']})"
        fig.y_label = color_label(y_label_text)

        prices = data["prices"]
        if log_scale:
            prices = [math.log10(p) for p in prices]

        fig.set_x_limits(min_=min(block_numbers), max_=max(block_numbers))
        fig.set_y_limits(
            min_=data["stats"]["low"] * 0.99,
            max_=data["stats"]["high"] * 1.01,
        )

        fig.plot(
            block_numbers,
            prices,
            label=f"Subnet {netuid} Price",
            interp="linear",
            lc="bae98f",
        )

        stats = data["stats"]
        change_color = "dark_sea_green3" if stats["change_pct"] > 0 else "red"

        if netuid != 0:
            console.print(
                f"\n[{COLOR_PALETTE['GENERAL']['SYMBOL']}]Subnet {netuid} - {stats['symbol']} "
                f"[cyan]{stats['name']}[/cyan][/{COLOR_PALETTE['GENERAL']['SYMBOL']}]\n"
                f"Current: [blue]{stats['current_price']:.6f}{stats['symbol']}[/blue]\n"
                f"{interval_hours}h High: [dark_sea_green3]{stats['high']:.6f}{stats['symbol']}[/dark_sea_green3]\n"
                f"{interval_hours}h Low: [red]{stats['low']:.6f}{stats['symbol']}[/red]\n"
                f"{interval_hours}h Change: [{change_color}]{stats['change_pct']:.2f}%[/{change_color}]\n"
            )
        else:
            console.print(
                f"\n[{COLOR_PALETTE['GENERAL']['SYMBOL']}]Subnet {netuid} - {stats['symbol']} "
                f"[cyan]{stats['name']}[/cyan][/{COLOR_PALETTE['GENERAL']['SYMBOL']}]\n"
                f"Current: [blue]{stats['symbol']} {stats['current_price']:.6f}[/blue]\n"
                f"{interval_hours}h High: [dark_sea_green3]{stats['symbol']} {stats['high']:.6f}[/dark_sea_green3]\n"
                f"{interval_hours}h Low: [red]{stats['symbol']} {stats['low']:.6f}[/red]\n"
                f"{interval_hours}h Change: [{change_color}]{stats['change_pct']:.2f}%[/{change_color}]\n"
            )

        print(fig.show())

        if netuid != 0:
            stats_text = (
                "\nLatest stats:\n"
                f"Supply: [{COLOR_PALETTE['POOLS']['ALPHA_IN']}]"
                f"{stats['supply']:,.2f} {stats['symbol']}[/{COLOR_PALETTE['POOLS']['ALPHA_IN']}]\n"
                f"Market Cap: [steel_blue3]{stats['market_cap']:,.2f} {stats['symbol']} / 21M[/steel_blue3]\n"
                f"Emission: [{COLOR_PALETTE['POOLS']['EMISSION']}]"
                f"{stats['emission']:,.2f} {stats['symbol']}[/{COLOR_PALETTE['POOLS']['EMISSION']}]\n"
                f"Stake: [{COLOR_PALETTE['STAKE']['TAO']}]"
                f"{stats['stake']:,.2f} {stats['symbol']}[/{COLOR_PALETTE['STAKE']['TAO']}]"
            )
        else:
            stats_text = (
                "\nLatest stats:\n"
                f"Supply: [{COLOR_PALETTE['POOLS']['ALPHA_IN']}]"
                f"{stats['symbol']} {stats['supply']:,.2f}[/{COLOR_PALETTE['POOLS']['ALPHA_IN']}]\n"
                f"Market Cap: [steel_blue3]{stats['symbol']} {stats['market_cap']:,.2f} / 21M[/steel_blue3]\n"
                f"Emission: [{COLOR_PALETTE['POOLS']['EMISSION']}]"
                f"{stats['symbol']} {stats['emission']:,.2f}[/{COLOR_PALETTE['POOLS']['EMISSION']}]\n"
                f"Stake: [{COLOR_PALETTE['STAKE']['TAO']}]"
                f"{stats['symbol']} {stats['stake']:,.2f}[/{COLOR_PALETTE['STAKE']['TAO']}]"
            )

        console.print(stats_text)


def _has_exited(handler) -> bool:
    """Check if PyWry process has cleanly exited with returncode 0."""
    return (
        hasattr(handler, "runner")
        and handler.runner is not None
        and handler.runner.returncode == 0
    )
