"""META-V02: text metadata detectors."""

from __future__ import annotations

import pytest

from aegis.egress.params import TextParams
from aegis.egress.textmeta import mask_excerpt, scan_text

DOMAINS = ["*.acme-capital.example", "*.corp.local"]

# staging/pii/fixtures PATH_USERNAME vectors (text, expected username)
STAGING_POSITIVES = [
    ("Source File: /Users/zprzeklasa/Pictures/IMG_2041.jpg", "zprzeklasa"),
    ("template C:\\Users\\rollinsashley\\AppData\\Roaming\\Microsoft\\Templates\\Normal.dotm",
     "rollinsashley"),
    ("<env>\nWorking directory: /Users/rpabis/projects/bank-app\nPlatform: darwin\n</env>", "rpabis"),
    ("<env>\nWorking directory: /Users/marekwojnicz/projects/bank-app\n</env>", "marekwojnicz"),
    ("<env>\nWorking directory: /Users/tobiasz43/projects/bank-app\n</env>", "tobiasz43"),
    ("ssh-keygen: key saved to /home/melissafriedman/.ssh/id_ed25519", "melissafriedman"),
    ("ssh-keygen: key saved to /home/roratdagmara/.ssh/id_ed25519", "roratdagmara"),
    ("ssh-keygen: key saved to /home/sharon30/.ssh/id_ed25519", "sharon30"),
]

HARD_NEGATIVES = [
    "Copy the export to /Users/Shared/reports/q3.csv",
    "CI runs in /home/runner/work/repo",
    "Default profile lives in C:\\Users\\Public\\Documents",
    "Check ~/.ssh/config for the host alias",
    "npm i -D @types/node",
    "Upgrade to v10.20.30.40 of the firmware",
    "Requires version 10.0.0.1 or later",
    "Public resolver 8.8.8.8 is fine",
    "See docs.python.org for details",
    "Bind the dev server to 127.0.0.1:8787",
    "Rename settings.local to settings.prod",
    "What is the P/E ratio of a bank?",
]


def _users(spans):
    return [s.value for s in spans if s.entity == "USERNAME"]


@pytest.mark.parametrize(("text", "user"), STAGING_POSITIVES)
def test_staging_path_usernames(text: str, user: str) -> None:
    spans = scan_text(text, internal_domains=DOMAINS)
    assert user in _users(spans)
    s = next(s for s in spans if s.value == user)
    assert text[s.start:s.end] == user
    assert s.replacement is None  # placeholder style -> vault token


@pytest.mark.parametrize("text", HARD_NEGATIVES)
def test_hard_negatives(text: str) -> None:
    assert scan_text(text, internal_domains=DOMAINS) == []


def test_research_vector_spans() -> None:
    t = "Traceback in /Users/jdoe/acme-internal/trading/pnl.py on host jdoe-mbp.corp.local (10.20.30.40)"
    spans = scan_text(t, internal_domains=DOMAINS)
    got = {(s.entity, t[s.start:s.end]) for s in spans}
    assert ("USERNAME", "jdoe") in got
    assert ("HOSTNAME", "jdoe-mbp.corp.local") in got
    assert ("IP_ADDRESS", "10.20.30.40") in got
    assert len([s for s in spans if s.entity == "HOSTNAME"]) == 1  # one span, longest wins


def test_machine_name_without_domain() -> None:
    spans = scan_text("ssh jdoe-mbp and Janes-MacBook-Pro", internal_domains=DOMAINS)
    assert [s.value for s in spans if s.entity == "HOSTNAME"] == ["jdoe-mbp", "Janes-MacBook-Pro"]


def test_learned_identifier_in_ls_output() -> None:
    t = "drwxr-xr-x  5 jdoe  staff  160 Oct  3 21:00 trading"
    assert scan_text(t, internal_domains=DOMAINS) == []
    spans = scan_text(t, internal_domains=DOMAINS, identifiers=["jdoe"])
    assert [(s.entity, t[s.start:s.end]) for s in spans] == [("USERNAME", "jdoe")]


def test_learned_identifier_guards() -> None:
    t = "the admin user ran it as root; joe did too"
    assert scan_text(t, identifiers=["admin", "root", "joe"]) == []  # allow-list + min length


def test_generalize_style() -> None:
    t = "open /Users/jdoe/x.py on jdoe-mbp.corp.local 192.168.1.20"
    spans = scan_text(t, internal_domains=DOMAINS, style="generalize")
    reps = {s.entity: s.replacement for s in spans}
    assert reps == {"USERNAME": "~", "HOSTNAME": "[HOST]", "IP_ADDRESS": "[PRIVATE_IP]"}
    s = next(s for s in spans if s.entity == "USERNAME")
    assert t[s.start:s.end] == "/Users/jdoe"


def test_private_ranges_and_ipv6() -> None:
    t = "a 172.16.5.4 b 100.64.1.2 c fd12:3456:789a::1 d 169.254.10.10 e 1.2.3.4"
    vals = [s.value for s in scan_text(t)]
    assert vals == ["172.16.5.4", "100.64.1.2", "fd12:3456:789a::1", "169.254.10.10"]


def test_git_identities_only_when_enabled() -> None:
    t = "commit abc\nAuthor: Jane Doe <jane.doe@acme-capital.example>\nuser.email=jd@corp.example"
    assert [s for s in scan_text(t) if s.entity in ("GIT_EMAIL",)] == []
    spans = scan_text(t, params=TextParams(git=True))
    ents = sorted((s.entity, s.value) for s in spans)
    assert ("USERNAME", "Jane Doe") in ents
    assert ("GIT_EMAIL", "jane.doe@acme-capital.example") in ents
    assert ("GIT_EMAIL", "jd@corp.example") in ents


def test_disabled_text_params() -> None:
    t = "/Users/jdoe/x on 10.0.0.5"
    assert scan_text(t, params=TextParams(enabled=False)) == []
    assert [s.entity for s in scan_text(t, params=TextParams(paths=False))] == ["IP_ADDRESS"]


def test_mask_excerpt_never_raw() -> None:
    assert mask_excerpt("USERNAME", "jdoe") == "j***"
    assert mask_excerpt("HOSTNAME", "jdoe-mbp.corp.local") == "***.corp.local"
    assert mask_excerpt("IP_ADDRESS", "10.20.30.40") == "10.x.x.x"
    assert mask_excerpt("EMAIL", "jane.doe@acme.example") == "j***@a***"
