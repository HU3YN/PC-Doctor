"""Find earlier work-log entries that look like the problem in front of you.

This is deliberately simple and explainable: every match comes with the
reasons it matched ("same stop code 0x124", "same part: rtx 3070"). A work
log is hundreds of entries, not millions, so scoring every entry in Python
is instant and needs no search server.

    shared error code      strongest signal - the same stop code or event
    same fault category    thermal, power, memory, ...
    shared parts           tokens from the components and device fields
    shared words           weighted so rare words count more than common ones
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from pcdoctor_analysis.model import CATEGORIES
from pcdoctor_analysis.stopcodes import STOP_CODES, extract_codes, format_code

from ..models import WorkLogEntry

WEIGHT_CODE = 6.0
WEIGHT_CODE_MAX = 12.0
WEIGHT_CATEGORY = 3.0
WEIGHT_PART = 1.5
WEIGHT_PART_MAX = 4.5
WEIGHT_TEXT = 5.0
MIN_SCORE = 1.5

_WORD = re.compile(r"[a-z0-9][a-z0-9+#.\-]*")
_HEX_CODE = re.compile(r"^0[xX][0-9A-Fa-f]{1,8}$")

# Words too common in repair notes to say anything about a match.
STOP_WORDS = frozenset(
    """
    the and for with was were are but not has had have from this that then than when
    after before while into onto out off over under again still also just very only
    pc computer system machine customer client user issue problem problems fault
    tested test testing check checked checking found replaced replace fixed fix works
    working worked new old one two all any can could would should did does doing done
    get got its it's his her their our you your they them was been being will there
    here what which who how why because during about some more most other same
    itself keep keeps always sometimes every time times lot bit really until
    """.split()
)


# Different words technicians and customers use for the same thing, as stems.
# Each group is folded to its first word.
_SYNONYM_GROUPS = [
    ("restart", "reboot", "reset"),
    ("shut", "shutdown", "poweroff"),
    ("freez", "hang", "hung", "lockup", "unresponsiv"),
    ("stutter", "hitch", "lag", "jitter", "judder", "choppy"),
    ("hot", "overheat", "heat", "thermal"),
    ("bsod", "bluescreen", "bugcheck"),
    ("artifact", "artefact", "glitch"),
    ("slow", "sluggish"),
    ("nois", "loud"),
    ("black", "blank"),
]
SYNONYMS = {word: group[0] for group in _SYNONYM_GROUPS for word in group[1:]}
_PHRASES = [
    (re.compile(r"\bblue[\s-]?screens?(?: of death)?\b"), "bsod"),
    (
        re.compile(
            r"\b(?:shuts?|shutting|turns?|turning|powers?|powering|cuts?|cutting)[\s-](?:off|down|out)\b"
        ),
        "shutdown",
    ),
    (re.compile(r"\block(?:s|ed|ing)?[\s-]up\b"), "lockup"),
    (re.compile(r"\bno[\s-](?:display|signal|video|picture)\b"), "nodisplay"),
    (
        re.compile(
            r"\b(?:won'?t|will not|doesn'?t|does not|not) (?:boot|post|start|turn on|power on)\b"
        ),
        "noboot",
    ),
]


def normalize_code(code: str) -> str:
    """'0x00000124' -> '0x124'; anything else just has its spacing tidied.

    Other codes ("Kernel-Power-41", "POST 55", "Q-LED DRAM") keep the casing
    they were written with; they are compared without regard to case.
    """
    text = code.strip()
    if _HEX_CODE.match(text):
        return format_code(int(text, 16))
    return re.sub(r"\s+", " ", text)


def code_key(code: str) -> str:
    """What two codes are compared by."""
    return normalize_code(code).upper()


def normalize_codes(codes: Iterable[str]) -> list[str]:
    seen: dict[str, str] = {}
    for code in codes:
        if not isinstance(code, str) or not code.strip():
            continue
        seen.setdefault(code_key(code), normalize_code(code))
    return list(seen.values())


def stem(word: str) -> str:
    """Fold a word to a rough stem so different endings still match.

    "stuttering", "stutters" and "stutter" all become "stutter"; "freezes"
    and "freezing" both become "freez". Crude on purpose - it only has to be
    consistent, and the original words are what the user is shown.
    """
    if len(word) > 5 and word.endswith("ly"):
        word = word[:-2]  # "randomly" -> "random"
    if len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 4 and word.endswith("ed"):
        word = word[:-2]
    elif len(word) > 4 and word.endswith("es") and word[-3] in "sxh":
        word = word[:-2]
    elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if len(word) > 3 and word[-1] == word[-2] and word[-1] not in "aeiousl":
        word = word[:-1]  # "runn" -> "run"
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]  # "freeze" -> "freez", to meet "freezing"
    return SYNONYMS.get(word, word)


def stems(text: str) -> dict[str, str]:
    """Stem -> the word as written, for every meaningful word in the text."""
    found: dict[str, str] = {}
    lowered = (text or "").lower()
    for pattern, replacement in _PHRASES:
        lowered = pattern.sub(f" {replacement} ", lowered)
    for raw in _WORD.findall(lowered):
        word = raw.strip(".-")
        if word in STOP_WORDS or len(word) < 2 or (len(word) < 3 and not word.isdigit()):
            continue
        # Model numbers and codes are kept exactly; only plain words are stemmed.
        key = stem(word) if word.isalpha() else word
        if key not in STOP_WORDS:
            found.setdefault(key, word)
    return found


def tokenize(text: str) -> list[str]:
    return list(stems(text))


def part_tokens(values: Iterable[str]) -> set[str]:
    """Tokens that identify hardware: model numbers and names, not filler."""
    filler = {
        stem(word)
        for word in (
            "intel amd nvidia geforce radeon core processor graphics with gaming series build "
            "desktop laptop inc ltd corp rtx gtx ryzen ddr3 ddr4 ddr5 super ssd hdd psu inch"
        ).split()
    }
    out: set[str] = set()
    for value in values:
        for token in tokenize(value or ""):
            if token in filler or token.endswith("-core"):
                continue
            # A bare number only identifies a part when it is a model number.
            if token.isdigit() and len(token) < 3:
                continue
            out.add(token)
    return out


@dataclass
class Query:
    text: str = ""
    codes: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)  # CPU / GPU / board names


@dataclass
class Match:
    entry: WorkLogEntry
    score: float
    reasons: list[str]


def entry_codes(entry: WorkLogEntry) -> set[str]:
    """Comparison keys of the codes on the entry, plus any 0x... codes in its text."""
    codes = {code_key(c) for c in normalize_codes(entry.error_codes or [])}
    for text in (entry.title, entry.symptoms, entry.root_cause, entry.steps):
        codes.update(code_key(c) for c in extract_codes(text or ""))
    return codes


def entry_text_tokens(entry: WorkLogEntry) -> list[str]:
    return tokenize(
        " ".join(
            [
                entry.title or "",
                entry.symptoms or "",
                entry.root_cause or "",
                entry.fix or "",
                entry.steps or "",
            ]
        )
    )


def entry_part_tokens(entry: WorkLogEntry) -> set[str]:
    return part_tokens([*(entry.components or []), entry.device or ""])


def _describe_code(code: str) -> str:
    if _HEX_CODE.match(code):
        known = STOP_CODES.get(int(code, 16))
        if known:
            return f"Same stop code {code} ({known.name})"
        return f"Same stop code {code}"
    return f"Same code {code}"


def find_similar(
    entries: list[WorkLogEntry],
    query: Query,
    *,
    limit: int = 5,
    exclude_id: int | None = None,
) -> list[Match]:
    candidates = [e for e in entries if e.id != exclude_id]
    if not candidates:
        return []

    # comparison key -> the code as it should be shown
    query_codes = {
        code_key(c): c for c in [*normalize_codes(query.codes), *extract_codes(query.text)]
    }
    query_parts = part_tokens(query.parts)
    query_words = stems(query.text)  # stem -> the word the user wrote
    query_tokens = set(query_words)
    query_categories = {c for c in query.categories if c in CATEGORIES}

    # Inverse document frequency over the log: a word that appears in every
    # entry ("restart") says less than one that appears in two ("artifacts").
    tokens_by_entry = {e.id: set(entry_text_tokens(e)) for e in candidates}
    document_frequency: Counter[str] = Counter()
    for tokens in tokens_by_entry.values():
        document_frequency.update(tokens)
    total = len(candidates)

    def idf(token: str) -> float:
        return math.log((total + 1) / (document_frequency.get(token, 0) + 1)) + 1.0

    query_weight = sum(idf(t) for t in query_tokens)

    matches: list[Match] = []
    for entry in candidates:
        score = 0.0
        reasons: list[str] = []

        shared_codes = sorted(set(query_codes) & entry_codes(entry))
        if shared_codes:
            score += min(WEIGHT_CODE_MAX, WEIGHT_CODE * len(shared_codes))
            reasons.extend(_describe_code(query_codes[key]) for key in shared_codes[:3])

        if entry.category in query_categories and entry.category not in ("other", "no_fault_found"):
            score += WEIGHT_CATEGORY
            reasons.append(f"Same kind of fault: {CATEGORIES[entry.category]}")

        shared_parts = sorted(query_parts & entry_part_tokens(entry))
        if shared_parts:
            score += min(WEIGHT_PART_MAX, WEIGHT_PART * len(shared_parts))
            reasons.append("Same parts: " + ", ".join(shared_parts[:4]))

        shared_words = query_tokens & tokens_by_entry[entry.id]
        if shared_words and query_weight > 0:
            share = sum(idf(t) for t in shared_words) / query_weight
            # One shared word is weak evidence however rare it is.
            score += WEIGHT_TEXT * share * min(1.0, (len(shared_words) + 1) / 3)
            best = sorted(shared_words, key=lambda t: (-idf(t), t))[:5]
            reasons.append("Matching words: " + ", ".join(query_words[t] for t in best))

        if score >= MIN_SCORE and reasons:
            matches.append(Match(entry, round(score, 2), reasons))

    # Best score first; between equals, a solved case beats an open one and a
    # recent one beats an old one.
    matches.sort(
        key=lambda m: (-m.score, m.entry.status != "fixed", -m.entry.occurred_on.toordinal())
    )
    return matches[:limit]
