import json
import pytest


"""
Verify commands:

* btcli stake child get
* btcli stake child set
* btcli stake child revoke
"""

NETWORK = "ws://127.0.0.1:9945"
NETUID = 2


def _setup_subnet_and_stake(wallet_setup):
    """Create Alice wallet, subnet, start emissions, add stake. Returns helpers."""
    kp_alice, w_alice, wp_alice, exec_alice = wallet_setup("//Alice")

    # Create subnet
    result = exec_alice(
        command="subnets",
        sub_command="create",
        extra_args=[
            "--wallet-path",
            wp_alice,
            "--network",
            NETWORK,
            "--wallet-name",
            w_alice.name,
            "--wallet-hotkey",
            w_alice.hotkey_str,
            "--subnet-name",
            "Test Subnet",
            "--repo",
            "https://github.com/username/repo",
            "--contact",
            "alice@opentensor.dev",
            "--url",
            "https://testsubnet.com",
            "--discord",
            "alice#1234",
            "--description",
            "A test subnet for e2e testing",
            "--additional-info",
            "Created by Alice",
            "--logo-url",
            "https://testsubnet.com/logo.png",
            "--no-prompt",
            "--json-output",
            "--no-mev-protection",
        ],
    )
    assert json.loads(result.stdout)["success"] is True

    # Start emissions
    exec_alice(
        command="subnets",
        sub_command="start",
        extra_args=[
            "--netuid",
            NETUID,
            "--wallet-path",
            wp_alice,
            "--wallet-name",
            w_alice.name,
            "--hotkey",
            w_alice.hotkey_str,
            "--network",
            NETWORK,
            "--no-prompt",
        ],
    )

    # Add stake
    result = exec_alice(
        command="stake",
        sub_command="add",
        extra_args=[
            "--netuid",
            NETUID,
            "--wallet-path",
            wp_alice,
            "--wallet-name",
            w_alice.name,
            "--hotkey",
            w_alice.hotkey_str,
            "--network",
            NETWORK,
            "--amount",
            "1",
            "--unsafe",
            "--no-prompt",
            "--era",
            "144",
            "--no-mev-protection",
        ],
    )
    assert "✅ Finalized" in result.stdout

    return w_alice, wp_alice, exec_alice


def _register_on_subnet(wallet, wallet_path, exec_cmd):
    result = exec_cmd(
        command="subnets",
        sub_command="register",
        extra_args=[
            "--wallet-path",
            wallet_path,
            "--wallet-name",
            wallet.name,
            "--hotkey",
            wallet.hotkey_str,
            "--netuid",
            NETUID,
            "--network",
            NETWORK,
            "--no-prompt",
        ],
    )
    assert "✅ Registered" in result.stdout or "✅ Already Registered" in result.stdout


def _set_children(exec_alice, w_alice, wp_alice, child_addresses, proportions):
    """Set children and return parsed JSON output."""
    args = ["set"]
    for addr in child_addresses:
        args += ["--children", addr]
    for prop in proportions:
        args += ["--proportions", str(prop)]
    args += [
        "--netuid",
        NETUID,
        "--wallet-path",
        wp_alice,
        "--wallet-name",
        w_alice.name,
        "--hotkey",
        w_alice.hotkey_str,
        "--network",
        NETWORK,
        "--no-prompt",
        "--json-output",
    ]
    result = exec_alice(command="stake", sub_command="child", extra_args=args)
    assert result.stdout.strip(), f"Empty stdout. stderr: {result.stderr}"
    output = json.loads(result.stdout)
    assert output[str(NETUID)]["success"] is True
    return output


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("local_chain", [False], indirect=True)
def test_set_children_single_child(local_chain, wallet_setup):
    """Set a single child hotkey with 50% proportion."""
    w_alice, wp_alice, exec_alice = _setup_subnet_and_stake(wallet_setup)
    _, w_bob, wp_bob, exec_bob = wallet_setup("//Bob")
    _register_on_subnet(w_bob, wp_bob, exec_bob)

    output = _set_children(
        exec_alice,
        w_alice,
        wp_alice,
        [w_bob.hotkey.ss58_address],
        ["0.5"],
    )
    assert output[str(NETUID)]["completion_block"] is not None
    assert output[str(NETUID)]["set_block"] is not None
    assert isinstance(output[str(NETUID)]["extrinsic_identifier"], str)


