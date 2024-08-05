import netaddr


def int_to_ip(int_val: int) -> str:
    """Maps an integer to a unique ip-string
    :param int_val: The integer representation of an ip. Must be in the range (0, 3.4028237e+38).

    :return: The string representation of an ip. Of form *.*.*.* for ipv4 or *::*:*:*:* for ipv6

    :raises: netaddr.core.AddrFormatError (Exception): Raised when the passed int_vals is not a valid ip int value.
    """
    return str(netaddr.IPAddress(int_val))
