"""Network identifiers (INTERNAL, acted on by DLP-03): IP (public / private), MAC address."""

from ._base import CoreView

DETECTORS = [
    CoreView("pii.ip.public", "IP_ADDRESS", detector_prefix="pii.ip.public"),
    CoreView("pii.ip.private", "IP_ADDRESS", detector_prefix="pii.ip.private"),
    CoreView("meta.mac_address", "MAC_ADDRESS"),
]
