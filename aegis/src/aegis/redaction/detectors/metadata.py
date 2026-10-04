"""Metadata (INTERNAL, for DLP-03): OS user names inside /Users/<x>, /home/<x>, C:\\Users\\<x>."""

from ._base import CoreView

DETECTORS = [CoreView("meta.path_username", "USERNAME")]
