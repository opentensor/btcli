from types import SimpleNamespace

import pytest

from bittensor_cli.src.commands.subnets.subnets import filter_sort_limit_subnets


def _subnet(
    *,
    netuid: int,
    name: str,
    alpha_in: float,
    alpha_out: float,
    price: float,
    emission: float = 0.0,
    tempo: int = 0,
):
    # Minimal shape required by `filter_sort_limit_subnets`.
    return SimpleNamespace(
        netuid=netuid,
        subnet_name=name,
        subnet_identity=None,
        alpha_in=SimpleNamespace(tao=alpha_in),
        alpha_out=SimpleNamespace(tao=alpha_out),
        price=SimpleNamespace(tao=price),
        tao_in_emission=SimpleNamespace(tao=emission),
        tempo=tempo,
    )


def test_filter_by_netuids_keeps_only_selected():
    subnets = [
        _subnet(netuid=0, name="root", alpha_in=0, alpha_out=0, price=1),
        _subnet(netuid=1, name="alpha", alpha_in=10, alpha_out=5, price=2),
        _subnet(netuid=2, name="beta", alpha_in=8, alpha_out=4, price=3),
    ]

    out = filter_sort_limit_subnets(
        subnets=subnets,
        mechanisms={0: 1, 1: 1, 2: 2},
        ema_tao_inflow={},
        netuids=[2],
    )

    assert [s.netuid for s in out] == [2]


def test_filter_by_name_contains_case_insensitive():
    subnets = [
        _subnet(netuid=0, name="root", alpha_in=0, alpha_out=0, price=1),
        _subnet(netuid=10, name="MySubnet", alpha_in=10, alpha_out=0, price=1),
        _subnet(netuid=11, name="Other", alpha_in=10, alpha_out=0, price=1),
    ]

    out = filter_sort_limit_subnets(
        subnets=subnets,
        mechanisms={},
        ema_tao_inflow={},
        name_contains="subnet",
    )

    assert [s.netuid for s in out] == [10]


def test_sort_by_price_desc_default_for_numeric():
    subnets = [
        _subnet(netuid=0, name="root", alpha_in=0, alpha_out=0, price=1),
        _subnet(netuid=1, name="a", alpha_in=1, alpha_out=1, price=2),
        _subnet(netuid=2, name="b", alpha_in=1, alpha_out=1, price=5),
    ]

    out = filter_sort_limit_subnets(
        subnets=subnets,
        mechanisms={},
        ema_tao_inflow={},
        sort_by="price",
    )

    # root always first; rest sorted desc
    assert [s.netuid for s in out] == [0, 2, 1]


def test_sort_by_netuid_asc_and_limit():
    subnets = [
        _subnet(netuid=0, name="root", alpha_in=0, alpha_out=0, price=1),
        _subnet(netuid=5, name="e", alpha_in=1, alpha_out=1, price=1),
        _subnet(netuid=3, name="c", alpha_in=1, alpha_out=1, price=1),
        _subnet(netuid=4, name="d", alpha_in=1, alpha_out=1, price=1),
    ]

    out = filter_sort_limit_subnets(
        subnets=subnets,
        mechanisms={},
        ema_tao_inflow={},
        sort_by="netuid",
        sort_order="asc",
        limit=3,
    )

    assert [s.netuid for s in out] == [0, 3, 4]
