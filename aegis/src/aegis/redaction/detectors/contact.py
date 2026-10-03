"""Contact data: e-mail (incl. reserved TLDs .example/.test), phone (libphonenumber / regex)."""

from ._base import CoreView

DETECTORS = [
    CoreView("pii.email", "EMAIL"),
    CoreView("pii.phone", "PHONE"),
]
