import pytest

from bittensor_cli.src.commands.subnets.subnets import filter_sort_limit_metagraph_rows


def _row(
    *,
    uid: int,
    global_stake: float = 0.0,
    local_stake: float = 0.0,
    stake_weight: float = 0.0,
    rank: float = 0.0,
    trust: float = 0.0,
    consensus: float = 0.0,
    incentive: float = 0.0,
    dividends: float = 0.0,
    emission: int = 0,
    vtrust: float = 0.0,
    val: str = "",
    updated: int = 0,
    active: int = 1,
    axon: str = "none",
    hotkey: str = "hk",
    coldkey: str = "ck",
):
    # Row schema matches `metagraph_cmd` table_data creation order.
    return [
        str(uid),
        f"{global_stake:.4f}",
        f"{local_stake:.4f}",
        f"{stake_weight:.4f}",
        f"{rank:.5f}",
        f"{trust:.5f}",
        f"{consensus:.5f}",
        f"{incentive:.5f}",
        f"{dividends:.5f}",
        str(int(emission)),
        f"{vtrust:.5f}",
        val,
        str(int(updated)),
        str(int(active)),
        axon,
        hotkey,
        coldkey,
    ]


def test_filter_by_uids_keeps_only_selected():
    rows = [
        _row(uid=0, global_stake=1.0, hotkey="a"),
        _row(uid=1, global_stake=2.0, hotkey="b"),
        _row(uid=2, global_stake=3.0, hotkey="c"),
    ]

    out = filter_sort_limit_metagraph_rows(rows=rows, uids=[2])

    assert [int(r[0]) for r in out] == [2]


def test_filter_by_hotkey_contains_case_insensitive():
    rows = [
        _row(uid=1, hotkey="MyHotKey"),
        _row(uid=2, hotkey="Other"),
    ]

    out = filter_sort_limit_metagraph_rows(rows=rows, hotkey_contains="hotkey")

    assert [int(r[0]) for r in out] == [1]


def test_sort_by_global_stake_desc_default():
    rows = [
        _row(uid=1, global_stake=10.0),
        _row(uid=2, global_stake=50.0),
        _row(uid=3, global_stake=20.0),
    ]

    out = filter_sort_limit_metagraph_rows(rows=rows, sort_by="global_stake")

    assert [int(r[0]) for r in out] == [2, 3, 1]


def test_sort_by_uid_asc_and_limit():
    rows = [
        _row(uid=5),
        _row(uid=2),
        _row(uid=4),
        _row(uid=1),
    ]

    out = filter_sort_limit_metagraph_rows(
        rows=rows,
        sort_by="uid",
        sort_order="asc",
        limit=3,
    )

    assert [int(r[0]) for r in out] == [1, 2, 4]
