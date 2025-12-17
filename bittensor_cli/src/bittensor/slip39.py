"""
SLIP39 (Shamir's Secret Sharing) utilities for Bittensor wallet management.

This module provides functionality to:
1. Generate SLIP39 mnemonic shares from a seed/entropy
2. Recover seed/entropy from SLIP39 mnemonic shares
3. Create coldkeys with SLIP39 share output (no plaintext mnemonic exposure)
4. Recover coldkeys from SLIP39 shares

SLIP39 allows splitting a secret into N shares where M shares are required
to reconstruct the original secret (M-of-N threshold scheme).

References:
- SLIP-0039: https://github.com/satoshilabs/slips/blob/master/slip-0039.md
- shamir-mnemonic: https://github.com/trezor/python-shamir-mnemonic
"""

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from bittensor_wallet import Keypair, Wallet
from shamir_mnemonic import generate_mnemonics, combine_mnemonics
from shamir_mnemonic.share import Share

from bittensor_cli.src.bittensor.utils import console


# Constants for entropy sizes (in bytes)
ENTROPY_128_BITS = 16  # 12-word BIP39 mnemonic equivalent
ENTROPY_256_BITS = 32  # 24-word BIP39 mnemonic equivalent


@dataclass
class SLIP39Config:
    """Configuration for SLIP39 share generation."""

    group_threshold: int = 1  # Number of groups required to recover
    groups: list[tuple[int, int]] = None  # List of (threshold, count) per group
    passphrase: str = ""  # Optional passphrase for additional security
    iteration_exponent: int = (
        1  # PBKDF2 iteration exponent (higher = slower but more secure)
    )

    def __post_init__(self):
        if self.groups is None:
            # Default: single group with 2-of-3 threshold
            self.groups = [(2, 3)]

    @property
    def total_shares(self) -> int:
        """Total number of shares across all groups."""
        return sum(count for _, count in self.groups)

    @property
    def threshold_description(self) -> str:
        """Human-readable description of the threshold scheme."""
        if len(self.groups) == 1:
            threshold, count = self.groups[0]
            return f"{threshold}-of-{count}"
        else:
            group_descs = [f"{t}-of-{c}" for t, c in self.groups]
            return (
                f"{self.group_threshold} groups required from: {', '.join(group_descs)}"
            )


@dataclass
class SLIP39ShareSet:
    """Container for generated SLIP39 shares."""

    shares: list[list[str]]  # Shares organized by group
    config: SLIP39Config
    identifier: int  # Share set identifier for matching shares

    def all_shares_flat(self) -> list[str]:
        """Return all shares as a flat list."""
        return [share for group in self.shares for share in group]

    def get_group(self, group_index: int) -> list[str]:
        """Get shares for a specific group."""
        if 0 <= group_index < len(self.shares):
            return self.shares[group_index]
        raise IndexError(f"Group index {group_index} out of range")


def generate_slip39_shares(
    master_secret: bytes,
    config: Optional[SLIP39Config] = None,
) -> SLIP39ShareSet:
    """
    Generate SLIP39 mnemonic shares from a master secret.

    Args:
        master_secret: The secret to split (16 or 32 bytes for 128/256-bit security)
        config: SLIP39 configuration (threshold, groups, passphrase)

    Returns:
        SLIP39ShareSet containing the generated mnemonic shares

    Raises:
        ValueError: If master_secret length is invalid
    """
    if len(master_secret) not in (ENTROPY_128_BITS, ENTROPY_256_BITS):
        raise ValueError(
            f"Master secret must be {ENTROPY_128_BITS} or {ENTROPY_256_BITS} bytes, "
            f"got {len(master_secret)}"
        )

    if config is None:
        config = SLIP39Config()

    # Generate SLIP39 mnemonics
    mnemonics = generate_mnemonics(
        group_threshold=config.group_threshold,
        groups=config.groups,
        master_secret=master_secret,
        passphrase=config.passphrase.encode() if config.passphrase else b"",
        iteration_exponent=config.iteration_exponent,
    )

    # Extract identifier from first share for reference
    first_share = Share.from_mnemonic(mnemonics[0][0])
    identifier = first_share.identifier

    return SLIP39ShareSet(
        shares=mnemonics,
        config=config,
        identifier=identifier,
    )


def recover_secret_from_shares(
    shares: list[str],
    passphrase: str = "",
) -> bytes:
    """
    Recover the master secret from SLIP39 mnemonic shares.

    Args:
        shares: List of SLIP39 mnemonic strings (must meet threshold requirements)
        passphrase: Optional passphrase used during share generation

    Returns:
        The recovered master secret as bytes

    Raises:
        ValueError: If shares are invalid or insufficient
        MnemonicError: If shares cannot be combined
    """
    if not shares:
        raise ValueError("No shares provided")

    return combine_mnemonics(
        shares,
        passphrase=passphrase.encode() if passphrase else b"",
    )


