"""Personal data with context anchors: date of birth (EN/PL/DE triggers)."""

from ._base import CoreView

DETECTORS = [CoreView("pii.dob", "DOB", ("en", "pl", "de"))]
