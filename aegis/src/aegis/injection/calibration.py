"""INJ-02 domain calibration for trusted prompts (CAL).

The ONNX injection classifier (Horizon PI-small) over-triggers on short imperative finance
language ("Unwind the hedge and report the realized PnL" scores 0.98) and on security
meta-discussion that *quotes* an attack phrase ("write a rule that detects the phrase '…'").
Both are normal requests from a bank's own staff.

This module never allows anything by itself. For a **trusted** unit whose classifier score
reached the act band, it may *demote* the verdict to the review band, where the guard model
(Qwen3Guard) decides, and where ``review_fallback.trusted`` applies if the guard is unavailable.
A demotion needs ALL of:

* no lexical injection evidence: the local signature score and the engine heuristic are both
  ``<= max_cue_score`` (rule ``domain``), or every signature hit is a quoted *mention* inside a
  meta-discussion request (rule ``mention``);
* the best-scoring candidate is the plain text (not a decoded base64/hex layer or hidden span);
* the text is short (``<= max_chars``) and contains no agent-targeting cue (instructions,
  system prompt, rules, assistant/AI/model, secrecy, credentials, URLs, mass data export …);
* rule ``domain`` only: at least one finance-domain term (order, hedge, PnL, portfolio, client …).

``finance_benign`` serves INJ-03 the same way: a guard "Non-violent Illegal Acts" verdict on a
short finance-operational prompt ("Cancel all open orders before the ECB announcement") is
logged instead of blocked unless a financial-crime cue (laundering, insider, spoofing, fraud …)
is present.

Lexicons are deliberately small and auditable; extend them in policy via
``params.calibration.domain_terms`` / ``target_cues`` (extra regex alternatives).
"""

from __future__ import annotations

import re
from functools import lru_cache

DOMAIN_TERMS = (
    # EN finance / trading / client-service vocabulary
    r"orders?",
    r"fills?",
    r"positions?",
    r"hedges?",
    r"p&l|pnl|p/l",
    r"var",
    r"portfolios?",
    r"clients?",
    r"dividends?",
    r"earnings",
    r"trades?|trading",
    r"shares?",
    r"stocks?",
    r"bonds?",
    r"equit(?:y|ies)",
    r"liquidate|unwind|rebalance",
    r"settlement|t\+[0-3]",
    r"benchmark",
    r"yields?|coupons?",
    r"fx|eur/pln|usd/pln",
    r"market[- ](?:open|close)|market-on-close|stop[- ]loss|limit order",
    r"desk",
    r"exposure",
    r"payouts?|reinvest(?:ment)?",
    r"brokers?|tickers?|ipo|nav|vwap|twap|bps|basis points",
    r"margin|collateral|notional",
    r"q[1-4]|quarter(?:ly)?",
    r"invoices?|refunds?|payments?",
    # PL
    r"zleceni\w*",
    r"pozycj\w*",
    r"portfel\w*",
    r"klient\w*",
    r"dywidend\w*",
    r"akcj[ai]\w*",
    r"obligacj\w*",
    r"sesj\w*",
    r"notowa\w*",
    r"kwarta\w*",
)

TARGET_CUES = (
    # the agent itself / its instructions
    r"instruct\w*",
    r"prompts?",
    r"system",
    r"rules?",
    r"guidelines?",
    r"polic(?:y|ies)",
    r"restrict\w*",
    r"filters?",
    r"safety|safe mode|guardrails?",
    r"assistant",
    r"ai|llm|model|chatbot|gpt|claude",
    r"jailbreak\w*|developer mode|dan",
    r"persona|role-?play|pretend|character",
    r"obey\w*|comply with me",
    r"reveal|verbatim|confidential configuration",
    # secrecy toward the user / operator
    r"do not (?:tell|mention|inform|log)|don't (?:tell|mention|inform|log)|hide|secret\w*",
    # credentials and exfil channels
    r"passwords?|credentials?|api[ _-]?keys?|tokens?|ssh|id_rsa",
    r"webhook|curl|wget|base64|encode",
    r"e-?mail address\w*|every customer|all (?:customers|users|clients|records)",
    # PL
    r"instrukcj\w*|polecen\w*|zasad\w*|regu\w*|asystent\w*|model\w*|has\w*o",
    r"nie (?:m[oó]w|informuj)",
)


#: Financial-crime intent: a guard "Non-violent Illegal Acts" verdict on finance language is only
#: calibrated (logged instead of blocked) when NONE of these appear.
HARM_CUES = (
    r"launder\w*|money mules?|structuring|smurf\w*|layering",
    r"insider|inside information|mnpi|non-?public|before [\w\s]{0,30}?(?:is|goes|becomes|are) (?:public|announced)|tip(?:ped|s)? (?:me |us |him |her )?off",
    r"front-?run\w*|spoof\w*|wash[- ]trad\w*|pump[- ]and[- ]dump|manipulat\w*|ramp(?:ing)? the price",
    r"evad\w*|evasion|avoid (?:aml|kyc|reporting|detection|tax)|sanction\w*|offshore shell",
    r"fraud\w*|scam\w*|phish\w*|steal\w*|stolen|embezzl\w*|forg(?:e|ed|ery)|fake|counterfeit|brib\w*",
    r"kickbacks?|ponzi|skim\w*|hack\w*|without (?:the )?(?:client'?s? )?(?:consent|knowledge|authori[sz]ation)",
    r"pran\w* pieni\w*|wy\u0142udz\w*|oszust\w*|manipulac\w*|kradzie\w*|\u0142ap\u00f3wk\w*|podrob\w*",
)


@lru_cache(maxsize=16)
def _rx(alts: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"(?<![\w])(?:" + "|".join(alts) + r")(?![\w])", re.IGNORECASE)


def domain_hits(text: str, extra: tuple[str, ...] = ()) -> int:
    return len(_rx(DOMAIN_TERMS + extra).findall(text))


_CHANNEL = re.compile(r"https?://|www\.|\.env\b|[\w.+-]+@[\w-]+\.\w", re.IGNORECASE)


def has_target_cue(text: str, extra: tuple[str, ...] = ()) -> bool:
    return _CHANNEL.search(text) is not None or _rx(TARGET_CUES + extra).search(text) is not None


def finance_benign(text: str, *, max_chars: int = 400, domain_terms: tuple[str, ...] = (),
                   harm_cues: tuple[str, ...] = ()) -> bool:
    """Short finance-operational prompt with no agent-targeting and no financial-crime cue."""
    if len(text) > max_chars or domain_hits(text, domain_terms) < 1:
        return False
    if has_target_cue(text):
        return False
    return _rx(HARM_CUES + harm_cues).search(text) is None


def demotion_rule(
    text: str,
    *,
    candidate: str,
    sig_score: float,
    sig_all_mentioned: bool,
    heur_score: float,
    max_cue_score: float = 0.0,
    max_chars: int = 400,
    mention: bool = True,
    domain: bool = True,
    domain_terms: tuple[str, ...] = (),
    target_cues: tuple[str, ...] = (),
) -> str | None:
    """'domain' | 'mention' when an act-band classifier verdict may go to guard review, else None."""
    if candidate != "text" or len(text) > max_chars:
        return None
    if mention and sig_all_mentioned:
        return "mention"
    if not domain or sig_score > max_cue_score or heur_score > max_cue_score:
        return None
    if has_target_cue(text, target_cues):
        return None
    if domain_hits(text, domain_terms) < 1:
        return None
    return "domain"


__all__ = ["DOMAIN_TERMS", "HARM_CUES", "TARGET_CUES", "demotion_rule", "domain_hits", "finance_benign",
           "has_target_cue"]
