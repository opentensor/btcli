from bittensor_cli.src.bittensor.swap_math import price_to_tick

def test_price_to_tick():
    tick_spacing = 1.0001
    precision = 0.0000000001

    # 1.0 => tick 0
    assert price_to_tick(1.0) == 0
    assert price_to_tick(tick_spacing) == 1
    assert price_to_tick(tick_spacing ** 2 + precision) == 2
    assert price_to_tick(tick_spacing ** 5 + precision) == 5
    assert price_to_tick(tick_spacing ** 15 + precision) == 15
    assert price_to_tick(tick_spacing ** -15 - precision) == -15
