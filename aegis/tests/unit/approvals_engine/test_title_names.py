"""LIVE: approval titles keep org-directory names (requester/sponsor) but still mask customer PII."""

from __future__ import annotations

from aegis.approvals.views import Masker
from aegis.controls.config.gov05_config import change_summary
from aegis.core.policy_schema import PolicyChange


class _Red:
    def mask_for_log(self, text: str, max_len: int = 160) -> str:
        for name in ("Piotr Zieliński", "Jan Kowalski"):
            text = text.replace(name, "[PERSON]")
        return text[:max_len]


def test_text_keep_shields_org_names_only() -> None:
    m = Masker(_Red())
    t = "Piotr Zieliński wants to email Jan Kowalski"
    assert m.text(t) == "[PERSON] wants to email [PERSON]"
    assert m.text_keep(t, ["Piotr Zieliński", None, "x"]) == "Piotr Zieliński wants to email [PERSON]"
    assert m.text_keep(t, []) == m.text(t)


def test_budget_summary_keeps_verb() -> None:
    pc = PolicyChange.model_validate({"kind": "budget.raise", "path": "budgets.limits[scope=team:trading]",
                                      "scope": "team:trading", "summary": "team:trading day usd 60 → 150"})
    assert change_summary(pc) == "raise team:trading day usd 60 → 150"


def test_control_disable_summary_is_a_verb_phrase() -> None:
    pc = PolicyChange.model_validate({"kind": "control.disable", "path": "controls[id=DLP-02].enabled",
                                      "control_id": "DLP-02", "summary": "DLP-02 disabled"})
    assert change_summary(pc) == "disable DLP-02"
