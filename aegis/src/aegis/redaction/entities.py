"""Entity catalog (CONTRACTS section 3.4 + plan 03 gap entities section 4.3).

Every detector in this package reports one of these canonical entity names. The catalog is the
single place that knows an entity's data class, finding category, whether it may be vaulted
(reversible placeholder) and how it is previewed in audit excerpts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DataClassName = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED", "SECRET"]
PreviewKind = Literal["pan", "email", "iban", "secret", "ip", "username", "date", "tail2", "none"]


@dataclass(frozen=True, slots=True)
class EntityInfo:
    entity: str
    data_class: DataClassName
    category: str  # pii | pci | secret | metadata
    reversible: bool = True  # False => always "[REDACTED:ENTITY]" (never vaulted)
    preview: PreviewKind = "tail2"
    source: str = "tier-d"  # tier-d | ner | external (provided by another workstream)
    description: str = ""


def _e(entity: str, data_class: DataClassName, category: str, **kw: object) -> EntityInfo:
    return EntityInfo(entity, data_class, category, **kw)  # type: ignore[arg-type]


#: canonical entity -> info. Order = display order in /api/redaction/entities.
ENTITIES: dict[str, EntityInfo] = {
    e.entity: e
    for e in (
        # ---- CONFIDENTIAL (pii)
        _e("PESEL", "CONFIDENTIAL", "pii", description="Polish national id (mod-10 + birth date)"),
        _e("NIP", "CONFIDENTIAL", "pii", description="Polish tax id (mod-11, context required)"),
        _e("REGON", "CONFIDENTIAL", "pii", description="Polish business id (mod-11, context)"),
        _e("PL_ID_CARD", "CONFIDENTIAL", "pii", description="Polish ID card (ABA300000)"),
        _e("PASSPORT", "CONFIDENTIAL", "pii", description="Polish passport (ZS0000177)"),
        _e("IBAN", "CONFIDENTIAL", "pii", preview="iban", description="IBAN / 26-digit NRB"),
        _e("EMAIL", "CONFIDENTIAL", "pii", preview="email", description="E-mail address"),
        _e("PHONE", "CONFIDENTIAL", "pii", description="Phone number (libphonenumber)"),
        _e("DOB", "CONFIDENTIAL", "pii", preview="date", description="Date of birth (context)"),
        _e("PERSON", "CONFIDENTIAL", "pii", source="ner", description="Person name (NER)"),
        _e("ADDRESS", "CONFIDENTIAL", "pii", source="ner", description="Postal address (NER)"),
        _e("HEALTH", "CONFIDENTIAL", "pii", source="ner", description="Health data (GDPR Art. 9)"),
        _e("CRYPTO_ADDRESS", "CONFIDENTIAL", "pii", description="BTC base58/bech32, ETH EIP-55"),
        _e(
            "SPECIAL_CATEGORY",
            "CONFIDENTIAL",
            "pii",
            source="ner",
            description="GDPR Art. 9 other than health (opt-in via DLP-07 params.entities)",
        ),
        # ---- RESTRICTED (pci)
        _e("PAN", "RESTRICTED", "pci", preview="pan", description="Payment card (Luhn + IIN)"),
        _e("CARD_EXPIRY", "RESTRICTED", "pci", preview="date", description="Card expiry date"),
        _e(
            "CVV",
            "RESTRICTED",
            "pci",
            reversible=False,
            preview="none",
            description="Card security code - always dropped (PCI SAD)",
        ),
        _e(
            "TRACK_DATA",
            "RESTRICTED",
            "pci",
            reversible=False,
            preview="none",
            description="Magnetic stripe track 1/2 - always dropped (PCI SAD)",
        ),
        # ---- SECRET
        _e("AWS_KEY", "SECRET", "secret", preview="secret", description="AWS access key id"),
        _e("AWS_SECRET", "SECRET", "secret", preview="secret", description="AWS secret key"),
        _e("GITHUB_TOKEN", "SECRET", "secret", preview="secret", description="GitHub token"),
        _e("SLACK_TOKEN", "SECRET", "secret", preview="secret", description="Slack token/hook"),
        _e("STRIPE_KEY", "SECRET", "secret", preview="secret", description="Stripe API key"),
        _e("OPENAI_KEY", "SECRET", "secret", preview="secret", description="OpenAI API key"),
        _e("ANTHROPIC_KEY", "SECRET", "secret", preview="secret", description="Anthropic key"),
        _e("JWT", "SECRET", "secret", preview="secret", description="JSON Web Token"),
        _e("PRIVATE_KEY", "SECRET", "secret", preview="secret", description="PEM private key"),
        _e("PASSWORD", "SECRET", "secret", preview="secret", description="Password / passphrase"),
        _e(
            "CONNECTION_STRING",
            "SECRET",
            "secret",
            preview="secret",
            description="Credential inside scheme://user:pass@host",
        ),
        _e(
            "GENERIC_SECRET",
            "SECRET",
            "secret",
            preview="secret",
            description="Other API keys, URL secrets, session cookies",
        ),
        # ---- INTERNAL (metadata; acted on by DLP-03, metadata-egress)
        _e("IP_ADDRESS", "INTERNAL", "metadata", preview="ip", description="IPv4 / IPv6"),
        _e("MAC_ADDRESS", "INTERNAL", "metadata", description="Device MAC address"),
        _e(
            "USERNAME",
            "INTERNAL",
            "metadata",
            preview="username",
            description="OS user name inside a path",
        ),
        _e("HOSTNAME", "INTERNAL", "metadata", source="external", description="Host (DLP-03)"),
        _e("INTERNAL_URL", "INTERNAL", "metadata", source="external", description="(DLP-03)"),
        _e("FILE_PATH", "INTERNAL", "metadata", source="external", description="(DLP-03)"),
        _e("GIT_EMAIL", "INTERNAL", "metadata", source="external", description="(DLP-03)"),
    )
}

#: never vaulted, never fingerprinted, never previewed (PCI DSS 3.3.1 sensitive auth data)
IRREVERSIBLE: frozenset[str] = frozenset({"CVV", "TRACK_DATA"})

#: data-class rank for overlap tie-breaks (higher wins)
CLASS_RANK: dict[str, int] = {
    "PUBLIC": 0,
    "INTERNAL": 1,
    "CONFIDENTIAL": 2,
    "RESTRICTED": 3,
    "SECRET": 4,
}

#: entities produced by NER (or its deterministic fallback)
NER_ENTITIES: frozenset[str] = frozenset({"PERSON", "ADDRESS", "HEALTH", "SPECIAL_CATEGORY"})

#: DLP-01 default: CONFIDENTIAL + RESTRICTED Tier-D entities (INTERNAL is DLP-03's job)
DLP01_DEFAULT: tuple[str, ...] = (
    "EMAIL",
    "PHONE",
    "DOB",
    "PESEL",
    "NIP",
    "REGON",
    "PL_ID_CARD",
    "PASSPORT",
    "IBAN",
    "PAN",
    "CARD_EXPIRY",
    "CVV",
    "TRACK_DATA",
    "CRYPTO_ADDRESS",
)
#: DLP-02 default: every SECRET entity
DLP02_DEFAULT: tuple[str, ...] = tuple(e for e, i in ENTITIES.items() if i.data_class == "SECRET")
#: DLP-07 default (NER)
NER_DEFAULT: tuple[str, ...] = ("PERSON", "ADDRESS", "HEALTH", "DOB")

# ---- staged (granular detector type) -> contract entity ------------------------------------
STAGED_TO_CONTRACT: dict[str, str] = {
    "CREDIT_CARD": "PAN",
    "CARD_CVV": "CVV",
    "CARD_EXPIRY": "CARD_EXPIRY",
    "CARD_TRACK": "TRACK_DATA",
    "IBAN": "IBAN",
    "PL_NRB": "IBAN",
    "PL_PESEL": "PESEL",
    "PL_NIP": "NIP",
    "PL_REGON": "REGON",
    "PL_ID_CARD": "PL_ID_CARD",
    "PL_PASSPORT": "PASSPORT",
    "EMAIL": "EMAIL",
    "PHONE": "PHONE",
    "IP_ADDRESS": "IP_ADDRESS",
    "MAC_ADDRESS": "MAC_ADDRESS",
    "JWT": "JWT",
    "PRIVATE_KEY": "PRIVATE_KEY",
    "URL_SECRET": "GENERIC_SECRET",
    "PATH_USERNAME": "USERNAME",
    "DATE_OF_BIRTH": "DOB",
    "CRYPTO_BTC": "CRYPTO_ADDRESS",
    "CRYPTO_ETH": "CRYPTO_ADDRESS",
    "DENY_TERM": "GENERIC_SECRET",
    "CUSTOM": "GENERIC_SECRET",
}

#: secret rule id -> contract entity (rules not listed -> GENERIC_SECRET / PASSWORD)
SECRET_RULE_TO_ENTITY: dict[str, str] = {
    "aws-access-key": "AWS_KEY",
    "aws-access-key-legacy": "AWS_KEY",
    "aws-secret-key": "AWS_SECRET",
    "github-pat": "GITHUB_TOKEN",
    "github-oauth": "GITHUB_TOKEN",
    "github-app-token": "GITHUB_TOKEN",
    "github-refresh-token": "GITHUB_TOKEN",
    "github-fine-grained-pat": "GITHUB_TOKEN",
    "slack-token": "SLACK_TOKEN",
    "slack-webhook-url": "SLACK_TOKEN",
    "stripe-access-token": "STRIPE_KEY",
    "openai-api-key": "OPENAI_KEY",
    "anthropic-api-key": "ANTHROPIC_KEY",
    "connection-string-password": "CONNECTION_STRING",
    "password-label": "PASSWORD",
    "password-inline": "PASSWORD",
    "basic-auth-header": "PASSWORD",
}

#: granular staged type -> detector id (when not derived from category.entity)
STAGED_DETECTOR_ID: dict[str, str] = {
    "CREDIT_CARD": "pci.pan",
    "CARD_CVV": "pci.cvv",
    "CARD_EXPIRY": "pci.card_expiry",
    "CARD_TRACK": "pci.track_data",
    "IBAN": "pii.iban",
    "PL_NRB": "pii.nrb",
    "PL_PESEL": "pii.pesel",
    "PL_NIP": "pii.nip",
    "PL_REGON": "pii.regon",
    "PL_ID_CARD": "pii.pl_id_card",
    "PL_PASSPORT": "pii.passport",
    "EMAIL": "pii.email",
    "PHONE": "pii.phone",
    "MAC_ADDRESS": "meta.mac_address",
    "JWT": "secret.jwt",
    "PRIVATE_KEY": "secret.private_key",
    "URL_SECRET": "secret.url_param",
    "PATH_USERNAME": "meta.path_username",
    "DATE_OF_BIRTH": "pii.dob",
    "CRYPTO_BTC": "pii.crypto.btc",
    "CRYPTO_ETH": "pii.crypto.eth",
    "DENY_TERM": "custom.deny_term",
    "CUSTOM": "custom.pattern",
}


def info(entity: str) -> EntityInfo:
    """Catalog entry; unknown entities default to CONFIDENTIAL pii (fail safe)."""
    got = ENTITIES.get(entity)
    if got is not None:
        return got
    return EntityInfo(entity, "CONFIDENTIAL", "pii", source="external")


def data_class(entity: str) -> DataClassName:
    return info(entity).data_class


def category(entity: str) -> str:
    return info(entity).category


def is_reversible(entity: str) -> bool:
    return entity not in IRREVERSIBLE and info(entity).reversible


def contract_entity(staged_type: str, meta: dict | None = None) -> str:
    """Project a staged detector type (+ secret rule id) onto the contract vocabulary."""
    if staged_type == "SECRET":
        meta = meta or {}
        ent = SECRET_RULE_TO_ENTITY.get(str(meta.get("rule", "")))
        if ent:
            return ent
        return "PASSWORD" if meta.get("password") else "GENERIC_SECRET"
    return STAGED_TO_CONTRACT.get(staged_type, staged_type)


def detector_id(staged_type: str, meta: dict | None = None) -> str:
    """Stable detector ids: pii.pesel, pci.pan, secret.aws_access_key, pii.ip.private, ..."""
    meta = meta or {}
    if staged_type == "SECRET":
        rule = str(meta.get("rule") or "generic")
        return "secret." + rule.lower().replace("-", "_").replace(":", ".")
    if staged_type == "IP_ADDRESS":
        return "pii.ip.private" if meta.get("private") else "pii.ip.public"
    return STAGED_DETECTOR_ID.get(staged_type, f"pii.{staged_type.lower()}")
