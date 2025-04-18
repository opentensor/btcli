import math

min_tick = -887272
max_tick =  887272
price_step = 1.0001

def price_to_tick(price: float) -> int:
    """
    Convert a float price to the nearest Uniswap V3 tick index.
    """

    if price <= 0:
        raise ValueError("Price must be positive")

    tick = int(math.log(price) / math.log(price_step))

    if not (min_tick <= tick <= max_tick):
        raise ValueError("Price is out of allowed range")

    return tick

def tick_to_price(tick: int) -> float:
    """
    Convert an integer Uniswap V3 tick index to float price.
    """

    if not (min_tick <= tick <= max_tick):
        raise ValueError("Tick is out of allowed range")

    return price_step ** tick
