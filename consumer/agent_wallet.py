"""
Agent Wallet Management

Each trading agent gets its own wallet on Base mainnet. This module shows how to:
1. Generate new wallets for agents
2. Encrypt private keys at rest (Fernet AES-128)
3. Decrypt for payment operations

Reference implementation from Simmer (simmer.markets)
"""

import os
from typing import Tuple
from eth_account import Account
from cryptography.fernet import Fernet


def get_encryption_key() -> bytes:
    """Get the encryption key from environment."""
    key = os.environ.get("AGENT_KEY_ENCRYPTION_SECRET")
    if not key:
        raise ValueError(
            "AGENT_KEY_ENCRYPTION_SECRET not set. "
            "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return key.encode()


def generate_agent_wallet() -> Tuple[str, str, str]:
    """
    Generate a new wallet for an agent.

    Returns:
        Tuple of (address, encrypted_private_key, checksum)
        - address: Public wallet address (0x...)
        - encrypted_private_key: Fernet-encrypted private key (safe to store in DB)
        - checksum: First 8 chars of address for verification
    """
    # Generate random wallet
    account = Account.create()

    # Get private key as hex (without 0x prefix for consistency)
    private_key = account.key.hex()
    if private_key.startswith("0x"):
        private_key = private_key[2:]

    # Encrypt with Fernet (AES-128)
    fernet = Fernet(get_encryption_key())
    encrypted_key = fernet.encrypt(private_key.encode()).decode()

    return (
        account.address,
        encrypted_key,
        account.address[:10],  # Checksum for UI display
    )


def decrypt_wallet(encrypted_key: str) -> str:
    """
    Decrypt an agent's private key for use.

    Args:
        encrypted_key: Fernet-encrypted private key from database

    Returns:
        Hex-encoded private key (without 0x prefix)
    """
    fernet = Fernet(get_encryption_key())
    return fernet.decrypt(encrypted_key.encode()).decode()


def get_wallet_address(encrypted_key: str) -> str:
    """
    Get the public address from an encrypted private key.

    Useful for displaying wallet address without exposing the key.
    """
    private_key = decrypt_wallet(encrypted_key)
    # Add 0x prefix if not present
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    account = Account.from_key(private_key)
    return account.address


# ==========================================
# EXAMPLE USAGE
# ==========================================

def example_usage():
    """Example: Generate and use an agent wallet."""

    # First, set up encryption key (do this once, store securely)
    if not os.environ.get("AGENT_KEY_ENCRYPTION_SECRET"):
        # Generate a new key for demo
        key = Fernet.generate_key().decode()
        os.environ["AGENT_KEY_ENCRYPTION_SECRET"] = key
        print(f"Generated encryption key: {key}")
        print("Store this in your environment variables!\n")

    # Generate wallet for new agent
    address, encrypted_key, checksum = generate_agent_wallet()
    print(f"New agent wallet:")
    print(f"  Address: {address}")
    print(f"  Checksum: {checksum}")
    print(f"  Encrypted key (store in DB): {encrypted_key[:50]}...")

    # Later, decrypt for payments
    decrypted = decrypt_wallet(encrypted_key)
    print(f"\n  Decrypted key (use for x402): {decrypted[:10]}...")

    # Verify address matches
    recovered_address = get_wallet_address(encrypted_key)
    assert recovered_address == address, "Address mismatch!"
    print(f"  Verified address matches: {recovered_address}")


if __name__ == "__main__":
    example_usage()
