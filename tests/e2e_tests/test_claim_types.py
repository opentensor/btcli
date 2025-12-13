"""
Verify commands:

* btcli stake set-claim swap
* btcli stake set-claim keep
* btcli stake set-claim keep --netuids 2-4
* btcli stake set-claim delegated
* btcli stake set-validator-claims --swap 2-4
* btcli stake set-validator-claims --keep 1-3
"""


def test_claim_type_flows(local_chain, wallet_setup):
    """
    Cover root claim type transitions (Swap, Keep, KeepSubnets, Delegated)
    and validator claim type settings using the CLI.
    """

    # Wallet setup
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        "//Alice"
    )

    # Create multiple subnets
    for netuid in [2, 3, 4]:
        result = exec_command_alice(
            command="subnets",
            sub_command="create",
            extra_args=[
                "--wallet-path",
                wallet_path_alice,
                "--chain",
                "ws://127.0.0.1:9945",
                "--wallet-name",
                wallet_alice.name,
                "--wallet-hotkey",
                wallet_alice.hotkey_str,
                "--subnet-name",
                "Test Subnet",
                "--repo",
                "https://github.com/username/repo",
                "--contact",
                "test@opentensor.dev",
                "--url",
                "https://testsubnet.com",
                "--discord",
                "test#1234",
                "--description",
                "A test subnet for e2e testing",
                "--logo-url",
                "https://testsubnet.com/logo.png",
                "--additional-info",
                "Test subnet",
                "--no-prompt",
                "--no-mev-protection",
            ],
        )
        assert f"✅ Registered subnetwork with netuid: {netuid}" in result.stdout

    # 1) Set to Swap (as a holder)
    swap_result = exec_command_alice(
        command="stake",
        sub_command="set-claim",
        extra_args=[
            "swap",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-path",
            wallet_path_alice,
            "--network",
            "ws://127.0.0.1:9945",
            "--no-prompt",
        ],
    )
    assert "✅ Successfully changed claim type" in swap_result.stdout

    # 2) Set to Keep (as a holder)
    keep_result = exec_command_alice(
        command="stake",
        sub_command="set-claim",
        extra_args=[
            "keep",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-path",
            wallet_path_alice,
            "--network",
            "ws://127.0.0.1:9945",
            "--no-prompt",
        ],
    )
    assert "✅ Successfully changed claim type" in keep_result.stdout

    # 3) Set to KeepSubnets (as a holder)
    keep_subnets_result = exec_command_alice(
        command="stake",
        sub_command="set-claim",
        extra_args=[
            "keep",
            "--netuids",
            "1-3",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-path",
            wallet_path_alice,
            "--network",
            "ws://127.0.0.1:9945",
            "--no-prompt",
        ],
    )
    assert "✅ Successfully changed claim type" in keep_subnets_result.stdout

    # 4) Set to Delegated (as a holder)
    delegated_result = exec_command_alice(
        command="stake",
        sub_command="set-claim",
        extra_args=[
            "delegated",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-path",
            wallet_path_alice,
            "--network",
            "ws://127.0.0.1:9945",
            "--no-prompt",
        ],
    )
    assert "✅ Successfully changed claim type" in delegated_result.stdout

    # 5) Validator claim (as a validator)
    validator_claim_swap_result = exec_command_alice(
        command="stake",
        sub_command="set-validator-claims",
        extra_args=[
            "--swap",
            "1-3",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-path",
            wallet_path_alice,
            "--network",
            "ws://127.0.0.1:9945",
            "--no-prompt",
        ],
    )
    assert (
        "✅ Successfully updated validator claim types"
        in validator_claim_swap_result.stdout
    )

    # 6) Validator claim (as a validator)
    validator_claim_keep_result = exec_command_alice(
        command="stake",
        sub_command="set-validator-claims",
        extra_args=[
            "--keep",
            "1-3",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-path",
            wallet_path_alice,
            "--network",
            "ws://127.0.0.1:9945",
            "--no-prompt",
        ],
    )
    assert (
        "✅ Successfully updated validator claim types"
        in validator_claim_keep_result.stdout
    )
