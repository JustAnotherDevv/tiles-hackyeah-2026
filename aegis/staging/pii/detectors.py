"""Tier-D deterministic detectors (research 07 section 4) - reference implementation.

Pipeline per text:  normalise (offset map) -> candidate detectors on the normalised view ->
validators + context scoring -> decode-and-rescan (base64/hex) -> JSON cross-field join ->
map spans back to the ORIGINAL string -> allow-lists -> per-type min_score -> overlap merge.

Design rules honoured
  * Built-in regexes are RE2-compatible strings (no look-around, no back-refs, repetition
    <= 1000); look-around semantics are emulated in code. ``tests`` compile every built-in
    pattern with google-re2 so the set ports 1:1 to Go RE2. Built-ins run on stdlib ``re`` with
    ASCII semantics (faster in CPython than the re2 binding); *user / feed supplied* patterns
    (deny terms, custom patterns, allow patterns) are compiled with google-re2 only, so a judge
    editing the policy live cannot ReDoS the gateway.
  * Validated types (cards, IBAN, NRB, PESEL, crypto, JWT) score >= 0.9; weak-checksum types
    (NIP, REGON, ID card, passport ~10% random pass) need context words or formatting.
  * Overlap merge: tier (structural > validated > context > weak), then span length, then score
    (IBAN contains NRB, track contains PAN, conn-string password beats the email regex, ...).

Public API
  Detector(config).detect(text) -> list[Finding]   (offsets into the original text)
  Detector(config).detect_segments([seg, ...])     (cross-message / cross-field fragments)
  detect(text) / analyze(text)                     (module-level default detector)
  fingerprint(type, canonical, key)                (keyed HMAC for audit, never plain hash)
"""
from __future__ import annotations

import base64
import binascii
import bisect
import hashlib
import hmac
import ipaddress
import re
import tomllib
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import phonenumbers

from . import validators as V
from .normalize import Normalized, normalize

try:  # google-re2 (pip: google-re2) - required for user/feed supplied patterns
    import re2 as _re2
except ImportError:  # pragma: no cover
    _re2 = None

# ============================================================================ types & tiers

TIER_STRUCTURAL, TIER_VALIDATED, TIER_CONTEXT, TIER_WEAK = 0, 1, 2, 3

ENTITY_TYPES = (
    "CREDIT_CARD", "CARD_CVV", "CARD_EXPIRY", "CARD_TRACK", "IBAN", "PL_NRB", "PL_PESEL",
    "PL_NIP", "PL_REGON", "PL_ID_CARD", "PL_PASSPORT", "EMAIL", "PHONE", "IP_ADDRESS",
    "MAC_ADDRESS", "JWT", "SECRET", "PRIVATE_KEY", "URL_SECRET", "CRYPTO_BTC", "CRYPTO_ETH",
    "PATH_USERNAME", "DATE_OF_BIRTH", "DENY_TERM", "CUSTOM",
)

# Checksum / structure-validated detector types: leak rate target is exactly 0.
VALIDATED_TYPES = frozenset({
    "CREDIT_CARD", "CARD_TRACK", "IBAN", "PL_NRB", "PL_PESEL", "PL_NIP", "PL_REGON",
    "PL_ID_CARD", "PL_PASSPORT", "JWT", "PRIVATE_KEY", "CRYPTO_BTC", "CRYPTO_ETH",
})

VALIDATED_ENTITIES = frozenset({"PAN", "TRACK_DATA", "IBAN", "PESEL", "NIP", "REGON", "PL_ID_CARD",
                                "PASSPORT", "JWT", "PRIVATE_KEY", "CRYPTO_BTC", "CRYPTO_ETH"})

DEFAULT_MIN_SCORES = {"PL_NIP": 0.60, "PL_REGON": 0.70, "PL_ID_CARD": 0.70, "PL_PASSPORT": 0.70}

# ---- CONTRACTS.md s3.4 canonical vocabulary. Detector `type` stays granular (PL_NRB vs IBAN,
# one SECRET type with rule ids); `Finding.entity` is the canonical projection used for
# placeholders ([PESEL_1]), the policy matrix, metrics and the API.
CONTRACT_ENTITY = {
    "CREDIT_CARD": "PAN", "CARD_CVV": "CVV", "CARD_EXPIRY": "CARD_EXPIRY", "CARD_TRACK": "TRACK_DATA",
    "IBAN": "IBAN", "PL_NRB": "IBAN", "PL_PESEL": "PESEL", "PL_NIP": "NIP", "PL_REGON": "REGON",
    "PL_ID_CARD": "PL_ID_CARD", "PL_PASSPORT": "PASSPORT", "EMAIL": "EMAIL", "PHONE": "PHONE",
    "IP_ADDRESS": "IP_ADDRESS", "JWT": "JWT", "PRIVATE_KEY": "PRIVATE_KEY",
    "URL_SECRET": "GENERIC_SECRET", "PATH_USERNAME": "USERNAME", "DATE_OF_BIRTH": "DOB",
    # extensions not (yet) in s3.4 - keep their own names
    "MAC_ADDRESS": "MAC_ADDRESS", "CRYPTO_BTC": "CRYPTO_BTC", "CRYPTO_ETH": "CRYPTO_ETH",
    "DENY_TERM": "DENY_TERM", "CUSTOM": "CUSTOM",
}
SECRET_RULE_ENTITY = {
    "aws-access-key": "AWS_KEY", "aws-secret-key": "AWS_SECRET",
    "github-pat": "GITHUB_TOKEN", "github-oauth": "GITHUB_TOKEN", "github-app-token": "GITHUB_TOKEN",
    "github-refresh-token": "GITHUB_TOKEN", "github-fine-grained-pat": "GITHUB_TOKEN",
    "slack-token": "SLACK_TOKEN", "slack-webhook-url": "SLACK_TOKEN",
    "stripe-access-token": "STRIPE_KEY", "openai-api-key": "OPENAI_KEY",
    "anthropic-api-key": "ANTHROPIC_KEY", "connection-string-password": "CONNECTION_STRING",
    "password-label": "PASSWORD", "password-inline": "PASSWORD", "basic-auth-header": "PASSWORD",
}
DATA_CLASS = {
    **{e: "CONFIDENTIAL" for e in ("EMAIL", "PHONE", "PERSON", "ADDRESS", "DOB", "PESEL", "NIP",
                                   "REGON", "PL_ID_CARD", "PASSPORT", "IBAN", "HEALTH",
                                   "CRYPTO_BTC", "CRYPTO_ETH", "DENY_TERM", "CUSTOM")},
    **{e: "RESTRICTED" for e in ("PAN", "CARD_EXPIRY", "CVV", "TRACK_DATA")},
    **{e: "SECRET" for e in ("AWS_KEY", "AWS_SECRET", "GITHUB_TOKEN", "SLACK_TOKEN", "STRIPE_KEY",
                             "OPENAI_KEY", "ANTHROPIC_KEY", "JWT", "PRIVATE_KEY", "PASSWORD",
                             "CONNECTION_STRING", "GENERIC_SECRET")},
    **{e: "INTERNAL" for e in ("IP_ADDRESS", "HOSTNAME", "INTERNAL_URL", "FILE_PATH", "USERNAME",
                               "GIT_EMAIL", "MAC_ADDRESS")},
}
CATEGORY = {"CONFIDENTIAL": "pii", "RESTRICTED": "pci", "SECRET": "secret", "INTERNAL": "metadata"}


def contract_entity(etype: str, meta: dict | None = None) -> str:
    if etype == "SECRET":
        meta = meta or {}
        ent = SECRET_RULE_ENTITY.get(meta.get("rule", ""))
        if ent:
            return ent
        return "PASSWORD" if meta.get("password") else "GENERIC_SECRET"
    return CONTRACT_ENTITY.get(etype, etype)


@dataclass(slots=True)
class Finding:
    type: str
    start: int            # offsets into the ORIGINAL text (half-open)
    end: int
    value: str            # original substring (may contain fullwidth digits, ZW chars, ...)
    score: float
    detector: str
    tier: int = TIER_CONTEXT
    canonical: str = ""   # normalised compact form: vault key + HMAC input
    meta: dict = field(default_factory=dict)
    entity: str = ""      # CONTRACTS s3.4 canonical entity (PAN, PESEL, GITHUB_TOKEN, ...)

    @property
    def data_class(self) -> str:
        return DATA_CLASS.get(self.entity, "CONFIDENTIAL")

    @property
    def category(self) -> str:
        return CATEGORY.get(self.data_class, "pii")

    @property
    def detector_id(self) -> str:   # e.g. "pii.pesel", "secret.github_pat", "pci.pan"
        rule = self.meta.get("rule")
        return f"{self.category}.{(rule or self.entity).lower().replace('-', '_')}"

    def to_span(self) -> dict:
        """Fields of the frozen core `Span` model (offsets into the scanned text)."""
        return {"start": self.start, "end": self.end, "entity": self.entity,
                "data_class": self.data_class, "detector_id": self.detector_id,
                "score": round(self.score, 3), "category": self.category}

    def to_dict(self, include_value: bool = False) -> dict:
        d = {"type": self.type, "entity": self.entity, "start": self.start, "end": self.end,
             "score": round(self.score, 3), "detector": self.detector, "tier": self.tier,
             "meta": self.meta}
        if include_value:
            d["value"] = self.value
        return d


