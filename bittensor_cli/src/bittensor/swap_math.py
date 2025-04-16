import math

def price_to_tick(price: float) -> int:
    """
    Convert a float price to the nearest Uniswap V3 tick index.
    """

    if price <= 0:
        raise ValueError("Price must be positive")

    # Binary search over tick range
    min_tick = -887272
    max_tick =  887272

    tick = int(math.log(price) / math.log(1.0001))

    if not (min_tick <= tick <= max_tick):
        raise ValueError("Price is out of allowed range")

    return tick

