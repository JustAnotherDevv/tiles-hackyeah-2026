"""CoreView: a thin ``Detector`` view over the shared Tier-D core scan (skipped by discovery).

Each family module (pci, pl_ids, banking, ...) exposes ``DETECTORS`` made of CoreViews. Used
standalone (``Detector.detect(text)``) a view runs the module-level default scanner and keeps
only its entity; inside the engine, ``core = True`` tells ``rt.redactor`` that the view is
already covered by the one shared (cached, policy-configured) scan per text.
"""

from __future__ import annotations

from aegis.core.types import Span

from .. import entities as E


class CoreView:
    core = True

    def __init__(
        self,
        detector_id: str,
        entity: str,
        languages: tuple[str, ...] = (),
        *,
        detector_prefix: str | None = None,
    ) -> None:
        self.id = detector_id
        self.entity = entity
        info = E.info(entity)
        self.data_class = info.data_class
        self.category = info.category
        self.languages = languages
        # match on the hit's detector id prefix (e.g. "secret.aws_access_key"); default = entity
        self._prefix = detector_prefix

    def detect(self, text: str) -> list[Span]:
        """Pure, synchronous, deterministic; checksums validated by the core scanner."""
        from ..scan import default_detector

        out: list[Span] = []
        for h in default_detector().detect(text):
            if h.entity != self.entity:
                continue
            if self._prefix and not h.detector_id.startswith(self._prefix):
                continue
            out.append(Span(**h.to_span()))
        return out

    def __repr__(self) -> str:
        return f"<CoreView {self.id} -> {self.entity}>"
