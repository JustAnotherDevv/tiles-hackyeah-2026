"""Crypto wallets: BTC base58check / bech32(m), ETH EIP-55 (gap entity CRYPTO_ADDRESS)."""

from ._base import CoreView

DETECTORS = [
    CoreView("pii.crypto.btc", "CRYPTO_ADDRESS", detector_prefix="pii.crypto.btc"),
    CoreView("pii.crypto.eth", "CRYPTO_ADDRESS", detector_prefix="pii.crypto.eth"),
]
