# audits/checks/criteria/p3/c_3_1_4_abbreviations.py
from typing import Dict, Any, List, Optional, Tuple, Set
import re
import unicodedata

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "3.1.4"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

ABBR_TAG_RE = re.compile(r"^[A-ZÁÉÍÓÚÜÑ][A-Z0-9ÁÉÍÓÚÜÑ\.]{1,5}$", re.UNICODE)
ABBR_INLINE_RE = re.compile(r"\b([A-ZÁÉÍÓÚÜÑ]{2,6}(?:\.[A-ZÁÉÍÓÚÜÑ]{1,5})?)\b", re.UNICODE)

def _as_list(x):
    if not x:
        return []
    if isinstance(x, list):
        return x
    return list(x)

def _s(v: Any) -> str:
    return "" if v is None else str(v)

def _get_attr(node: Any, name: str) -> Optional[str]:
    try:
        if isinstance(node, dict):
            val = node.get(name)
            return _s(val) if val is not None else None
        if hasattr(node, "get"):
            val = node.get(name)  # type: ignore[attr-defined]
            return _s(val) if val is not None else None
    except Exception:
        pass
    return None

def _page_text(ctx: PageContext) -> str:
    soup = getattr(ctx, "soup", None)
    if soup is not None:
        try:
            return (soup.get_text() or "")  # type: ignore[attr-defined]
        except Exception:
            pass
    return _s(getattr(ctx, "document_text", "") or "")

def _canon_text(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "")

def _has_global_glossary(soup) -> bool:
    if soup is None:
        return False
    try:
        link = soup.find("a", string=re.compile(r"\b(glosario|glossary|abreviaturas|ac[ró]nimos|acr[oó]nimos)\b", re.I))
        if link:
            return True
        sec = soup.find(id=re.compile(r"glossary|glosario|abbrev|acron", re.I)) or soup.find(class_=re.compile(r"glossary|glosario|abbrev|acron", re.I))
        return bool(sec)
    except Exception:
        return False

def _find_inline_expansions(text: str) -> Dict[str, str]:
    """
    Busca patrones 'HTML (Hypertext ...)' y 'Hypertext ... (HTML)' para mapear abreviación <-> expansión.
    """
    expansions: Dict[str, str] = {}
    t = _canon_text(text)
    # CASE A: ABBR (Expansion)
    for m in re.finditer(r"\b([A-ZÁÉÍÓÚÜÑ]{2,6})\b\s*\(([^)]+)\)", t):
        ab = m.group(1).strip()
        exp = m.group(2).strip()
        if 2 <= len(ab) <= 6:
            expansions[ab] = exp[:140]
    # CASE B: Expansion (ABBR)
    for m in re.finditer(r"\b([A-Za-zÁÉÍÓÚÜÑ][^()]{6,80}?)\s*\(\s*([A-ZÁÉÍÓÚÜÑ]{2,6})\s*\)", t):
        ab = m.group(2).strip()
        exp = m.group(1).strip()
        if 2 <= len(ab) <= 6 and len(exp) >= 6:
            expansions[ab] = exp[:140]
    return expansions

