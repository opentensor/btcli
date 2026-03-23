"""
BTCLI Commander — Textual TUI Mockup
Mirrors the design in code.html (dark terminal aesthetic, neon-green accents).
Run with:  python commander/mockup.py
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import (
    DataTable,
    Label,
    RichLog,
    Static,
)
from textual.containers import Horizontal, VerticalScroll
from rich.text import Text


# ---------------------------------------------------------------------------
# Sample data (mirrors the HTML mock data)
# ---------------------------------------------------------------------------

WALLET_ROWS = [
    ("Alice", "1,240.50 TAO", "[SN1: 500.00]  [SN18: 1,200.00]", "1,700.00 TAO"),
    ("Bob", "  450.12 TAO", "[SN1: 200.12]  [SN11:   250.00]", "  450.12 TAO"),
    ("Charlie", "   89.00 TAO", "[SN3:  89.00]", "   89.00 TAO"),
]

LOG_LINES = [
    (
        "[dim][14:22:01][/dim] [green]INFO[/green]  Fetching metadata from chain...",
    ),
    (
        "[dim][14:22:03][/dim] [green]INFO[/green]  Alice account synchronized with chain state.",
    ),
    (
        "[dim][14:22:03][/dim] [green]INFO[/green]  Bob account synchronized with chain state.",
    ),
    (
        "[dim][14:22:03][/dim] [green]INFO[/green]  Charlie account synchronized with chain state.",
    ),
    (
        "[dim][14:22:08][/dim] [bright_green]READY[/bright_green] System idling. Waiting for command...",
    ),
]


# ---------------------------------------------------------------------------
# Custom widgets
# ---------------------------------------------------------------------------


class AppHeader(Static):
    """Top bar: title + connection info."""

    DEFAULT_CSS = """
    AppHeader {
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 1;
        dock: top;
    }
    """

    def render(self) -> Text:
        t = Text()
        t.append("BTCLI COMMANDER", style="bold bright_green")
        t.append("  │  ", style="dim green")
        t.append("wss://lite.sub.latent.to:443", style="dim")
        t.append("   " * 10)
        t.append("CHAIN: FINNEY-SUBTENSOR", style="dim")
        return t


class SectionHeader(Static):
    """Box-drawing section title bar."""

    DEFAULT_CSS = """
    SectionHeader {
        height: 1;
        color: #66FF00;
        padding: 0 0;
    }
    """

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title

    def render(self) -> Text:
        t = Text()
        t.append("┌── ", style="dim green")
        t.append(self._title, style="bold bright_green")
        t.append(" ", style="dim green")
        return t


class SystemLog(Static):
    """Pinned terminal / system log panel."""

    DEFAULT_CSS = """
    SystemLog {
        height: 8;
        border: solid #3c4b35;
        background: $surface;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    SystemLog RichLog {
        background: $surface;
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("[dim]btcli.log[/dim]", markup=True)
        log = RichLog(highlight=True, markup=True, id="syslog")
        yield log

    def on_mount(self) -> None:
        log = self.query_one("#syslog", RichLog)
        for (line,) in LOG_LINES:
            log.write(line)
        log.write("[bright_green]_[/bright_green]")


class WalletTable(Static):
    """Wallet Summary & Stake Allocation table."""

    DEFAULT_CSS = """
    WalletTable {
        height: auto;
    }
    WalletTable DataTable {
        height: auto;
        background: $surface;
    }
    """

    def compose(self) -> ComposeResult:
        yield SectionHeader("Wallet Summary")
        table: DataTable = DataTable(cursor_type="row", id="wallet_table")
        yield table
        yield Static(
            Text(
                "  [CREATE NEW WALLET]  ",
                style="bold black on #66FF00",
                justify="center",
            ),
            id="create_wallet_btn",
        )

    def on_mount(self) -> None:
        table = self.query_one("#wallet_table", DataTable)
        table.add_columns(
            "Wallet Name",
            "Free Balance",
            "Subnet Allocation",
            "Total Staked",
        )
        for name, free, subnets, total in WALLET_ROWS:
            table.add_row(
                Text(f"» {name}", style="white"),
                Text(free, style="bright_green", justify="right"),
                Text(subnets, style="bright_green"),
                Text(total, style="bold bright_green", justify="right"),
            )


# Nav entries: (label, key_label, active_by_default)
NAV_ENTRIES = [
    ("HOME", "F1"),
    ("WALLET", "F2"),
    ("STAKE", "F3"),
    ("SUDO", "F4"),
    ("SUBNETS", "F5"),
    ("PROXY", "F6"),
    ("CROWDLOAN", "F7"),
    ("BATCH", "F8"),
]


class NavKeys(Static):
    """Left portion of the footer: scrollable F-key buttons."""

    active: reactive[int] = reactive(0)

    DEFAULT_CSS = """
    NavKeys {
        width: 1fr;
        height: 1;
        overflow-x: hidden;
    }
    """

    def render(self) -> Text:
        t = Text(overflow="fold", no_wrap=True)
        for i, (name, key) in enumerate(NAV_ENTRIES):
            label = f"[{key}] {name}"
            if i == self.active:
                t.append(f" {label} ", style="bold black on #66FF00")
            else:
                t.append(f" {label} ", style="#c6c6c7")
        return t


class NavStatus(Static):
    """Right portion of the footer: connection status + version."""

    DEFAULT_CSS = """
    NavStatus {
        width: auto;
        height: 1;
        padding: 0 1;
    }
    """

    def render(self) -> Text:
        t = Text(no_wrap=True)
        t.append("● ", style="#00e639")
        t.append("ONLINE", style="#c6c6c7")
        t.append("   ")
        t.append("BTCLI v10.0.0", style="dim")
        return t


class AppFooter(Widget):
    """Bottom bar: F-key nav on the left, ONLINE + version on the right."""

    DEFAULT_CSS = """
    AppFooter {
        dock: bottom;
        height: 2;
        background: #131313;
        border-top: solid #3c4b35;
        layout: horizontal;
    }
    """

    def compose(self) -> ComposeResult:
        yield NavKeys(id="nav_keys")
        yield NavStatus()

    def set_active(self, index: int) -> None:
        self.query_one("#nav_keys", NavKeys).active = index


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------


class CommanderApp(App):
    """BTCLI Commander TUI mockup."""

    TITLE = "BTCLI COMMANDER"
    CSS = """
    Screen {
        background: #131313;
        color: #c6c6c7;
    }

    /* ── Main scroll area ───────────────────────────────────────── */
    #main_scroll {
        background: #131313;
        padding: 1 2;
    }

    /* ── DataTable ──────────────────────────────────────────────── */
    DataTable {
        border: solid #3c4b35;
        background: #1b1b1b;
    }
    DataTable > .datatable--header {
        background: #353535;
        color: #c6c6c7;
        text-style: none;
    }
    DataTable > .datatable--cursor {
        background: #2a2a2a;
        color: #66FF00;
    }
    DataTable > .datatable--hover {
        background: #2a2a2a;
    }

    /* ── Create wallet button ───────────────────────────────────── */
    #create_wallet_btn {
        margin: 1 0 0 0;
        text-align: center;
    }

    /* ── System log ─────────────────────────────────────────────── */
    SystemLog {
        margin-top: 1;
    }

    """

    BINDINGS = [
        Binding("f1", "nav_home", show=False),
        Binding("f2", "nav_wallet", show=False),
        Binding("f3", "nav_stake", show=False),
        Binding("f4", "nav_sudo", show=False),
        Binding("f5", "nav_subnets", show=False),
        Binding("f6", "nav_proxy", show=False),
        Binding("f7", "nav_crowdloan", show=False),
        Binding("f8", "nav_batch", show=False),
        Binding("q", "quit", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield AppHeader()
        with VerticalScroll(id="main_scroll"):
            yield WalletTable()
            yield SystemLog()
        yield AppFooter(id="app_footer")

    # ── Stub action handlers ─────────────────────────────────────────────

    def action_nav_home(self) -> None:
        self._nav(0, "HOME")

    def action_nav_wallet(self) -> None:
        self._nav(1, "WALLET")

    def action_nav_stake(self) -> None:
        self._nav(2, "STAKE")

    def action_nav_sudo(self) -> None:
        self._nav(3, "SUDO")

    def action_nav_subnets(self) -> None:
        self._nav(4, "SUBNETS")

    def action_nav_proxy(self) -> None:
        self._nav(5, "PROXY")

    def action_nav_crowdloan(self) -> None:
        self._nav(6, "CROWDLOAN")

    def action_nav_batch(self) -> None:
        self._nav(7, "BATCH")

    def _nav(self, index: int, screen: str) -> None:
        self.query_one("#app_footer", AppFooter).set_active(index)
        log = self.query_one("#syslog", RichLog)
        msg = Text()
        msg.append("[ NOW ]", style="dim")
        msg.append(" ")
        msg.append("NAV", style="bright_green")
        msg.append(f"   → {screen}")
        log.write(msg)


if __name__ == "__main__":
    CommanderApp().run()
