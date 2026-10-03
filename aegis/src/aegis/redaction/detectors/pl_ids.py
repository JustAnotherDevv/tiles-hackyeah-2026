"""Polish identifiers: PESEL, NIP, REGON, ID card, passport (checksums + context words)."""

from ._base import CoreView

DETECTORS = [
    CoreView("pii.pesel", "PESEL", ("pl",)),
    CoreView("pii.nip", "NIP", ("pl",)),
    CoreView("pii.regon", "REGON", ("pl",)),
    CoreView("pii.pl_id_card", "PL_ID_CARD", ("pl",)),
    CoreView("pii.passport", "PASSPORT", ("pl",)),
]
