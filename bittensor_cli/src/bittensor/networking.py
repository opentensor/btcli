import netaddr

def int_to_ip(int_val: int) -> str:
    """Maps an integer to a unique IP string.
    
    :param int_val: The integer representation of an IP. 
        Must be in the range (0, 2^32-1) for IPv4 or (0, 2^128-1) for IPv6.

    :return: The string representation of an IP in the form *.*.*.* for IPv4 
             or *::*:*:*:* for IPv6.
    
    :raises: netaddr.core.AddrFormatError: Raised when the passed int_val is 
             not a valid IP integer value.
    """
    try:
        return str(netaddr.IPAddress(int_val))
    except netaddr.core.AddrFormatError as e:
        raise ValueError(f"Invalid IP integer value: {int_val}") from e