@dataclass(slots=True)
class _Cand:  # candidate in NORMALISED coordinates
    type: str
    a: int
    b: int
    score: float
    detector: str
    tier: int
    canonical: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class DetectorConfig:
    min_scores: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_MIN_SCORES))
    default_min_score: float = 0.50
    enabled: frozenset[str] | None = None          # None = all types
    disabled: frozenset[str] = frozenset()
    allow_private_ip: bool = True                  # private/loopback/docs ranges are not findings
    phone_regions: tuple[str, ...] = ("PL", "GB", "US", "DE")
    context_before: int = 40
    context_after: int = 25
    decode_depth: int = 2                          # base64/hex decode-and-rescan depth
    decode_max_bytes: int = 65536
    json_join: bool = True                         # cross-field fragments in JSON string leaves
    allow_patterns: tuple[str, ...] = ()           # RE2, matched against canonical value
    allow_values_hmac: frozenset[str] = frozenset()  # "hmac:<16 hex>" fingerprints to allow
    hmac_key: bytes | None = None
    deny_terms: tuple[str, ...] = ()               # -> DENY_TERM findings (case-insensitive)
    custom_patterns: tuple[dict, ...] = ()         # {"type","pattern","score"?} RE2 only
    path_user_allow: frozenset[str] = frozenset(
        {"shared", "root", "runner", "public", "default", "all users", "user", "username",
         "<user>", "$user", "${user}", "%username%", "you", "yourname", "your-name", "guest",
         "me", "name", "<username>", "ubuntu", "admin"})


# ============================================================================ helpers

def fingerprint(etype: str, canonical: str, key: bytes) -> str:
    """Keyed HMAC-SHA256 (64-bit prefix). A plain hash of a PAN/PESEL is brute-forceable."""
    mac = hmac.new(key, f"{etype}\x1f{canonical}".encode(), hashlib.sha256).hexdigest()
    return "hmac:" + mac[:16]


def compile_user_pattern(pattern: str, *, case_insensitive: bool = False):
    """Compile a user / feed supplied regex with RE2 (linear time, no ReDoS). Raises ValueError."""
    if _re2 is None:  # pragma: no cover
        raise ValueError("google-re2 is required for user supplied patterns")
    opts = _re2.Options()
    opts.case_sensitive = not case_insensitive
    opts.max_mem = 8 << 20
    opts.log_errors = False
    try:
        return _re2.compile(pattern, opts)
    except Exception as e:  # re2.error
        raise ValueError(f"invalid RE2 pattern: {e}") from e


def _alnum(c: str) -> bool:
    return c.isascii() and c.isalnum()


def _is_letter(c: str) -> bool:
    return c.isascii() and c.isalpha()


def _kw(*words: str, stems: Iterable[str] = ()) -> re.Pattern:
    alts = [re.escape(w) for w in words] + [re.escape(s) + r"\w{0,8}" for s in stems]
    alts.sort(key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(alts) + r")(?!\w)", re.I)


_LOOKS_PLACEHOLDER = (
    "example", "xxxx", "your", "placeholder", "changeme", "change_me", "change-me", "dummy",
    "sample", "redacted", "insert", "replace", "<", ">", "${", "{{", "%s", "****", "....",
    "todo", "fixme", "_here", "-here", "foobar", "lorem", "notreal", "fake",
)
_REPEAT = re.compile(r"(.)\1{7,}")
_IDENT_DOTTED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+")
_SNAKE_WORDS = re.compile(r"[a-z]+(?:_[a-z]+)+|[A-Z]+(?:_[A-Z]+)+")
_COMMON_VALUES = frozenset({"true", "false", "null", "none", "required", "optional", "string",
                            "undefined", "password", "secret", "token", "default", "hidden"})


def _placeholder(v: str) -> bool:
    lv = v.lower()
    return (lv in _COMMON_VALUES or any(p in lv for p in _LOOKS_PLACEHOLDER)
            or _REPEAT.search(v) is not None)


# ============================================================================ context words

CTX = {
    "CREDIT_CARD": _kw("pan", "visa", "mastercard", "master card", "amex", "american express",
                       "maestro", "discover", "jcb", "diners", "cc", "cvv", "cvc", "credit",
                       "debit", "payment", "nr karty", "numer karty", "kredytowa", "kredytowej",
                       "kredytową", "debetowa", "debetowej", "debetową", "płatnicza",
                       "płatniczej", "platnicza", stems=("kart", "card")),
    "NEG_CARD": _kw("imei", "meid", "serial", "serial number", "numer seryjny", "s/n", "isbn",
                    "issn", "ean", "gtin", "upc", "tracking", "przesyłki", "przesylki"),
    "PL_PESEL": _kw(stems=("pesel",)),
    "PL_NIP": _kw("vat", "vat-ue", "vat ue", "tax id", "taxid", "tax_id", "tin", "nip-ue",
                  "nip ue", "eu vat", "vat id", "vat_id", "numer identyfikacji podatkowej",
                  stems=("nip",)),
    "PL_REGON": _kw(stems=("regon",)),
    "BANK": _kw("iban", "nrb", "bic", "swift", "acct", "account", "account number",
                "account_number", "konto", "konta", "kontem", "koncie", "rachunek", "rachunku",
                "rachunkiem", "rachunki", "przelew", "przelewu", "przelewem", "transfer", "wire",
                "bank", "banku", "sort code", "beneficjent", "beneficiary"),
    "PL_ID_CARD": _kw("dowód", "dowodu", "dowodem", "dowod", "dowód osobisty",
                      "dowodu osobistego", "dow. os.", "dow.os.", "id card", "identity card",
                      "national id", "seria i numer", "seria", "nr dowodu", "numer dowodu",
                      "id_card", "id number", "document", "document number", "dokument",
                      "dokumentu", "numer dokumentu", "dokument tożsamości", "id", "polish id",
                      "identity", "identity document", "tożsamości", "dowód tożsamości"),
    "PL_PASSPORT": _kw("document", "document number", "dokument", "dokumentu",
                       "numer dokumentu", stems=("paszport", "passport")),
    "PHONE": _kw("tel", "tel.", "kom.", "komórka", "komórkowy", "komórki", "mobile", "cell",
                 "call", "zadzwoń", "zadzwon", "dzwoń", "fax", "whatsapp", "sms", "contact",
                 "kontakt", "kontaktowy", "mob", "mob.", "numer kontaktowy", "msisdn", "infolinia",
                 "reach", "reached", "dial", "ring", "text me", "zadzwonić", "dzwonić",
                 stems=("telefon", "phone")),
    "IP_ADDRESS": _kw("ip", "ip address", "adres ip", "ip_address", "client_ip", "remote_addr",
                      "x-forwarded-for", "x-real-ip", "host", "server", "serwer", "from",
                      "logowanie", "login"),
    "MAC_ADDRESS": _kw("mac", "mac address", "adres mac", "hwaddr", "ether", "bssid",
                       "mac_address", "device", "urządzenie", "urzadzenie"),
    "CRYPTO_ETH": _kw("eth", "ether", "ethereum", "wallet", "portfel", "portfela", "metamask",
                      "erc20", "erc-20", "usdt", "usdc", "address", "adres", "crypto", "krypto"),
    "CRYPTO_BTC": _kw("btc", "bitcoin", "wallet", "portfel", "portfela", "address", "adres"),
}

# letters glued to a number that do NOT disqualify it (labels without a separator)
_GLUE_OK = frozenset({"pl", "nr", "no", "id", "pesel", "nip", "regon", "tel", "card", "karta",
                      "iban", "nrb", "konto", "acct"})

# ============================================================================ built-in patterns
# All strings below are RE2-compatible (checked by tests). Compiled with stdlib re + ASCII.

