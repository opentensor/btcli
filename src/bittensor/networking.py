import netaddr


def int_to_ip(int_val: int) -> str:
    """Maps an integer to a unique ip-string
    Args:
        int_val  (:type:`int128`, `required`): The integer representation of an ip. Must be in the range (0, 3.4028237e+38).

    Returns:
        str_val (:type:`str`, `required): The string representation of an ip. Of form *.*.*.* for ipv4 or *::*:*:*:* for ipv6

    Raises:
        netaddr.core.AddrFormatError (Exception): Raised when the passed int_vals is not a valid ip int value.
    """
    return str(netaddr.IPAddress(int_val))
