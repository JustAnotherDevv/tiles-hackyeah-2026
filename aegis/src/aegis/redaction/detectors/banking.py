"""Banking: IBAN (per-country length + mod-97), 26-digit Polish NRB -> IBAN."""

from ._base import CoreView

DETECTORS = [
    CoreView("pii.iban", "IBAN", detector_prefix="pii.iban"),
    CoreView("pii.nrb", "IBAN", ("pl",), detector_prefix="pii.nrb"),
]
