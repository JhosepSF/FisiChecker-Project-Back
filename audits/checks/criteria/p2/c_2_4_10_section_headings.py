# audits/checks/criteria/p2/c_2_4_10_section_headings.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.4.10"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

HEADING_TAG_RE = re.compile(r"^h[1-6]$", re.I)

def _as_list(x):
    if not x:
        return []
    if isinstance(x, list):
        return x
    return list(x)

def _s(v: Any) -> str:
    return "" if v is None else str(v)

def _lower(v: Any) -> str:
    return _s(v).strip().lower()

def _norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def _get_text(node: Any) -> str:
    """Texto visible aproximado para dict o Tag."""
    if isinstance(node, dict):
        for k in ("text","label","aria-label","title","accessible_name","inner_text"):
            v = node.get(k)
            if isinstance(v, str) and v.strip():
                return _norm_spaces(v)
        return ""
    try:
        if hasattr(node, "get_text"):
            t = node.get_text()  # type: ignore[attr-defined]
            if isinstance(t, str) and t.strip():
                return _norm_spaces(t)
    except Exception:
        pass
    return ""

def _extract_headings(ctx: PageContext) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for h in _as_list(getattr(ctx, "heading_tags", [])):
        try:
            if isinstance(h, dict):
                text = _get_text(h)
                level = h.get("level")
                tag = _lower(_s(h.get("tag")))
                if level is None and tag:
                    m = re.match(r"h([1-6])$", tag)
                    level = int(m.group(1)) if m else None
                out.append({"level": level if isinstance(level, int) else None,
                            "text": text, "tag": tag or None,
                            "selector": _s(h.get("selector") or h.get("id"))})
            else:
                tagname = _lower(getattr(h, "name", ""))
                if not HEADING_TAG_RE.match(tagname or ""):
                    continue
                try:
                    text = _norm_spaces(h.get_text())  # type: ignore[attr-defined]
                except Exception:
                    text = ""
                lvl = None
                m = re.match(r"h([1-6])$", tagname) if tagname else None
                if m:
                    try:
                        lvl = int(m.group(1))
                    except Exception:
                        lvl = None
                out.append({"level": lvl, "text": text, "tag": tagname, "selector": _s(getattr(h, "id", ""))})
        except Exception:
            continue
    return out

def _page_word_count(ctx: PageContext) -> int:
    soup = getattr(ctx, "soup", None)
    if soup is None:
        txt = _s(getattr(ctx, "document_text", "") or "")
        return len(re.findall(r"\w+", txt, re.UNICODE))
    try:
        raw = soup.get_text()  # type: ignore[attr-defined]
        return len(re.findall(r"\w+", _s(raw), re.UNICODE))
    except Exception:
        return 0

# ------------------------------------------------------------
# Heurística de aplicabilidad y aprobación
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.4.10 (AAA): Se usan encabezados de sección para organizar el contenido.
    Heurísticas:
      - Si la página es “larga” (>= 300 palabras) y no hay encabezados → violación.
      - Si la página es “muy larga” (>= 800 palabras) y hay < 2 encabezados → violación.
      - Encabezados vacíos no cuentan; se reportan.
      - Si existen encabezados no vacíos, asumimos que organizan (sin validar jerarquía completa).
    """
    words = _page_word_count(ctx)
    headings = _extract_headings(ctx)

    total = len(headings)
    nonempty = 0
    empty = 0
    offenders: List[Dict[str, Any]] = []

    for h in headings:
        t = _s(h.get("text"))
        if t.strip():
            nonempty += 1
        else:
            empty += 1
            offenders.append({"selector": h.get("selector"), "reason": "Encabezado vacío."})

    applicable = 1 if words >= 150 or total > 0 else 0

    violates = 0
    if words >= 300 and nonempty == 0:
        violates += 1
        offenders.append({"reason": "Página larga sin ningún encabezado de sección."})
    if words >= 800 and nonempty < 2:
        violates += 1
        offenders.append({"reason": "Página muy larga con menos de dos encabezados."})

    # si hay encabezados no vacíos y no se cumplen condiciones de violación, consideramos que “organiza”
    passed = (applicable == 0) or (violates == 0 and nonempty >= 1)

    ok_ratio = 1.0 if applicable == 0 else (1.0 if passed else 0.0)

    details: Dict[str, Any] = {
        "word_count": words,
        "headings_total": total,
        "headings_nonempty": nonempty,
        "headings_empty": empty,
        "applicable": applicable,
        "violations": violates,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 2.4.10 requiere usar encabezados de sección para organizar el contenido. "
            "Heurísticas por longitud de la página y presencia de encabezados no vacíos; "
            "no se valida la jerarquía completa (H1→H2→H3…)."
        )
    }
    return details

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED puedes usar el DOM post-JS (headings dinámicos, routing SPA).
    Si no se aporta nada extra, se reutiliza RAW.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.4.10; no se pudo evaluar en modo renderizado."}
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note","") + " | RENDERED: evaluación tras renderizado/SPA.").strip()
    return d

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: sugiere insertar encabezados de sección (H2/H3) en páginas largas sin estructura.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    needs = (details.get("violations", 0) or 0) > 0 or (details.get("headings_nonempty", 0) or 0) == 0
    if not needs:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "word_count": details.get("word_count"),
        "offenders": details.get("offenders", [])[:10],
        "html_snippet": (html_sample or "")[:2200],
        "patterns": {
            "suggest_h2": "Usa <h2> para secciones principales y <h3> para subsecciones.",
            "toc_hint": "Para páginas muy largas, añade un pequeño índice al inicio (ver 2.4.1/2.4.5)."
        }
    }
    prompt = (
        "Eres auditor WCAG 2.4.10 (Section Headings, AAA). "
        "Propón encabezados H2/H3 para organizar la página y, si aplica, un índice breve. "
        "Devuelve JSON: { suggestions: [{heading_level, text, where_hint?, rationale}], "
        "toc?: [{text, anchor?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_2_4_10(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None
) -> CriterionOutcome:
    if mode == CheckMode.RENDERED:
        if rendered_ctx is None:
            details = _compute_counts_raw(ctx)
            details["warning"] = "Se pidió RENDERED sin rendered_ctx; fallback a RAW."
            src = "raw"
        else:
            details = _compute_counts_rendered(rendered_ctx)
            src = "rendered"
    else:
        details = _compute_counts_raw(ctx)
        src = "raw"

    manual_required = False
    if mode == CheckMode.AI:
        ai_info = _ai_review(details, html_sample=html_for_ai)
        details["ai_info"] = ai_info
        src = "ai"
        manual_required = bool(ai_info.get("manual_review", False))

    applicable = int(details.get("applicable", 0) or 0)
    violations = int(details.get("violations", 0) or 0)
    nonempty = int(details.get("headings_nonempty", 0) or 0)
    passed = (applicable == 0) or (violations == 0 and nonempty >= 1)

    verdict = verdict_from_counts(details, passed)
    score0 = score_from_verdict(verdict)

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE,
        passed=passed,
        verdict=verdict,
        score_0_2=score0,
        details=details,
        level=meta.get("level", "AAA"),
        principle=meta.get("principle", "Operable"),
        title=meta.get("title", "Encabezados de sección"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