P = {
    "RUN": r"[0-9](?:(?:[ \t\-.]{1,3}|[ \t]*\r?\n[ \t]*)?[0-9])*",
    "GROUP": r"[0-9]+",
    "IBAN_START": r"[A-Za-z]{2}[0-9]{2}",
    "ID_CARD": r"[A-Za-z]{3}[ \-]?[0-9]{6}",
    "PASSPORT": r"[A-Za-z]{2}[ \-]?[0-9]{7}",
    "EMAIL": r"[A-Za-z0-9._%+\-]{1,64}@(?:[A-Za-z0-9\-]{1,63}\.){1,8}[A-Za-z]{2,24}",
    "URL_AUTH_TAIL": r"[A-Za-z][A-Za-z0-9+.\-]{0,30}://[^\s/?#@]{0,160}$",
    "PHONE_PRE": r"\+?\(?[0-9](?:[ \t\-.()/]{0,3}[0-9]){6,}",
    "IPV4": r"[0-9]{1,3}(?:\.[0-9]{1,3}){3}",
    "IPV6": r"(?:[0-9A-Fa-f]{0,4}:){2,7}(?:[0-9A-Fa-f]{1,4}|[0-9]{1,3}(?:\.[0-9]{1,3}){3})?",
    "VERSION_TAIL": r"(?i:version|wersja|wersji|ver|v|release|build|firmware|python|node|java|"
                    r"golang|ruby|php|libc|kernel)[ \t:=]{0,3}$|(?:==|>=|<=|~=|\^|@|~)[ \t]*$",
    "MAC_COLON": r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}",
    "MAC_DASH": r"[0-9A-Fa-f]{2}(?:-[0-9A-Fa-f]{2}){5}",
    "MAC_CISCO": r"[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}",
    "JWT": r"eyJ[A-Za-z0-9_\-.]{20,}",
    "BTC_B58": r"[13][1-9A-HJ-NP-Za-km-z]{25,34}",
    "BTC_BECH32": r"(?:bc1|BC1)[02-9ac-hj-np-zAC-HJ-NP-Z]{11,71}",
    "ETH": r"0[xX][0-9a-fA-F]{40}",
    "PATH_USER": r"(?:/Users/|/home/|[A-Za-z]:(?:\\\\|\\|/)(?i:users)(?:\\\\|\\|/))([^/\\\s\"'<>:|*?]{1,64})",
    "CVV": r"(?i:cvv2?|cvc2?|cav2|cid|csc|kod[ \t]+(?:cvv2?|cvc2?|zabezpieczający|zabezpieczajacy|"
           r"bezpieczeństwa|bezpieczenstwa)|security[ \t]+code|card[ \t]+verification(?:[ \t]+"
           r"(?:value|code))?)[\"']?[ \t]*(?:[:=#]|is|to|-)?[ \t]*[\"']?([0-9]{3,4})",
    "EXPIRY": r"(?i:exp(?:iry|ires|iration)?(?:[ \t]+date)?\.?|valid[ \t]+(?:thru|through|until)|"
              r"wa[żz]n[a-ząęóśłżźćń]{0,3}[ \t]+do|data[ \t]+wa[żz]no[śs]ci|"
              r"termin[ \t]+wa[żz]no[śs]ci)[\"']?[ \t]*[:=]?[ \t]*[\"']?"
              r"((?:0[1-9]|1[0-2])[ \t]*[/\-.][ \t]*(?:20[0-9]{2}|[0-9]{2}))",
    "EXP_TAIL": r"(?:0[1-9]|1[0-2])[ \t]*/[ \t]*(?:20[0-9]{2}|[0-9]{2})",
    "TRACK1": r"%?B[0-9]{12,19}\^[^\^\n]{2,26}\^[0-9]{4}[0-9]*\??",
    "TRACK2": r";?[0-9]{12,19}=[0-9]{4}[0-9]{3,}\??",
    "DOB_TRIGGER": r"(?i:ur\.|urodzon[ya]|urodzenia|data urodzenia|d\.o\.b\.?|dob|date of birth|"
                   r"birth[ \t_]?date|born(?:[ \t]+on)?|birthday|geb\.|geboren)",
    "DATE_ISO": r"(?:19|20)[0-9]{2}-[0-9]{2}-[0-9]{2}",
    "DATE_DMY": r"[0-9]{1,2}[./\-][0-9]{1,2}[./\-](?:19|20)[0-9]{2}",
    "DATE_WORDS_PL": r"[0-9]{1,2}[ \t]+(?i:stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|"
                     r"sierpnia|września|wrzesnia|października|pazdziernika|listopada|grudnia)"
                     r"[ \t]+(?:19|20)[0-9]{2}",
    "DATE_WORDS_EN": r"(?:[0-9]{1,2}[ \t]+(?i:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
                     r"[a-z]*\.?,?[ \t]+(?:19|20)[0-9]{2})|(?:(?i:jan|feb|mar|apr|may|jun|jul|aug|"
                     r"sep|sept|oct|nov|dec)[a-z]*\.?[ \t]+[0-9]{1,2}(?:st|nd|rd|th)?,?[ \t]+"
                     r"(?:19|20)[0-9]{2})",
    "B64": r"[A-Za-z0-9+/_\-]{16,}={0,2}",
    "HEX": r"(?:[0-9A-Fa-f]{2}){8,}",
    "JSON_STR": r"\"((?:[^\"\\\n]|\\.){1,512})\"",
    "URL_SECRET": r"[?&#;](?i:(access_token|id_token|refresh_token|token|auth|auth_token|sig|"
                  r"signature|x-amz-signature|x-amz-credential|x-amz-security-token|"
                  r"x-goog-signature|x-goog-credential|api_key|apikey|api-key|key|secret|"
                  r"client_secret|password|passwd|pass|pwd|code|session|sessionid|sid|jwt|"
                  r"access_key|secret_key))=([^&#\s\"'<>]{6,})",
    "COOKIE_LINE": r"(?im:^[ \t\"']*(?:set-)?cookie[\"']?[ \t]*:[ \t]*([^\n]*))",
    "COOKIE_PAIR": r"([A-Za-z0-9_.\-]+)=([^;\s\"']+)",
    "COOKIE_NAME": r"(?i:session|sess|sessionid|sid|connect\.sid|phpsessid|jsessionid|"
                   r"asp\.net_sessionid|auth|auth_token|access_token|refresh_token|token|"
                   r"remember_token|jwt|[a-z0-9_]*_session|__secure-[a-z0-9_\-]+|__host-[a-z0-9_\-]+)",
    "PK_BEGIN": r"-----BEGIN[ A-Z0-9_\-]{0,40}PRIVATE KEY(?: BLOCK)?-----",
    "PK_END": r"-----END[ A-Z0-9_\-]{0,40}PRIVATE KEY(?: BLOCK)?-----",
    "PK_TRUNC": r"-----BEGIN[ A-Z0-9_\-]{0,40}PRIVATE KEY(?: BLOCK)?-----(?:\\n|\\r|\s)*"
                r"[A-Za-z0-9+/=]{40,}(?:(?:\\n|\\r|\s)+[A-Za-z0-9+/=]{4,})*",
}


@dataclass(frozen=True)
class SecretRule:
    id: str
    pattern: str
    group: int = 0
    keywords: tuple[str, ...] = ()
    min_entropy: float = 0.0
    score: float = 0.95
    tier: int = TIER_VALIDATED
    type: str = "SECRET"
    boundary: bool = True        # emulate \b on both sides of the secret group
    generic: bool = False        # extra identifier / value-shape filtering


# Formats modelled on gitleaks v8 rules (MIT). A loader for the full gitleaks.toml is below.
SECRET_RULES: tuple[SecretRule, ...] = (
    SecretRule("aws-access-key", r"(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16}",
               keywords=("akia", "asia", "abia", "acca", "a3t")),
    SecretRule("aws-secret-key",
               r"(?i:aws_?secret_?(?:access_?)?key|secret_?access_?key)[\"']?[ \t]*(?:=|:|=>)[ \t]*"
               r"[\"']?([A-Za-z0-9/+=]{40})", group=1, keywords=("secret",), min_entropy=3.5),
    SecretRule("github-pat", r"ghp_[0-9A-Za-z]{36}", keywords=("ghp_",), min_entropy=3.0),
    SecretRule("github-oauth", r"gho_[0-9A-Za-z]{36}", keywords=("gho_",), min_entropy=3.0),
    SecretRule("github-app-token", r"(?:ghu|ghs)_[0-9A-Za-z]{36}", keywords=("ghu_", "ghs_"),
               min_entropy=3.0),
    SecretRule("github-refresh-token", r"ghr_[0-9A-Za-z]{36}", keywords=("ghr_",), min_entropy=3.0),
    SecretRule("github-fine-grained-pat", r"github_pat_[0-9A-Za-z_]{82}", keywords=("github_pat_",)),
    SecretRule("gitlab-pat", r"glpat-[0-9A-Za-z_\-]{20}", keywords=("glpat-",), min_entropy=3.0),
    SecretRule("slack-token", r"xox[baprs]-[0-9A-Za-z\-]{10,250}", keywords=("xox",),
               min_entropy=3.0),
    SecretRule("slack-webhook-url",
               r"(?:https?://)?hooks\.slack\.com/(?:services|workflows|triggers)/[A-Za-z0-9+/]{43,56}",
               keywords=("hooks.slack.com",)),
    SecretRule("stripe-access-token", r"(?:sk|rk)_(?:test|live|prod)_[0-9A-Za-z]{10,99}",
               keywords=("sk_", "rk_"), min_entropy=3.0),
    SecretRule("openai-api-key",
               r"sk-(?:(?:proj|svcacct|admin)-)?[A-Za-z0-9_\-]{20,74}T3BlbkFJ[A-Za-z0-9_\-]{20,74}",
               keywords=("t3blbkfj",)),
    SecretRule("anthropic-api-key", r"sk-ant-(?:api03|admin01)-[A-Za-z0-9_\-]{93}AA",
               keywords=("sk-ant-",)),
    SecretRule("gcp-api-key", r"AIza[0-9A-Za-z_\-]{35}", keywords=("aiza",), min_entropy=3.0),
    SecretRule("huggingface-token", r"(?:hf_|api_org_)[A-Za-z]{34}", keywords=("hf_", "api_org_"),
               min_entropy=3.0),
    SecretRule("npm-access-token", r"npm_[A-Za-z0-9]{36}", keywords=("npm_",), min_entropy=3.0),
    SecretRule("pypi-upload-token", r"pypi-AgEIcHlwaS5vcmc[A-Za-z0-9_\-]{50,1000}",
               keywords=("pypi-ageichlwas5vcmc",)),
    SecretRule("sendgrid-api-token", r"SG\.[A-Za-z0-9=_\-]{22}\.[A-Za-z0-9=_\-]{43}",
               keywords=("sg.",)),
    SecretRule("twilio-api-key", r"SK[0-9a-fA-F]{32}", keywords=("sk",), min_entropy=3.0),
    SecretRule("shopify-token", r"shp(?:at|ca|pa|ss)_[a-fA-F0-9]{32}",
               keywords=("shpat_", "shpca_", "shppa_", "shpss_")),
    SecretRule("digitalocean-token", r"do[opr]_v1_[a-f0-9]{64}",
               keywords=("dop_v1_", "doo_v1_", "dor_v1_")),
    SecretRule("databricks-token", r"dapi[a-f0-9]{32}(?:-[0-9]+)?", keywords=("dapi",),
               min_entropy=3.0),
    SecretRule("telegram-bot-token", r"[0-9]{5,16}:A[A-Za-z0-9_\-]{34}", keywords=(":a",),
               min_entropy=3.0),
    SecretRule("groq-api-key", r"gsk_[A-Za-z0-9]{52}", keywords=("gsk_",)),
    SecretRule("mailgun-private-key", r"key-[a-f0-9]{32}", keywords=("key-",), min_entropy=3.0),
    SecretRule("square-token", r"sq0(?:atp|csp)-[0-9A-Za-z_\-]{22,43}", keywords=("sq0",)),
    SecretRule("postman-api-key", r"PMAK-[a-f0-9]{24}-[a-f0-9]{34}", keywords=("pmak-",)),
    SecretRule("linear-api-key", r"lin_api_[A-Za-z0-9]{40}", keywords=("lin_api_",)),
    SecretRule("vault-service-token", r"hvs\.[A-Za-z0-9_\-]{90,120}", keywords=("hvs.",)),
    SecretRule("azure-ad-client-secret", r"[A-Za-z0-9_~.]{3}[0-9]Q~[A-Za-z0-9_~.\-]{31,34}",
               keywords=("q~",)),
    # --- connection strings / headers / config files (generic, lower tier) ---
    SecretRule("connection-string-password",
               r"[A-Za-z][A-Za-z0-9+.\-]{1,20}://[^\s:@/'\"]{1,64}:([^\s@/'\"]{3,128})@[A-Za-z0-9.\-\[\]_]+",
               group=1, keywords=("://",), score=0.9, boundary=False),
    SecretRule("bearer-token", r"(?i:bearer)[ \t]+([A-Za-z0-9\-._~+/]{16,}=*)", group=1,
               keywords=("bearer",), min_entropy=3.0, score=0.85, tier=TIER_CONTEXT, boundary=False),
    SecretRule("basic-auth-header",
               r"(?i:authorization)[\"']?[ \t]*[:=][ \t]*[\"']?(?i:basic)[ \t]+([A-Za-z0-9+/]{12,}={0,2})",
               group=1, keywords=("basic",), score=0.85, tier=TIER_CONTEXT, boundary=False),
    SecretRule("env-assignment",
               r"(?m:^[ \t]*(?:export[ \t]+)?[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|"
               r"PASS|CREDENTIALS?|AUTH)[A-Z0-9_]*[ \t]*=[ \t]*[\"']?([^\s\"'#]{6,}))",
               group=1, keywords=("=",), min_entropy=2.5, score=0.8, tier=TIER_CONTEXT,
               boundary=False, generic=True),
    SecretRule("password-label",
               r"(?i:hasło|haslo|password|passwd|passphrase|passcode)[^\n:=]{0,40}?[:=][ \t]*[\"']?"
               r"([^\s\"'`,;()\[\]{}<>]{6,200})",
               group=1, keywords=("hasło", "haslo", "pass"), min_entropy=2.5, score=0.75,
               tier=TIER_CONTEXT, boundary=False, generic=True),
    SecretRule("password-inline",  # 'login admin, hasło Xy7!...' / 'password is Xy7!...'
               r"(?i:hasło|haslo|password|passwd)[ \t]+(?:(?:to|is|jest|brzmi)[ \t]+)?[\"']?"
               r"([^\s\"'`,;()\[\]{}<>]{8,64})",
               group=1, keywords=("hasło", "haslo", "pass"), min_entropy=3.0, score=0.75,
               tier=TIER_CONTEXT, boundary=False, generic=True),
    SecretRule("generic-credential",
               r"(?i:(?:api|access|auth|client|secret|private|refresh|session|app|master|db|database|"
               r"admin|user|signing|encryption)?[_\-.]?(?:key|token|secret|passwd|password|pwd|"
               r"passphrase|hasło|haslo|credentials?))[\"']?[ \t]{0,5}(?:=|:|:=|=>)[ \t]{0,5}[\"']?"
               r"([^\s\"'`,;()\[\]{}<>]{8,200})",
               group=1, keywords=("key", "token", "secret", "pass", "pwd", "hasło", "haslo",
                                  "credential"),
               min_entropy=3.0, score=0.7, tier=TIER_CONTEXT, boundary=False, generic=True),
)