def generate_secure_entropy(n_bytes: int = ENTROPY_256_BITS) -> bytes:
    """
    Generate cryptographically secure random entropy.

    Args:
        n_bytes: Number of bytes to generate (16 or 32)

    Returns:
        Random bytes suitable for use as a master secret
    """
    if n_bytes not in (ENTROPY_128_BITS, ENTROPY_256_BITS):
        raise ValueError(f"n_bytes must be {ENTROPY_128_BITS} or {ENTROPY_256_BITS}")
    return secrets.token_bytes(n_bytes)


def entropy_to_keypair(entropy: bytes) -> Keypair:
    """
    Create a Keypair from entropy bytes.

    This uses the entropy as a mini-secret to derive a keypair,
    compatible with how BIP39 mnemonics work in substrate.

    Args:
        entropy: 16 or 32 bytes of entropy

    Returns:
        A Keypair derived from the entropy
    """
    # Use the entropy as a seed to create a keypair
    # We pad to 32 bytes if needed (for 128-bit entropy)
    if len(entropy) == ENTROPY_128_BITS:
        # Pad with zeros to make 32 bytes for sr25519
        seed = entropy + bytes(16)
    else:
        seed = entropy

    return Keypair.create_from_seed(seed.hex())


def create_coldkey_with_slip39(
    wallet: Wallet,
    config: Optional[SLIP39Config] = None,
    use_password: bool = True,
    overwrite: bool = False,
    entropy_bits: int = 256,
) -> tuple[SLIP39ShareSet, Keypair]:
    """
    Create a new coldkey and generate SLIP39 shares for backup.

    The coldkey is created from secure random entropy, and SLIP39 shares
    are generated for that entropy. The plaintext mnemonic is never exposed.

    Args:
        wallet: The wallet to create the coldkey for
        config: SLIP39 configuration
        use_password: Whether to encrypt the keyfile with a password
        overwrite: Whether to overwrite existing coldkey
        entropy_bits: Entropy size (128 or 256 bits)

    Returns:
        Tuple of (SLIP39ShareSet, Keypair) - the shares and the created keypair

    Raises:
        ValueError: If entropy_bits is invalid
    """
    if entropy_bits not in (128, 256):
        raise ValueError("entropy_bits must be 128 or 256")

    n_bytes = ENTROPY_128_BITS if entropy_bits == 128 else ENTROPY_256_BITS

    # Generate secure entropy
    entropy = generate_secure_entropy(n_bytes)

    # Generate SLIP39 shares from entropy
    share_set = generate_slip39_shares(entropy, config)

    # Create keypair from entropy
    keypair = entropy_to_keypair(entropy)

    # Set the coldkey on the wallet
    wallet.set_coldkey(keypair=keypair, encrypt=use_password, overwrite=overwrite)
    wallet.set_coldkeypub(keypair=keypair, overwrite=overwrite)

    # Clear entropy from memory (best effort)
    entropy = b"\x00" * len(entropy)

    return share_set, keypair


def recover_coldkey_from_slip39(
    wallet: Wallet,
    shares: list[str],
    passphrase: str = "",
    use_password: bool = True,
    overwrite: bool = False,
) -> Keypair:
    """
    Recover a coldkey from SLIP39 mnemonic shares.

    Args:
        wallet: The wallet to recover the coldkey to
        shares: List of SLIP39 mnemonic strings
        passphrase: Optional passphrase used during share generation
        use_password: Whether to encrypt the keyfile with a password
        overwrite: Whether to overwrite existing coldkey

    Returns:
        The recovered Keypair

    Raises:
        ValueError: If shares are invalid
        MnemonicError: If shares cannot be combined
    """
    # Recover entropy from shares
    entropy = recover_secret_from_shares(shares, passphrase)

    # Create keypair from recovered entropy
    keypair = entropy_to_keypair(entropy)

    # Set the coldkey on the wallet
    wallet.set_coldkey(keypair=keypair, encrypt=use_password, overwrite=overwrite)
    wallet.set_coldkeypub(keypair=keypair, overwrite=overwrite)

    # Clear entropy from memory (best effort)
    entropy = b"\x00" * len(entropy)

    return keypair