@pytest.mark.parametrize("local_chain", [False], indirect=True)
def test_set_children_multiple_proportions(local_chain, wallet_setup):
    """Set multiple children (Bob 25%, Charlie 35%, Dave 20%)."""
    w_alice, wp_alice, exec_alice = _setup_subnet_and_stake(wallet_setup)

    children = []
    for uri in ["//Bob", "//Charlie", "//Dave"]:
        _, w, wp, exc = wallet_setup(uri)
        _register_on_subnet(w, wp, exc)
        children.append(w.hotkey.ss58_address)

    output = _set_children(
        exec_alice,
        w_alice,
        wp_alice,
        children,
        ["0.25", "0.35", "0.20"],
    )
    assert output[str(NETUID)]["completion_block"] is not None


@pytest.mark.parametrize("local_chain", [False], indirect=True)
def test_get_children_json_output(local_chain, wallet_setup):
    """Set children then get with --json-output."""
    w_alice, wp_alice, exec_alice = _setup_subnet_and_stake(wallet_setup)
    _, w_bob, wp_bob, exec_bob = wallet_setup("//Bob")
    _register_on_subnet(w_bob, wp_bob, exec_bob)
    _set_children(exec_alice, w_alice, wp_alice, [w_bob.hotkey.ss58_address], ["0.5"])

    result = exec_alice(
        command="stake",
        sub_command="child",
        extra_args=[
            "get",
            "--netuid",
            NETUID,
            "--wallet-path",
            wp_alice,
            "--wallet-name",
            w_alice.name,
            "--hotkey",
            w_alice.hotkey_str,
            "--network",
            NETWORK,
            "--json-output",
        ],
    )
    output = json.loads(result.stdout)
    assert isinstance(output, list)


@pytest.mark.parametrize("local_chain", [False], indirect=True)
def test_get_children_table_output(local_chain, wallet_setup):
    """Get children without JSON — verify table output is non-empty."""
    w_alice, wp_alice, exec_alice = _setup_subnet_and_stake(wallet_setup)
    _, w_bob, wp_bob, exec_bob = wallet_setup("//Bob")
    _register_on_subnet(w_bob, wp_bob, exec_bob)
    _set_children(exec_alice, w_alice, wp_alice, [w_bob.hotkey.ss58_address], ["0.5"])

    result = exec_alice(
        command="stake",
        sub_command="child",
        extra_args=[
            "get",
            "--netuid",
            NETUID,
            "--wallet-path",
            wp_alice,
            "--wallet-name",
            w_alice.name,
            "--hotkey",
            w_alice.hotkey_str,
            "--network",
            NETWORK,
        ],
    )
    assert len(result.stdout) > 0


@pytest.mark.parametrize("local_chain", [False], indirect=True)
def test_revoke_children(local_chain, wallet_setup):
    """Set children then revoke and verify success."""
    w_alice, wp_alice, exec_alice = _setup_subnet_and_stake(wallet_setup)
    _, w_bob, wp_bob, exec_bob = wallet_setup("//Bob")
    _register_on_subnet(w_bob, wp_bob, exec_bob)
    _set_children(exec_alice, w_alice, wp_alice, [w_bob.hotkey.ss58_address], ["0.5"])

    result = exec_alice(
        command="stake",
        sub_command="child",
        extra_args=[
            "revoke",
            "--netuid",
            NETUID,
            "--wallet-path",
            wp_alice,
            "--wallet-name",
            w_alice.name,
            "--hotkey",
            w_alice.hotkey_str,
            "--network",
            NETWORK,
            "--no-prompt",
            "--json-output",
        ],
    )
    output = json.loads(result.stdout)
    assert output[str(NETUID)]["success"] is True
    assert output[str(NETUID)]["completion_block"] is not None