def _abbrs_from_tags(soup) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if soup is None:
        return out
    try:
        for ab in soup.find_all("abbr"):
            txt = _s(getattr(ab, "get_text", lambda: "")()).strip()  # type: ignore[misc]
            title = _get_attr(ab, "title") or _get_attr(ab, "aria-label")
            describedby = _get_attr(ab, "aria-describedby")
            out.append({"abbr": txt, "has_title": bool(title and title.strip()), "aria_describedby": describedby})
    except Exception:
        pass
    return out

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    3.1.4 (AAA): Debe existir un mecanismo para identificar el significado o forma expandida de abreviaturas.
    RAW:
      - Considera válidos: <abbr title="...">, aria-label/aria-describedby con expansión, o explicación en la primera aparición
        'ABBR (Expansión)' / 'Expansión (ABBR)', o un glosario global.
      - Marca abreviaturas en mayúsculas (2–6) detectadas en el texto si no se explican.
    """
    soup = getattr(ctx, "soup", None)
    text = _page_text(ctx)
    has_glossary = _has_global_glossary(soup)

    # a) <abbr> tags
    tag_items = _abbrs_from_tags(soup)
    abbr_explained: Set[str] = set()
    abbr_seen: Set[str] = set()
    offenders: List[Dict[str, Any]] = []

    for it in tag_items:
        ab = _s(it.get("abbr"))
        if not ab or not ABBR_TAG_RE.match(ab):
            continue
        abbr_seen.add(ab)
        if bool(it.get("has_title")) or _s(it.get("aria_describedby")).strip():
            abbr_explained.add(ab)

    # b) Expansiones inline en el texto
    inline_map = _find_inline_expansions(text)
    for ab, exp in inline_map.items():
        abbr_seen.add(ab)
        abbr_explained.add(ab)

    # c) Abreviaturas adicionales detectadas en texto (no solo <abbr>)
    for m in ABBR_INLINE_RE.finditer(text):
        ab = m.group(1).strip(".")
        if 2 <= len(ab) <= 6:
            abbr_seen.add(ab)

    # Resultado
    applicable = 1 if len(abbr_seen) > 0 or has_glossary else 0

    missing = 0
    if not has_glossary:
        for ab in sorted(abbr_seen):
            if ab not in abbr_explained:
                missing += 1
                offenders.append({"abbr": ab, "reason": "Abreviatura sin título/expansión/glosario detectado."})

    violations = 0 if (applicable == 0 or has_glossary or missing == 0) else missing
    explained = len(abbr_explained)
    total = len(abbr_seen)
    ok_ratio = 1.0 if applicable == 0 else (1.0 if violations == 0 else (explained / max(1, total)))

    details: Dict[str, Any] = {
        "applicable": applicable,
        "abbreviations_total": total,
        "explained": explained,
        "missing": missing,
        "has_global_glossary": has_glossary,
        "ok_ratio": round(ok_ratio, 4),
        "offenders": offenders,
        "note": (
            "RAW: considera válidos <abbr title>, aria-label/aria-describedby, expansión en primera aparición "
            "o glosario global. Se detectan abreviaturas en mayúsculas de 2–6 letras."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede aportar:
      rctx.abbreviations_test = [
        { "abbr": str, "occurrences": int, "has_title": bool, "has_aria_label": bool,
          "has_aria_describedby": bool, "inline_expansion_nearby": bool, "covered_by_glossary": bool }
      ]
      y rctx.has_global_glossary: bool
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 3.1.4; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "abbreviations_test", []))
    has_glossary = bool(getattr(rctx, "has_global_glossary", False))

    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = (d.get("note","") + " | RENDERED: sin 'abbreviations_test', se reusó RAW.").strip()
        return d

    applicable = 1
    total = 0
    explained = 0
    missing = 0
    offenders: List[Dict[str, Any]] = []

    for it in data:
        if not isinstance(it, dict):
            continue
        total += 1
        explained_here = bool(it.get("has_title")) or bool(it.get("has_aria_label")) \
                         or bool(it.get("has_aria_describedby")) or bool(it.get("inline_expansion_nearby")) \
                         or bool(it.get("covered_by_glossary")) or has_glossary
        if explained_here:
            explained += 1
        else:
            missing += 1
            offenders.append({"abbr": _s(it.get("abbr")), "reason": "Abreviatura sin mecanismo de expansión (runtime)."})

    violations = 0 if (has_glossary or missing == 0) else missing
    ok_ratio = 1.0 if total == 0 else (1.0 if violations == 0 else (explained / max(1, total)))

    details: Dict[str, Any] = {
        "rendered": True,
        "applicable": applicable,
        "abbreviations_total": total,
        "explained": explained,
        "missing": missing,
        "has_global_glossary": has_glossary,
        "violations": violations,
        "ok_ratio": round(ok_ratio, 4),
        "offenders": offenders,
        "note": "RENDERED: verificación explícita de expansión por atributos/inline/glosario."
    }
    return details

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False, "ai_message": "IA no configurada."}
    need = (details.get("missing", 0) or 0) > 0 or (not details.get("has_global_glossary", False))
    if not need:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "offenders": (details.get("offenders", []) or [])[:30],
        "html_snippet": (html_sample or "")[:2200],
        "examples": [
            "<abbr title='Hypertext Markup Language'>HTML</abbr>",
            "Hypertext Markup Language (HTML)",
            "HTML (Hypertext Markup Language)"
        ]
    }
    prompt = (
        "Eres auditor WCAG 3.1.4 (Abbreviations, AAA). "
        "Para cada abreviatura sin expansión, sugiere usar <abbr title> o explicar en la primera aparición, "
        "o enlazar a un glosario. Devuelve JSON: "
        "{ suggestions: [{abbr, snippet, rationale}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_3_1_4(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None
) -> CriterionOutcome:

    if mode == CheckMode.RENDERED:
        if rendered_ctx is None:
            details = _compute_counts_raw(ctx); details["warning"] = "Se pidió RENDERED sin rendered_ctx; fallback a RAW."; src = "raw"
        else:
            details = _compute_counts_rendered(rendered_ctx); src = "rendered"
    else:
        details = _compute_counts_raw(ctx); src = "raw"

    manual_required = False
    if mode == CheckMode.AI:
        ai = _ai_review(details, html_sample=html_for_ai); details["ai_info"] = ai; src = "ai"
        manual_required = bool(ai.get("manual_required", False))

    total = int(details.get("abbreviations_total", 0) or 0)
    has_glossary = bool(details.get("has_global_glossary", False))
    missing = int(details.get("missing", 0) or 0)
    passed = (total == 0) or has_glossary or (missing == 0)

    verdict = verdict_from_counts(details, passed)
    score0 = score_from_verdict(verdict)
    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0, details=details,
        level=meta.get("level","AAA"), principle=meta.get("principle","Comprensible"),
        title=meta.get("title","Abreviaturas"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
