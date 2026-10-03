"""Payment card industry: PAN (Luhn + IIN), CARD_EXPIRY, CVV, TRACK_DATA (SAD: always dropped)."""

from ._base import CoreView

DETECTORS = [
    CoreView("pci.pan", "PAN"),
    CoreView("pci.card_expiry", "CARD_EXPIRY", ("en", "pl")),
    CoreView("pci.cvv", "CVV", ("en", "pl")),
    CoreView("pci.track_data", "TRACK_DATA"),
]
