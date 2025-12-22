"""
Standardized JSON output utilities for btcli.

This module provides consistent JSON response formatting across all btcli commands.
All JSON outputs should use these utilities to ensure schema compliance.

Standard Response Format:
{
    "success": bool,       # Required: Whether the operation succeeded
    "data": {...},         # Optional: Command-specific response data
    "error": str           # Optional: Error message if success=False
}

For transaction responses, data should include:
{
    "extrinsic_hash": str,  # The transaction hash
    "block_hash": str       # The block containing the transaction
}
"""

import json
from typing import Any, Optional, Union
from rich.console import Console

# JSON console for outputting JSON responses
json_console = Console()


def json_response(
    success: bool,
    data: Optional[Any] = None,
    error: Optional[str] = None,
) -> str:
    """
    Create a standardized JSON response string.

    Args:
        success: Whether the operation succeeded
        data: Optional response data (dict, list, or primitive)
        error: Optional error message (typically used when success=False)

    Returns:
        JSON string with standardized format

    Examples:
        >>> json_response(True, {"balance": 100.5})
        '{"success": true, "data": {"balance": 100.5}}'

        >>> json_response(False, error="Wallet not found")
        '{"success": false, "error": "Wallet not found"}'
    """
    response: dict[str, Any] = {"success": success}

    if data is not None:
        response["data"] = data

    if error is not None:
        response["error"] = error

    return json.dumps(response)


def json_success(data: Any) -> str:
    """
    Create a successful JSON response.

    Args:
        data: Response data to include

    Returns:
        JSON string with success=True and the provided data
    """
    return json_response(success=True, data=data)


def json_error(error: str, data: Optional[Any] = None) -> str:
    """
    Create an error JSON response.

    Args:
        error: Error message describing what went wrong
        data: Optional additional context data

    Returns:
        JSON string with success=False and error message
    """
    return json_response(success=False, data=data, error=error)


def json_transaction(
    success: bool,
    extrinsic_hash: Optional[str] = None,
    block_hash: Optional[str] = None,
    error: Optional[str] = None,
    **extra_data: Any,
) -> str:
    """
    Create a standardized transaction response.

    Args:
        success: Whether the transaction succeeded
        extrinsic_hash: The transaction/extrinsic hash
        block_hash: The block hash containing the transaction
        error: Error message if transaction failed
        **extra_data: Additional transaction-specific data

    Returns:
        JSON string with transaction details
    """
    data: dict[str, Any] = {}

    if extrinsic_hash is not None:
        data["extrinsic_hash"] = extrinsic_hash

    if block_hash is not None:
        data["block_hash"] = block_hash

    # Add any extra data
    data.update(extra_data)

    return json_response(success=success, data=data if data else None, error=error)


def print_json(response: str) -> None:
    """
    Print a JSON response to the console.

    Args:
        response: JSON string to print
    """
    json_console.print(response)


def print_json_success(data: Any) -> None:
    """
    Print a successful JSON response.

    Args:
        data: Response data to include
    """
    print_json(json_success(data))


def print_json_error(error: str, data: Optional[Any] = None) -> None:
    """
    Print an error JSON response.

    Args:
        error: Error message
        data: Optional additional context
    """
    print_json(json_error(error, data))


def serialize_balance(balance: Any) -> dict[str, Union[int, float]]:
    """
    Serialize a Balance object to a consistent dictionary format.

    Args:
        balance: A Balance object or numeric value

    Returns:
        Dictionary with 'rao' (int) and 'tao' (float) keys
    """
    if hasattr(balance, "rao") and hasattr(balance, "tao"):
        return {"rao": int(balance.rao), "tao": float(balance.tao)}
    elif isinstance(balance, (int, float)):
        # Assume it's already in tao if float, rao if int
        if isinstance(balance, float):
            return {"rao": int(balance * 1e9), "tao": balance}
        else:
            return {"rao": balance, "tao": balance / 1e9}
    else:
        return {"rao": 0, "tao": 0.0}