def load_gitleaks_rules(path: str) -> list[SecretRule]:
    """Load the full gitleaks.toml (MIT) as SecretRules for the Python path.

    gitleaks uses Go RE2 syntax with mid-pattern ``(?i)``; we strip a leading global flag and
    let stdlib ``re`` handle the rest (22/222 rules need this per research 07). Rules whose
    regex fails to compile are skipped. Allow-lists from the TOML are not imported (we keep
    our own placeholder filter); the keyword prefilter IS honoured (it is mandatory for speed).
    """
    with open(path, "rb") as fh:
        cfg = tomllib.load(fh)
    rules: list[SecretRule] = []
    for r in cfg.get("rules", []):
        rx = r.get("regex")
        if not rx:
            continue
        rx = rx.replace("(?i)", "")
        flags_ci = "(?i)" in r.get("regex", "")
        pat = f"(?i:{rx})" if flags_ci else rx
        try:
            re.compile(pat)
        except re.error:
            continue
        rules.append(SecretRule(
            id="gitleaks:" + r.get("id", "?"), pattern=pat, group=int(r.get("secretGroup", 0) or 0),
            keywords=tuple(k.lower() for k in r.get("keywords", [])),
            min_entropy=float(r.get("entropy", 0) or 0),
            score=0.7 if r.get("id") == "generic-api-key" else 0.95,
            tier=TIER_CONTEXT if r.get("id") == "generic-api-key" else TIER_VALIDATED,
            boundary=False, generic=r.get("id") == "generic-api-key"))
    return rules


# ============================================================================ digit groupings

_CARD_GROUPINGS = {(4, 4, 4, 4), (4, 4, 4, 4, 3), (4, 6, 5), (4, 6, 4), (4, 4, 4, 3), (4, 4, 5)}
_ID_GROUPINGS = {
    "PL_PESEL": {(11,), (6, 5)},
    "PL_NIP": {(10,), (3, 3, 2, 2), (3, 2, 2, 3)},
    "PL_REGON": {(9,), (14,), (3, 3, 3)},
    "PL_NRB": {(26,), (2, 4, 4, 4, 4, 4, 4)},
}
_ID_LEN = {11: "PL_PESEL", 10: "PL_NIP", 9: "PL_REGON", 14: "PL_REGON", 26: "PL_NRB"}
_WINDOW_LENS = frozenset({9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 26})
_MAX_ONES_GROUPS = 256
_ID_VALID = {"PL_PESEL": V.pesel_ok, "PL_NIP": V.nip_ok, "PL_REGON": V.regon_ok, "PL_NRB": V.nrb_ok}


def _card_canonical(sizes: tuple[int, ...], n: int) -> bool:
    return len(sizes) == 1 or sizes in _CARD_GROUPINGS or (all(s == 1 for s in sizes) and n >= 12)


def _id_canonical(etype: str, sizes: tuple[int, ...]) -> bool:
    if sizes in _ID_GROUPINGS[etype]:
        return True
    return etype in ("PL_PESEL", "PL_NRB") and len(sizes) > 1 and all(s == 1 for s in sizes)


# ============================================================================ the detector

class Detector:
    def __init__(self, config: DetectorConfig | None = None,
                 extra_secret_rules: Sequence[SecretRule] = ()):
        self.cfg = config or DetectorConfig()
        A = re.ASCII
        self.rx = {k: re.compile(v, A) for k, v in P.items()}
        self.rx["JSON_STR"] = re.compile(P["JSON_STR"])  # unicode content allowed
        self.rules = [(r, re.compile(r.pattern, A)) for r in (*SECRET_RULES, *extra_secret_rules)]
        self.allow_rx = [compile_user_pattern(p) for p in self.cfg.allow_patterns]
        self.deny_rx = None
        if self.cfg.deny_terms:
            alt = "|".join(_re2.escape(t) if _re2 else re.escape(t) for t in self.cfg.deny_terms)
            self.deny_rx = compile_user_pattern(alt, case_insensitive=True)
        self.custom = [(c["type"], compile_user_pattern(c["pattern"]), float(c.get("score", 0.8)))
                       for c in self.cfg.custom_patterns]

    # ------------------------------------------------------------------ public API
    def detect(self, text: str, *, include_below_threshold: bool = False) -> list[Finding]:
        nv = normalize(text)
        cands = self._detect_view(nv.text, depth=0)
        out = [self._to_finding(nv, c) for c in cands]
        out = [f for f in out if not self._allowed(f)]
        if include_below_threshold:
            return sorted(out, key=lambda f: (f.start, f.end))
        return self._finalize(out)

    def analyze(self, text: str) -> list[Finding]:
        """Everything incl. sub-threshold candidates (for 'monitor' mode / explainability)."""
        return self.detect(text, include_below_threshold=True)

    def detect_segments(self, segments: Sequence[str]) -> list[list[Finding]]:
        """Per-segment findings + fragments of values split ACROSS segments (A7/A8).

        Segments are the user-authored string leaves of one request in order (messages, JSON
        fields). A card/IBAN/NRB crossing a boundary yields one fragment Finding per segment
        (meta.fragment=True; operator: non-reversible mask)."""
        per = [self.detect(s) for s in segments]
        nvs = [normalize(s) for s in segments]
        joined, owner = self._join([(i, 0, len(nv.text), nv.text) for i, nv in enumerate(nvs)])
        for c in self._cross_candidates(joined):
            for (seg, a, b) in self._split(owner, c.a, c.b):
                f = self._to_finding(nvs[seg], _Cand(c.type, a, b, c.score, "join>" + c.detector,
                                                     c.tier, c.canonical, {"fragment": True}))
                if not any(g.start < f.end and f.start < g.end for g in per[seg]):
                    per[seg].append(f)
        return [self._finalize(fs) for fs in per]

    # ------------------------------------------------------------------ finalize
    def _min_score(self, etype: str) -> float:
        return self.cfg.min_scores.get(etype, self.cfg.default_min_score)

    def _type_enabled(self, etype: str) -> bool:
        if etype in self.cfg.disabled:
            return False
        return self.cfg.enabled is None or etype in self.cfg.enabled

    def _finalize(self, fs: list[Finding]) -> list[Finding]:
        fs = [f for f in fs if f.score >= self._min_score(f.type) and self._type_enabled(f.type)]
        return _merge(fs, key=lambda f: (f.start, f.end))

    def _allowed(self, f: Finding) -> bool:
        if self.allow_rx and any(r.search(f.canonical or f.value) for r in self.allow_rx):
            return True
        if self.cfg.allow_values_hmac and self.cfg.hmac_key:
            return fingerprint(f.type, f.canonical, self.cfg.hmac_key) in self.cfg.allow_values_hmac
        return False

    @staticmethod
    def _to_finding(nv: Normalized, c: _Cand) -> Finding:
        s, e = nv.to_original(c.a, c.b)
        return Finding(c.type, s, e, nv.original[s:e], min(c.score, 1.0), c.detector, c.tier,
                       c.canonical or nv.text[c.a:c.b], c.meta, contract_entity(c.type, c.meta))

    # ------------------------------------------------------------------ core (normalised view)
    def _detect_view(self, t: str, depth: int) -> list[_Cand]:
        sc = _Scan(self, t)
        cands: list[_Cand] = []
        cands += sc.digit_runs()
        cands += sc.ibans()
        cands += sc.letter_ids()
        cands += sc.track_data()
        cands += sc.cvv_expiry()
        cands += sc.card_tails(cands)
        cands += sc.emails()
        cands += sc.ips()
        cands += sc.macs()
        cands += sc.jwts()
        cands += sc.secrets()
        cands += sc.url_secrets()
        cands += sc.cookies()
        cands += sc.private_keys()
        cands += sc.crypto()
        cands += sc.path_users()
        cands += sc.dob()
        cands += sc.phones(cands)
        cands += sc.user_patterns()
        if depth < self.cfg.decode_depth:
            cands += sc.decoded(cands, depth)
        if self.cfg.json_join and depth == 0:
            cands += sc.json_fragments(cands)
        if self.cfg.allow_private_ip:  # private/loopback/doc ranges are not findings
            cands = [c for c in cands if not (c.type == "IP_ADDRESS" and c.meta.get("private"))]
        return cands

    # used by decode-and-rescan: full pipeline incl. threshold + merge on a decoded string
    def _detect_inner(self, s: str, depth: int) -> list[_Cand]:
        nv = normalize(s)
        cs = self._detect_view(nv.text, depth)
        cs = [c for c in cs if c.score >= self._min_score(c.type) and self._type_enabled(c.type)]
        return _merge(cs, key=lambda c: (c.a, c.b))

    # ------------------------------------------------------------------ cross-segment helpers
    @staticmethod
    def _join(leaves: list[tuple[int, int, int, str]]) -> tuple[str, list[tuple[int, int] | None]]:
        parts: list[str] = []
        owner: list[tuple[int, int] | None] = []
        for k, (seg, a, b, txt) in enumerate(leaves):
            if k:
                parts.append("\n")
                owner.append(None)
            parts.append(txt[a:b])
            owner.extend((seg, i) for i in range(a, b))
        return "".join(parts), owner

    @staticmethod
    def _split(owner, a: int, b: int) -> list[tuple[int, int, int]]:
        out: list[tuple[int, int, int]] = []
        cur = None
        for j in range(a, b):
            o = owner[j]
            if o is None:
                if cur:
                    out.append(cur)
                cur = None
                continue
            seg, i = o
            if cur and cur[0] == seg and cur[2] == i:
                cur = (seg, cur[1], i + 1)
            else:
                if cur:
                    out.append(cur)
                cur = (seg, i, i + 1)
        if cur:
            out.append(cur)
        return out

    def _cross_candidates(self, joined: str) -> list[_Cand]:
        sc = _Scan(self, joined)
        out = []
        for c in sc.digit_runs() + sc.ibans():
            if "\n" not in joined[c.a:c.b] or c.type not in ("CREDIT_CARD", "IBAN", "PL_NRB"):
                continue
            if c.score < self._min_score(c.type):
                continue
            pieces = [p for p in joined[c.a:c.b].split("\n")]
            if all(sum(ch.isdigit() for ch in p) >= 2 for p in pieces):
                out.append(c)
        return out


