# Centralized applicability helpers for WCAG criteria
from typing import Dict, Iterable, Sequence, Any

DEFAULT_APPLICABLE_KEYS = ("applicable",)


def mark_na(details: Dict[str, Any], note_suffix: str = "") -> None:
    """Mutates details to represent a Not Applicable condition.
    - Sets details['na']=True
    - Nulls ratio hints (ok_ratio, ratio) if they equal 1 (avoid misleading PASS look)
    - Appends explanatory note.
    """
    details["na"] = True
    if details.get("ok_ratio") is not None:
        details["ok_ratio"] = None
    if note_suffix:
        details["note"] = (details.get("note", "") + f" | NA: {note_suffix}").strip()
    else:
        details["note"] = (details.get("note", "") + " | NA").strip()


def ensure_na_if_no_applicable(details: Dict[str, Any], applicable_keys: Sequence[str] = DEFAULT_APPLICABLE_KEYS,
                               note_suffix: str = "sin elementos aplicables detectados") -> bool:
    """Checks the sum of given applicable keys; if zero => mark NA and return True."""
    total = 0
    for k in applicable_keys:
        v = details.get(k)
        try:
            total += int(v or 0)
        except Exception:
            pass
    if total == 0:
        mark_na(details, note_suffix=note_suffix)
        return True
    return False


def normalize_pass_for_applicable(details: Dict[str, Any], violations_key: str = "violations",
                                  applicable_keys: Sequence[str] = DEFAULT_APPLICABLE_KEYS) -> bool:
    """Returns a boolean 'passed' taking into account NA state and violations.
    Logic:
      - If details['na'] True => passed False (we don't award PASS for no scope)
      - Else if violations == 0 => True else False.
    """
    if details.get("na") is True:
        return False
    violations = int(details.get(violations_key, 0) or 0)
    return violations == 0