def save_shares_to_files(
    share_set: SLIP39ShareSet,
    output_dir: Union[str, Path],
    prefix: str = "share",
) -> list[Path]:
    """
    Save SLIP39 shares to individual files.

    Each share is saved to a separate file for distribution to different
    custodians or storage locations.

    Args:
        share_set: The SLIP39ShareSet to save
        output_dir: Directory to save share files
        prefix: Filename prefix for share files

    Returns:
        List of paths to created share files
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    created_files = []
    share_num = 1

    for group_idx, group in enumerate(share_set.shares):
        for share_idx, share in enumerate(group):
            filename = f"{prefix}_g{group_idx + 1}_s{share_idx + 1}_{share_num}.slip39"
            filepath = output_dir / filename

            with open(filepath, "w") as f:
                f.write(f"# SLIP39 Share {share_num}\n")
                f.write(f"# Group {group_idx + 1}, Share {share_idx + 1}\n")
                f.write(f"# Identifier: {share_set.identifier}\n")
                f.write(f"# Threshold: {share_set.config.threshold_description}\n")
                f.write("#\n")
                f.write("# KEEP THIS FILE SECURE!\n")
                f.write("# This share is required to recover your wallet.\n")
                f.write("#\n")
                f.write(share)
                f.write("\n")

            # Set restrictive permissions
            os.chmod(filepath, 0o600)

            created_files.append(filepath)
            share_num += 1

    return created_files


def load_shares_from_files(file_paths: list[Union[str, Path]]) -> list[str]:
    """
    Load SLIP39 shares from files.

    Args:
        file_paths: List of paths to share files

    Returns:
        List of SLIP39 mnemonic strings
    """
    shares = []

    for path in file_paths:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Share file not found: {path}")

        with open(path, "r") as f:
            lines = f.readlines()

        # Filter out comments and empty lines
        share_lines = [
            line.strip() for line in lines if line.strip() and not line.startswith("#")
        ]

        if share_lines:
            shares.append(share_lines[0])

    return shares


def validate_shares(shares: list[str]) -> dict:
    """
    Validate SLIP39 shares and return information about them.

    Args:
        shares: List of SLIP39 mnemonic strings to validate

    Returns:
        Dictionary with validation results and share information
    """
    if not shares:
        return {"valid": False, "error": "No shares provided"}

    try:
        parsed_shares = [Share.from_mnemonic(s) for s in shares]

        # Check all shares have same identifier
        identifiers = set(s.identifier for s in parsed_shares)
        if len(identifiers) > 1:
            return {
                "valid": False,
                "error": "Shares have different identifiers - they belong to different share sets",
            }

        # Get share information
        first_share = parsed_shares[0]
        group_indices = set(s.group_index for s in parsed_shares)

        return {
            "valid": True,
            "identifier": first_share.identifier,
            "share_count": len(shares),
            "groups_represented": len(group_indices),
            "group_threshold": first_share.group_threshold,
            "iteration_exponent": first_share.iteration_exponent,
        }

    except Exception as e:
        return {"valid": False, "error": str(e)}


def print_shares_securely(
    share_set: SLIP39ShareSet,
    show_shares: bool = False,
) -> None:
    """
    Print SLIP39 share information to console.

    Args:
        share_set: The SLIP39ShareSet to display
        show_shares: If True, display the actual mnemonic shares (use with caution!)
    """
    console.print("\n[bold cyan]═══ SLIP39 Share Information ═══[/bold cyan]\n")
    console.print(f"[bold]Identifier:[/bold] {share_set.identifier}")
    console.print(f"[bold]Threshold:[/bold] {share_set.config.threshold_description}")
    console.print(f"[bold]Total Shares:[/bold] {share_set.config.total_shares}")

    if share_set.config.passphrase:
        console.print("[bold yellow]⚠ Passphrase protection enabled[/bold yellow]")

    console.print()

    for group_idx, group in enumerate(share_set.shares):
        console.print(f"[bold green]Group {group_idx + 1}:[/bold green]")
        threshold, count = share_set.config.groups[group_idx]
        console.print(f"  Threshold: {threshold} of {count} shares required")

        for share_idx, share in enumerate(group):
            if show_shares:
                console.print(f"  [dim]Share {share_idx + 1}:[/dim]")
                console.print(f"    [yellow]{share}[/yellow]")
            else:
                # Show only first few words as identifier
                words = share.split()[:3]
                console.print(
                    f"  [dim]Share {share_idx + 1}:[/dim] {' '.join(words)}... "
                    f"[dim]({len(share.split())} words)[/dim]"
                )

    console.print()
    console.print(
        "[bold red]⚠ IMPORTANT:[/bold red] Store these shares securely in separate locations!"
    )
    console.print(
        "  Each share should be given to a different custodian or stored separately."
    )
    console.print("  Never store all shares together or in digital form on one device.")
    console.print()