def _merge(items, key):
    """Greedy non-overlapping selection: tier asc, span length desc, score desc. O(n log n)."""
    def span(x):
        return (x.start, x.end) if isinstance(x, Finding) else (x.a, x.b)

    order = sorted(items, key=lambda x: (x.tier, span(x)[0] - span(x)[1], -x.score, span(x)[0]))
    starts: list[int] = []
    ends: list[int] = []
    taken: list = []
    for x in order:
        s, e = span(x)
        if e <= s:
            continue
        i = bisect.bisect_right(starts, s)
        if i > 0 and ends[i - 1] > s:      # predecessor overlaps
            continue
        if i < len(starts) and starts[i] < e:  # successor overlaps
            continue
        starts.insert(i, s)
        ends.insert(i, e)
        taken.append(x)
    return sorted(taken, key=key)


class _Cover:
    """Is [a, b) fully inside one of a set of intervals? (bisect + prefix max-end)"""

    def __init__(self, spans: Iterable[tuple[int, int]]):
        sp = sorted(spans)
        self.starts = [a for a, _ in sp]
        self.maxend: list[int] = []
        m = -1
        for _, b in sp:
            m = max(m, b)
            self.maxend.append(m)

    def covers(self, a: int, b: int) -> bool:
        i = bisect.bisect_right(self.starts, a) - 1
        return i >= 0 and self.maxend[i] >= b


# ============================================================================ per-call scanner

_CVV_TAIL = re.compile(r"[0-9]{3,4}")
_NONDIGIT = re.compile(r"[^0-9]+")

class _Scan:
    def __init__(self, det: Detector, t: str):
        self.d = det
        self.cfg = det.cfg
        self.rx = det.rx
        self.t = t
        self.n = len(t)
        self.low = t.lower() if t.isascii() else None
        runs = [(m.start(), m.end()) for m in self.rx["RUN"].finditer(t)]
        self.runs = runs
        self.run_starts = [a for a, _ in runs]
        self.run_ends = [b for _, b in runs]

    # ---------------------------------------------------------------- context
    def ctx(self, key: str, a: int, b: int) -> float:
        """1.0 if a keyword is in the 'near' window (between the previous number and the
        candidate), 0.5 if only in the wider window, else 0.0."""
        rx = CTX.get(key)
        if rx is None:
            return 0.0
        t = self.t
        lo = max(0, a - self.cfg.context_before)
        hi = min(self.n, b + self.cfg.context_after)
        i = bisect.bisect_right(self.run_ends, a) - 1
        near_lo = max(lo, self.run_ends[i]) if i >= 0 else lo
        j = bisect.bisect_left(self.run_starts, b)
        near_hi = min(hi, self.run_starts[j]) if j < len(self.run_starts) else hi
        if rx.search(t, near_lo, a) or rx.search(t, b, near_hi):
            return 1.0
        if rx.search(t, lo, a) or rx.search(t, b, hi):
            return 0.5
        return 0.0

    def _kw_present(self, *words: str) -> bool:
        low = self.low if self.low is not None else self.t.lower()
        return any(w in low for w in words)

    def glue_before(self, a: int) -> str | None:
        """Letter token directly attached before position a (None if not a letter)."""
        t = self.t
        if a == 0 or not _is_letter(t[a - 1]):
            return None
        i = a
        while i > 0 and _is_letter(t[i - 1]):
            i -= 1
        return t[i:a].lower()

    def letter_after(self, b: int) -> bool:
        return b < self.n and _is_letter(self.t[b])

    def plus_before(self, a: int) -> bool:
        i = a - 1
        while i >= 0 and self.t[i] in " (\t":
            i -= 1
            if a - i > 3:
                break
        return i >= 0 and self.t[i] == "+"

    # ---------------------------------------------------------------- digit runs: cards & PL IDs
    def digit_runs(self) -> list[_Cand]:
        out: list[_Cand] = []
        t = self.t
        grx = self.rx["GROUP"]
        for ra, rb in self.runs:
            if rb - ra < 9:
                continue
            groups = [(m.start(), m.end()) for m in grx.finditer(t, ra, rb)]
            G = len(groups)
            parts = [t[a:b] for a, b in groups]
            all_digits = "".join(parts)
            if len(all_digits) < 9:
                continue
            seps = [t[groups[k][1]:groups[k + 1][0]] for k in range(G - 1)]
            # IPv4-shaped runs (a.b.c.d, each <= 3 digits) are not IDs or cards
            if G == 4 and all(s == "." for s in seps) and V.ip_info(".".join(parts))[0]:
                continue
            glue = self.glue_before(ra)
            letter_adj = (glue is not None and glue not in _GLUE_OK) or self.letter_after(rb)
            plus = self.plus_before(ra)
            card_cands: list[tuple] = []

            def consider(i: int, j: int, digits: str, whole: bool, allow_ids: bool) -> bool:
                L = len(digits)
                sizes = tuple(len(p) for p in parts[i:j + 1])
                a, b = groups[i][0], groups[j][1]
                nl = any("\n" in s for s in seps[i:j])
                if 12 <= L <= 19 and V.card_ok(digits):
                    canon = _card_canonical(sizes, L)
                    if whole or canon:
                        card_cands.append((a, b, digits, sizes, canon, nl, whole))
                etype = _ID_LEN.get(L)
                if allow_ids and etype and _ID_VALID[etype](digits):
                    canon = _id_canonical(etype, sizes)
                    if whole or canon:
                        c = self._id_cand(etype, a, b, digits, sizes, canon, nl, glue, letter_adj, plus)
                        if c:
                            out.append(c)
                            return True
                return False

            whole_id = len(all_digits) <= 26 and consider(0, G - 1, all_digits, True, True)
            if G > 1:
                big = G > _MAX_ONES_GROUPS   # single-digit-gap (A2) windows only in runs <= 256 groups
                for i in range(G):
                    if big and len(parts[i]) == 1:
                        continue   # no canonical multi-group format starts with a 1-digit group
                    digits = ""
                    for j in range(i, G):
                        digits += parts[j]
                        L = len(digits)
                        if L > 26:
                            break
                        if (i == 0 and j == G - 1) or L not in _WINDOW_LENS:
                            continue
                        consider(i, j, digits, False, not whole_id)
            out += self._pick_cards(card_cands, letter_adj)
        return out

    def _pick_cards(self, cc: list[tuple], letter_adj: bool) -> list[_Cand]:
        if not cc:
            return []
        # PAN+CVV glued as (4,4,4,4,3): prefer the 16-digit prefix when it is itself valid
        pref = []
        for c in cc:
            a, b, digits, sizes, canon, nl, whole = c
            shorter = [d for d in cc if d[0] == a and d[1] < b and d[4] and len(d[2]) == 16]
            if len(digits) > 16 and sizes[-1] <= 4 and shorter:
                continue
            pref.append(c)
        pref.sort(key=lambda c: (not c[4], -(c[1] - c[0])))
        out: list[_Cand] = []
        for a, b, digits, sizes, canon, nl, whole in pref:
            if any(not (b <= o.a or a >= o.b) for o in out):
                continue
            score = 0.9 if canon else 0.8
            if nl:
                score -= 0.1
            if letter_adj:
                score = min(score, 0.55)
            is_test = digits in V.TEST_PANS
            ctx = self.ctx("CREDIT_CARD", a, b)
            score += 0.1 * ctx
            if self.ctx("NEG_CARD", a, b) == 1.0 and not is_test and ctx < 1.0:
                score = 0.2
            if is_test:
                score = max(score, 0.95)
            # a 14-digit REGON with REGON context that also passes Luhn+Diners stays a REGON
            if len(digits) == 14 and self.ctx("PL_REGON", a, b) == 1.0 and ctx == 0.0:
                continue
            out.append(_Cand("CREDIT_CARD", a, b, score, "luhn+iin", TIER_VALIDATED, digits,
                             {"brand": V.card_brand(digits), "test_pan": is_test}))
        return out

    def _id_cand(self, etype, a, b, digits, sizes, canon, nl, glue, letter_adj, plus) -> _Cand | None:
        t = self.t
        ctx_key = "BANK" if etype == "PL_NRB" else etype
        ctx = self.ctx(ctx_key, a, b)
        if glue and glue not in _GLUE_OK:
            return None
        if letter_adj and not ctx:
            return None
        if etype == "PL_PESEL":
            if plus and ctx < 1.0:
                return None
            score = (0.9 if sizes == (11,) else 0.75) + 0.1 * ctx
            if nl:
                score -= 0.1
            return _Cand(etype, a, b, score, "pesel", TIER_VALIDATED, digits,
                         {"birthdate": str(V.pesel_birthdate(digits))})
        if etype == "PL_NRB":
            score = 0.85 if sizes == (26,) else 0.9 if canon else 0.75
            score += 0.1 * ctx - (0.05 if nl else 0)
            return _Cand(etype, a, b, score, "nrb-mod97", TIER_VALIDATED, digits)
        if plus and ctx < 1.0:
            return None
        if etype == "PL_NIP":
            if sizes == (10,):
                score = 0.45
            elif sizes in ((3, 3, 2, 2), (3, 2, 2, 3)):
                score = 0.6 if all(s == "-" for s in self._seps(a, b)) else 0.55
            else:
                score = 0.4
            # PL prefix (VAT-UE format) -> include it in the span
            pa = a
            if a >= 2 and t[a - 2:a].upper() == "PL":
                pa, score = a - 2, max(score, 0.65)
            elif a >= 3 and t[a - 3:a].upper() == "PL ":
                pa, score = a - 3, max(score, 0.65)
            score += 0.35 if ctx == 1.0 else 0.2 if ctx else 0.0
            return _Cand(etype, pa, b, score, "nip-mod11", TIER_CONTEXT, digits)
        if etype == "PL_REGON":
            score = (0.45 if canon else 0.4) + (0.35 if ctx == 1.0 else 0.2 if ctx else 0.0)
            return _Cand(etype, a, b, score, "regon-mod11", TIER_CONTEXT, digits)
        return None

    def _seps(self, a: int, b: int) -> list[str]:
        return _NONDIGIT.findall(self.t[a:b])

    # ---------------------------------------------------------------- IBAN
    def ibans(self) -> list[_Cand]:
        out = []
        t = self.t
        for m in self.rx["IBAN_START"].finditer(t):
            a = m.start()
            if a > 0 and _alnum(t[a - 1]):
                continue
            r = self._scan_iban(a)
            if r is None:
                continue
            canon, b, nl = r
            upper = t[a:a + 2].isupper()
            score = (0.95 if upper else 0.85) - (0.05 if nl else 0) + 0.05 * self.ctx("BANK", a, b)
            out.append(_Cand("IBAN", a, b, score, "iban-mod97", TIER_VALIDATED, canon,
                             {"country": canon[:2]}))
        return out

    def _scan_iban(self, a: int):
        t, n = self.t, self.n
        cc = t[a:a + 2].upper()
        exp = V.IBAN_LENGTHS.get(cc)
        if exp is None:  # every IBAN country is in the SWIFT registry table
            return None
        chars: list[tuple[str, int]] = []
        i = a
        newlines = 0
        limit = exp or 34
        while i < n and len(chars) < limit:
            c = t[i]
            if _alnum(c):
                chars.append((c.upper(), i))
                i += 1
                continue
            j, nl = i, 0
            while j < n and t[j] in " \t-\r\n":
                nl += t[j] == "\n"
                j += 1
            seps = j - i
            if (len(chars) < 4 or seps == 0 or nl > 1 or newlines + nl > 1
                    or (not nl and seps > 2) or (nl and seps > 8)):
                break
            if j >= n or not _alnum(t[j]):
                break
            newlines += nl
            i = j
        for L in (exp,):
            if L > len(chars):
                continue
            s = "".join(c for c, _ in chars[:L])
            if not V.iban_ok(s):
                continue
            end = chars[L - 1][1] + 1
            if end < n and _alnum(t[end]):
                continue
            return s, end, newlines > 0
        return None

    # ---------------------------------------------------------------- PL ID card / passport
    def letter_ids(self) -> list[_Cand]:
        out = []
        t = self.t
        for key, etype, ok, det in (("ID_CARD", "PL_ID_CARD", V.pl_id_card_ok, "idcard-mod10"),
                                    ("PASSPORT", "PL_PASSPORT", V.pl_passport_ok, "passport-mod10")):
            for m in self.rx[key].finditer(t):
                a, b = m.span()
                if (a > 0 and _alnum(t[a - 1])) or (b < self.n and _alnum(t[b])):
                    continue
                canon = m.group(0).replace(" ", "").replace("-", "").upper()
                if not ok(canon):
                    continue
                letters = m.group(0)[:3 if etype == "PL_ID_CARD" else 2]
                score = 0.45 if letters.isupper() else 0.35
                if " " in m.group(0) or "-" in m.group(0):
                    score += 0.05
                ctx = self.ctx(etype, a, b)
                score += 0.35 if ctx == 1.0 else 0.2 if ctx else 0.0
                out.append(_Cand(etype, a, b, score, det, TIER_CONTEXT, canon))
        return out

    # ---------------------------------------------------------------- PCI: track, CVV, expiry
    def track_data(self) -> list[_Cand]:
        out = []
        t = self.t
        if "^" not in t and "=" not in t:
            return out
        for key in ("TRACK1", "TRACK2"):
            for m in self.rx[key].finditer(t):
                pan = re.search(r"[0-9]{12,19}", m.group(0))
                if pan and V.luhn_ok(pan.group(0)):
                    out.append(_Cand("CARD_TRACK", m.start(), m.end(), 1.0, key.lower(),
                                     TIER_STRUCTURAL, "", {}))
        return out

    def cvv_expiry(self) -> list[_Cand]:
        out = []
        t = self.t
        for key, etype, det in (("CVV", "CARD_CVV", "cvv-ctx"), ("EXPIRY", "CARD_EXPIRY", "expiry-ctx")):
            for m in self.rx[key].finditer(t):
                a, b = m.span(1)
                s0 = m.start()
                if s0 > 0 and _is_letter(t[s0 - 1]):
                    continue
                if b < self.n and t[b].isdigit():
                    continue
                score = 0.95 if etype == "CARD_CVV" else 0.85
                canon = "" if etype == "CARD_CVV" else re.sub(r"[ \t]", "", m.group(1))
                out.append(_Cand(etype, a, b, score, det, TIER_CONTEXT, canon))
        return out

    def card_tails(self, cands: list[_Cand]) -> list[_Cand]:
        """MM/YY and CVV directly after a PAN (dumps like 'PAN|12/27|123', 'PAN 12/27 123')."""
        out = []
        t = self.t
        for c in cands:
            if c.type != "CREDIT_CARD":
                continue
            i = self._skip(c.b, " \t,;|/")
            m = self.rx["EXP_TAIL"].match(t, i)
            if m and not (m.end() < self.n and t[m.end()].isdigit()):
                out.append(_Cand("CARD_EXPIRY", m.start(), m.end(), 0.8, "expiry-after-pan",
                                 TIER_CONTEXT, re.sub(r"[ \t]", "", m.group(0))))
                i = self._skip(m.end(), " \t,;|/")
            m = _CVV_TAIL.match(t, i)
            if m and i - c.b <= 40:
                e = m.end()
                nxt = t[e] if e < self.n else ""
                L = e - m.start()
                if not (nxt and (nxt.isdigit() or nxt in "/.-:" or _is_letter(nxt))) and \
                        (L == 3 or (L == 4 and (c.meta.get("brand") == "amex"))):
                    out.append(_Cand("CARD_CVV", m.start(), e, 0.8, "cvv-after-pan", TIER_CONTEXT, ""))
        return out

    def _skip(self, i: int, chars: str) -> int:
        while i < self.n and self.t[i] in chars:
            i += 1
        return i

    # ---------------------------------------------------------------- email
    def emails(self) -> list[_Cand]:
        t = self.t
        if "@" not in t:
            return []
        out = []
        for m in self.rx["EMAIL"].finditer(t):
            a, b = m.span()
            local, _, domain = m.group(0).partition("@")
            stripped = local.lstrip(".-")
            a += len(local) - len(stripped)
            local = stripped
            if not local or len(local) > 64 or local.endswith("."):
                continue
            labels = domain.split(".")
            if any(lb.startswith("-") or lb.endswith("-") for lb in labels):
                continue
            if b < self.n and (_alnum(t[b]) or t[b] in "-_"):
                continue
            if not V.email_tld_ok(labels[-1]):
                continue
            if b + 1 < self.n and t[b] == ":" and t[b + 1] not in " \t\n" and not t[b + 1].isdigit():
                continue  # git@github.com:org/repo (scp-like git remote)
            if self.rx["URL_AUTH_TAIL"].search(t, max(0, a - 200), a):
                continue  # inside scheme://user:pass@host - the password rule handles it
            out.append(_Cand("EMAIL", a, b, 0.9, "email", TIER_CONTEXT,
                             (local + "@" + domain).lower()))
        return out

    # ---------------------------------------------------------------- phone (libphonenumber)
    def phones(self, cands: Sequence[_Cand] = ()) -> list[_Cand]:
        t = self.t
        out: dict[tuple[int, int], _Cand] = {}
        # phones lose every overlap in the merge -> skip windows already claimed by a stronger,
        # above-threshold finding (cards, IBAN/NRB, PESEL, IP, ...). Big win on dense payloads.
        claimed = _Cover((c.a, c.b) for c in cands
                         if c.tier <= TIER_CONTEXT and c.score >= self.d._min_score(c.type))
        regions_cfg = self.cfg.phone_regions
        for pm in self.rx["PHONE_PRE"].finditer(t):
            if claimed.covers(pm.start(), pm.end()) or pm.end() - pm.start() > 40:
                continue  # claimed by a stronger finding, or a digit soup (no phone is > 40 chars)
            wa, wb = max(0, pm.start() - 3), min(self.n, pm.end() + 2)
            win = t[wa:wb]
            head = pm.group(0).lstrip("(")
            if head.startswith("+") or head.startswith("00"):
                regions = regions_cfg[:1]           # international format: region irrelevant
            elif head.startswith("0"):
                regions = tuple(r for r in regions_cfg if r in ("GB", "DE")) or regions_cfg
            else:
                regions = tuple(r for r in regions_cfg if r not in ("GB", "DE")) or regions_cfg
            for region in regions:
                try:
                    matches = list(phonenumbers.PhoneNumberMatcher(
                        win, region, leniency=phonenumbers.Leniency.VALID))
                except Exception:  # pragma: no cover - library edge cases
                    continue
                for m in matches:
                    a, b = wa + m.start, wa + m.end
                    raw = m.raw_string
                    intl = raw.startswith("+") or raw.startswith("00")
                    if region in ("GB", "DE") and not intl and not raw.lstrip("(").startswith("0"):
                        continue  # GB/DE national numbers always carry the trunk '0'
                    if (a, b) in out:
                        continue
                    if intl:
                        score = 0.8
                    elif any(not ch.isdigit() for ch in raw):
                        score = 0.65
                    elif raw.startswith("0") and len(raw) >= 10:
                        score = 0.55  # GB/DE trunk prefix '0' + full national number
                    else:
                        score = 0.4
                    ctx = self.ctx("PHONE", a, b)
                    score += 0.35 if ctx == 1.0 else 0.2 if ctx else 0.0
                    e164 = phonenumbers.format_number(m.number, phonenumbers.PhoneNumberFormat.E164)
                    out[(a, b)] = _Cand("PHONE", a, b, score, f"libphonenumber:{region}",
                                        TIER_WEAK, e164, {"region": region})
                if matches:
                    break
        return list(out.values())

    # ---------------------------------------------------------------- IP / MAC
    def ips(self) -> list[_Cand]:
        t = self.t
        out = []
        if "." in t:
            for m in self.rx["IPV4"].finditer(t):
                a, b = m.span()
                if a > 0 and (_alnum(t[a - 1]) or t[a - 1] == "."):
                    continue
                if b < self.n and (t[b].isdigit() or (t[b] == "." and b + 1 < self.n and t[b + 1].isdigit())):
                    continue
                if self.rx["VERSION_TAIL"].search(t, max(0, a - 16), a):
                    continue
                ok, public = V.ip_info(m.group(0))
                if not ok:
                    continue
                score = 0.85 + 0.1 * self.ctx("IP_ADDRESS", a, b)
                out.append(_Cand("IP_ADDRESS", a, b, score, "ipv4", TIER_CONTEXT, m.group(0),
                                 {"private": not public, "version": 4}))
        if t.count(":") >= 2:
            for m in self.rx["IPV6"].finditer(t):
                a, b = m.span()
                s = m.group(0)
                if s.endswith(":") and not s.endswith("::"):
                    s, b = s[:-1], b - 1
                if s.count(":") < 2 or len(s) < 3:
                    continue
                if a > 0 and (_alnum(t[a - 1]) or t[a - 1] in ":."):
                    continue
                if b < self.n and (_alnum(t[b]) or t[b] == ":"):
                    continue
                ok, public = V.ip_info(s)
                if not ok:
                    continue
                score = 0.85 + 0.1 * self.ctx("IP_ADDRESS", a, b)
                out.append(_Cand("IP_ADDRESS", a, b, score, "ipv6", TIER_CONTEXT,
                                 str(ipaddress.ip_address(s)), {"private": not public, "version": 6}))
        return out

    def macs(self) -> list[_Cand]:
        t = self.t
        out = []
        for key in ("MAC_COLON", "MAC_DASH", "MAC_CISCO"):
            for m in self.rx[key].finditer(t):
                a, b = m.span()
                if a > 0 and (_alnum(t[a - 1]) or t[a - 1] in ":-."):
                    continue
                if b < self.n and (_alnum(t[b]) or (t[b] in ":-." and b + 1 < self.n and _alnum(t[b + 1]))):
                    continue
                hexs = re.sub(r"[^0-9A-Fa-f]", "", m.group(0)).lower()
                if hexs in ("000000000000", "ffffffffffff"):
                    continue
                score = 0.75 + 0.15 * self.ctx("MAC_ADDRESS", a, b)
                out.append(_Cand("MAC_ADDRESS", a, b, score, "mac", TIER_CONTEXT, hexs))
        return out

    # ---------------------------------------------------------------- JWT & secrets
    def jwts(self) -> list[_Cand]:
        t = self.t
        if "eyJ" not in t:
            return []
        out = []
        for m in self.rx["JWT"].finditer(t):
            a = m.start()
            if a > 0 and (_alnum(t[a - 1]) or t[a - 1] in "_-"):
                continue
            tok = m.group(0).rstrip(".")
            parts = tok.split(".")
            if len(parts) not in (3, 5) or any(len(p) < 8 for p in parts[:2]):
                continue
            if V.jwt_ok(".".join(parts[:3])):
                out.append(_Cand("JWT", a, a + len(tok), 0.95, "jwt", TIER_VALIDATED, tok))
        return out

    def secrets(self) -> list[_Cand]:
        t = self.t
        low = self.low if self.low is not None else t.lower()
        out = []
        for rule, rx in self.d.rules:
            if rule.keywords and not any(k in low for k in rule.keywords):
                continue
            for m in rx.finditer(t):
                a, b = m.span(rule.group)
                if a < 0 or b <= a:
                    continue
                v = t[a:b]
                if rule.boundary and ((a > 0 and _alnum(t[a - 1])) or (b < self.n and _alnum(t[b]))):
                    continue
                if _placeholder(v):
                    continue
                if rule.min_entropy and V.shannon_entropy(v) < rule.min_entropy:
                    continue
                if rule.generic and not self._generic_ok(m, v, rule):
                    continue
                if rule.id == "connection-string-password" and v.startswith("$"):
                    continue
                meta = {"rule": rule.id}
                if rule.generic:
                    keyname = t[m.start():m.start(rule.group)].lower()
                    meta["password"] = any(k in keyname for k in ("pass", "pwd", "hasło", "haslo"))
                out.append(_Cand(rule.type, a, b, rule.score, rule.id, rule.tier, v, meta))
        return out

    def _generic_ok(self, m: re.Match, v: str, rule: SecretRule) -> bool:
        t = self.t
        s0 = m.start()
        if rule.id in ("generic-credential", "password-label", "password-inline") and s0 > 0 \
                and _is_letter(t[s0 - 1]):
            return False  # 'monkey: ...' / 'turkey=...'
        if rule.id == "password-inline":
            # no ':'/'=' -> value must look like a real password: 3 of 4 char classes
            classes = sum((any(c.islower() for c in v), any(c.isupper() for c in v),
                           any(c.isdigit() for c in v), any(not c.isalnum() for c in v)))
            if classes < 3:
                return False
        if "://" in v or "@" in v or v.startswith(("/", "./", "~/", "$", "%")):
            return False
        if v.isdigit() or _IDENT_DOTTED.fullmatch(v) or _SNAKE_WORDS.fullmatch(v):
            return False
        if v.replace(".", "").replace("-", "").isdigit():
            return False
        keyname = t[s0:m.start(rule.group)].lower()
        is_pw = any(k in keyname for k in ("pass", "pwd", "hasło", "haslo"))
        if rule.id == "generic-credential" and not is_pw:
            # keys/tokens: must look random (digits + letters, or long high-entropy)
            if len(v) < 12:
                return False
            if not (any(c.isdigit() for c in v) and any(c.isalpha() for c in v)) and V.shannon_entropy(v) < 4.0:
                return False
        if is_pw and v.isalpha() and v.islower() and len(v) < 12:
            return False  # dictionary-word "passwords" in docs (e.g. 'password: required')
        return True

    def url_secrets(self) -> list[_Cand]:
        t = self.t
        if "=" not in t:
            return []
        out = []
        for m in self.rx["URL_SECRET"].finditer(t):
            a, b = m.span(2)
            v = m.group(2)
            if _placeholder(v):
                continue
            out.append(_Cand("URL_SECRET", a, b, 0.85, "url-param:" + m.group(1).lower(),
                             TIER_CONTEXT, v))
        return out

    def cookies(self) -> list[_Cand]:
        t = self.t
        if "ookie" not in t and "OOKIE" not in t:
            return []
        out = []
        name_rx = self.rx["COOKIE_NAME"]
        for lm in self.rx["COOKIE_LINE"].finditer(t):
            for pm in self.rx["COOKIE_PAIR"].finditer(t, lm.start(1), lm.end(1)):
                if not name_rx.fullmatch(pm.group(1)):
                    continue
                v = pm.group(2)
                if len(v) < 12 or _placeholder(v):
                    continue
                a, b = pm.span(2)
                out.append(_Cand("SECRET", a, b, 0.85, "cookie:" + pm.group(1), TIER_CONTEXT, v,
                                 {"rule": "cookie-session"}))
        return out

    def private_keys(self) -> list[_Cand]:
        """PEM private-key blocks. BEGIN/END markers are paired in code (linear): each BEGIN takes
        the first END before the next BEGIN; otherwise a truncated key (BEGIN + base64 body)."""
        t = self.t
        if "PRIVATE KEY" not in t:
            return []
        begins = [m.span() for m in self.rx["PK_BEGIN"].finditer(t)]
        ends = [m.span() for m in self.rx["PK_END"].finditer(t)]
        end_starts = [a for a, _ in ends]
        out = []
        for idx, (ba, bb) in enumerate(begins):
            limit = begins[idx + 1][0] if idx + 1 < len(begins) else self.n
            k = bisect.bisect_left(end_starts, bb)
            if k < len(ends) and ends[k][0] < limit:
                out.append(_Cand("PRIVATE_KEY", ba, ends[k][1], 1.0, "pem-block", TIER_STRUCTURAL))
                continue
            tm = self.rx["PK_TRUNC"].match(t, ba)
            if tm:
                out.append(_Cand("PRIVATE_KEY", ba, tm.end(), 1.0, "pem-truncated", TIER_STRUCTURAL))
        return out

    # ---------------------------------------------------------------- crypto
    def crypto(self) -> list[_Cand]:
        t = self.t
        out = []
        for key in ("BTC_B58", "BTC_BECH32"):
            for m in self.rx[key].finditer(t):
                a, b = m.span()
                if (a > 0 and _alnum(t[a - 1])) or (b < self.n and _alnum(t[b])):
                    continue
                s = m.group(0)
                ok = V.btc_base58_ok(s) if key == "BTC_B58" else V.segwit_ok(s)
                if ok:
                    score = 0.9 + 0.05 * self.ctx("CRYPTO_BTC", a, b)
                    out.append(_Cand("CRYPTO_BTC", a, b, score,
                                     "base58check" if key == "BTC_B58" else "bech32",
                                     TIER_VALIDATED, s))
        if "0x" in t or "0X" in t:
            for m in self.rx["ETH"].finditer(t):
                a, b = m.span()
                if (a > 0 and _alnum(t[a - 1])) or (b < self.n and _alnum(t[b])):
                    continue
                state = V.eth_checksum_state(m.group(0))
                if state == "invalid":
                    continue
                if state == "valid":
                    out.append(_Cand("CRYPTO_ETH", a, b, 0.9 + 0.05 * self.ctx("CRYPTO_ETH", a, b),
                                     "eip55", TIER_VALIDATED, m.group(0).lower()))
                else:
                    ctx = self.ctx("CRYPTO_ETH", a, b)
                    score = 0.45 + (0.35 if ctx == 1.0 else 0.2 if ctx else 0.0)
                    out.append(_Cand("CRYPTO_ETH", a, b, score, "eth-hex+ctx", TIER_WEAK,
                                     m.group(0).lower()))
        return out

    # ---------------------------------------------------------------- misc
    def path_users(self) -> list[_Cand]:
        t = self.t
        if "Users" not in t and "/home/" not in t and "users" not in t.lower():
            return []
        out = []
        for m in self.rx["PATH_USER"].finditer(t):
            a, b = m.span(1)
            u = m.group(1)
            if u.lower() in self.cfg.path_user_allow or u.startswith(("$", "%", "<", "{")):
                continue
            out.append(_Cand("PATH_USERNAME", a, b, 0.9, "path-username", TIER_CONTEXT, u))
        return out

    def dob(self) -> list[_Cand]:
        t = self.t
        out = []
        for m in self.rx["DOB_TRIGGER"].finditer(t):
            s0 = m.start()
            if s0 > 0 and _is_letter(t[s0 - 1]):
                continue
            if m.end() < self.n and _is_letter(t[m.end()]) and not m.group(0).endswith("."):
                continue
            hi = min(self.n, m.end() + 30)
            best = None
            for key in ("DATE_ISO", "DATE_DMY", "DATE_WORDS_PL", "DATE_WORDS_EN"):
                dm = self.rx[key].search(t, m.end(), hi)
                if dm and (best is None or dm.start() < best.start()):
                    best = dm
            if best is None:
                continue
            if best.start() > 0 and t[best.start() - 1].isdigit():
                continue
            if best.end() < self.n and t[best.end()].isdigit():
                continue
            if not self._date_valid(best.group(0)):
                continue
            out.append(_Cand("DATE_OF_BIRTH", best.start(), best.end(), 0.85, "dob-ctx",
                             TIER_CONTEXT, best.group(0)))
        return out

    _MONTHS = {"sty": 1, "lut": 2, "mar": 3, "kwi": 4, "maj": 5, "cze": 6, "lip": 7, "sie": 8,
               "wrz": 9, "paź": 10, "paz": 10, "lis": 11, "gru": 12, "jan": 1, "feb": 2, "apr": 4,
               "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

    def _date_valid(self, s: str) -> bool:
        nums = [int(x) for x in re.findall(r"[0-9]+", s)]
        words = re.findall(r"[A-Za-ząćęłńóśźż]+", s)
        if words:
            mon = self._MONTHS.get(words[0][:3].lower())
            if mon is None or len(nums) < 2:
                return False
            day, year = (nums[0], nums[-1]) if nums[0] <= 31 else (nums[-2], nums[-1])
            return V.date_ok(year, mon, day)
        if len(nums) != 3:
            return False
        if nums[0] > 31:  # ISO
            return V.date_ok(nums[0], nums[1], nums[2])
        return V.date_ok(nums[2], nums[1], nums[0]) or V.date_ok(nums[2], nums[0], nums[1])

    def user_patterns(self) -> list[_Cand]:
        out = []
        if self.d.deny_rx is not None:
            for m in self.d.deny_rx.finditer(self.t):
                if m.end() > m.start():
                    out.append(_Cand("DENY_TERM", m.start(), m.end(), 0.9, "deny-term",
                                     TIER_CONTEXT, m.group(0).lower()))
        for etype, rx, score in self.d.custom:
            for m in rx.finditer(self.t):
                if m.end() > m.start():
                    out.append(_Cand(etype, m.start(), m.end(), score, "custom", TIER_CONTEXT))
        return out

    # ---------------------------------------------------------------- decode-and-rescan (A9)
    def decoded(self, cands: list[_Cand], depth: int) -> list[_Cand]:
        t = self.t
        out = []
        budget = self.cfg.decode_max_bytes
        strong = [(c.a, c.b) for c in cands if c.tier <= TIER_VALIDATED]
        alpha_b64 = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/_-")
        hexchars = set("0123456789abcdefABCDEF")
        for key in ("B64", "HEX"):
            for m in self.rx[key].finditer(t):
                a, b = m.span()
                if budget <= 0:
                    return out
                chars = alpha_b64 if key == "B64" else hexchars
                if (a > 0 and t[a - 1] in chars) or (b < self.n and t[b] in chars):
                    continue
                if any(sa <= a and b <= sb for sa, sb in strong):
                    continue
                s = m.group(0)
                raw = self._try_decode(s, key)
                if raw is None:
                    continue
                budget -= len(raw)
                inner = self.d._detect_inner(raw, depth + 1)
                if not inner:
                    continue
                best = min(inner, key=lambda c: (c.tier, -c.score))
                out.append(_Cand(best.type, a, b, best.score * 0.98,
                                 ("b64>" if key == "B64" else "hex>") + best.detector, best.tier,
                                 best.canonical, {"encoding": key.lower(),
                                                  "inner_types": sorted({c.type for c in inner})}))
        return out

    @staticmethod
    def _try_decode(s: str, key: str) -> str | None:
        try:
            if key == "HEX":
                if len(s) % 2:
                    return None
                data = bytes.fromhex(s)
            else:
                body = s.rstrip("=")
                if len(body) % 4 == 1:
                    return None
                pad = body + "=" * (-len(body) % 4)
                if "-" in body or "_" in body:
                    data = base64.urlsafe_b64decode(pad)
                else:
                    data = base64.b64decode(pad, validate=True)
            txt = data.decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            return None
        if len(txt) < 6:
            return None
        printable = sum(ch.isprintable() or ch in "\n\r\t" for ch in txt)
        return txt if printable / len(txt) >= 0.9 else None

    # ---------------------------------------------------------------- JSON cross-field (A8)
    def json_fragments(self, cands: list[_Cand]) -> list[_Cand]:
        t = self.t
        if t.count('"') < 4:
            return []
        leaves = []
        for m in self.rx["JSON_STR"].finditer(t):
            j = m.end()
            while j < self.n and t[j] in " \t\r\n":
                j += 1
            if j < self.n and t[j] == ":":
                continue  # object key
            a, b = m.span(1)
            if any(_alnum(ch) for ch in t[a:b]):
                leaves.append((0, a, b, t))
        if len(leaves) < 2:
            return []
        joined, owner = Detector._join(leaves)
        out = []
        for c in self.d._cross_candidates(joined):
            for (_, a, b) in Detector._split(owner, c.a, c.b):
                if any(not (b <= x.a or a >= x.b) for x in cands if x.tier <= TIER_VALIDATED):
                    continue
                out.append(_Cand(c.type, a, b, c.score - 0.05, "json-join>" + c.detector, c.tier,
                                 c.canonical, {"fragment": True}))
        return out


# ============================================================================ module-level API

_DEFAULT: Detector | None = None


def default_detector() -> Detector:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Detector()
    return _DEFAULT


def detect(text: str) -> list[Finding]:
    return default_detector().detect(text)


def analyze(text: str) -> list[Finding]:
    return default_detector().analyze(text)


def entity_catalog() -> list[dict]:
    """For GET /api/redaction/entities: [{entity, data_class, category, detectors: [...]}]."""
    det: dict[str, set[str]] = {}
    for t, e in CONTRACT_ENTITY.items():
        det.setdefault(e, set()).add(t.lower())
    for r in SECRET_RULES:
        det.setdefault(SECRET_RULE_ENTITY.get(r.id, "GENERIC_SECRET"), set()).add(r.id)
    det.setdefault("PASSWORD", set()).add("generic-credential(password key)")
    return [{"entity": e, "data_class": DATA_CLASS.get(e, "CONFIDENTIAL"),
             "category": CATEGORY.get(DATA_CLASS.get(e, "CONFIDENTIAL"), "pii"),
             "detectors": sorted(d)} for e, d in sorted(det.items())]


def builtin_patterns() -> dict[str, str]:
    """All built-in regex strings (for the RE2-portability test and the Go port)."""
    d = dict(P)
    d.update({f"rule:{r.id}": r.pattern for r in SECRET_RULES})
    return d
