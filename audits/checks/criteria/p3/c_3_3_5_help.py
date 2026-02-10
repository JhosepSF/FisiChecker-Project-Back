# audits/checks/criteria/p3/c_3_3_5_help.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "3.3.5"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

HELP_RE = re.compile(
    r"(ayuda|help|soporte|support|faq|preguntas\s+frecuentes|contacto|asistencia|"
    r"gu[ií]a|instrucciones|manual|tooltip|\?)",
    re.I
)

def _as_list(x):
    if not x: return []
    if isinstance(x, list): return x
    return list(x)

def _s(v: Any) -> str:
    return "" if v is None else str(v)

def _page_text(ctx: PageContext) -> str:
    soup = getattr(ctx, "soup", None)
    if soup is not None:
        try:
            return (soup.get_text() or "")  # type: ignore[attr-defined]
        except Exception:
            pass
    return _s(getattr(ctx, "document_text", ""))

def _has_help_links_in_form(form) -> bool:
    try:
        # enlaces a help/faq/soporte dentro del form
        for a in form.find_all("a"):
            txt = _s(getattr(a, "get_text", lambda: "")())  # type: ignore[misc]
            href = a.get("href") if hasattr(a, "get") else None  # type: ignore[attr-defined]
            if HELP_RE.search(txt or "") or HELP_RE.search(_s(href)):
                return True
    except Exception:
        pass
    return False

def _forms_in_page(ctx: PageContext):
    soup = getattr(ctx, "soup", None)
    if soup is None:
        return []
    try:
        return list(soup.find_all("form"))
    except Exception:
        return []

def _has_field_level_help(form) -> bool:
    try:
        # ¿hay hints/ayuda por campo? aria-describedby hacia elementos con pistas, o iconos de ayuda
        for el in form.find_all(True):
            title = el.get("title") if hasattr(el, "get") else None  # type: ignore[attr-defined]
            aria_label = el.get("aria-label") if hasattr(el, "get") else None  # type: ignore[attr-defined]
            cls = el.get("class") if hasattr(el, "get") else None  # type: ignore[attr-defined]
            textish = _s(title) + " " + _s(aria_label) + " " + " ".join(cls) if isinstance(cls, list) else _s(cls)
            if HELP_RE.search(textish or ""):
                return True
        return False
    except Exception:
        return False

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    3.3.5 (AAA): Se proporciona ayuda contextual cuando el contenido requiere entrada de usuario.
    RAW:
      - Busca enlaces a ayuda/FAQ/soporte dentro de formularios.
      - Busca pistas/ayuda a nivel de campo (title/aria-label/clases tipo 'help', íconos '?').
      - También acepta ayudas globales visibles en la página (menos preferible).
    """
    soup = getattr(ctx, "soup", None)
    forms = _forms_in_page(ctx)

    applicable = 0
    with_help = 0
    offenders: List[Dict[str, Any]] = []

    if forms:
        for idx, f in enumerate(forms[:20]):
            applicable += 1
            page_help = False
            field_help = _has_field_level_help(f)
            link_help = _has_help_links_in_form(f)
            page_help = False
            if soup is not None and (field_help or link_help) is False:
                try:
                    txt = soup.get_text()  # type: ignore[attr-defined]
                    page_help = bool(HELP_RE.search(txt or ""))
                except Exception:
                    page_help = False

            if field_help or link_help or page_help:
                with_help += 1
            else:
                offenders.append({"form_index": idx, "reason": "Sin ayudas visibles (enlaces, tooltips, hints) en o cerca del formulario."})
    else:
        # si no hay forms no aplica estrictamente
        return {"applicable": 0, "ok_ratio": 1.0, "offenders": [], "note": "Sin formularios; NA para 3.3.5."}

    passed = (applicable == 0) or (with_help == applicable)
    ok_ratio = 1.0 if applicable == 0 else (with_help / max(1, applicable))

    return {
        "applicable": applicable,
        "with_help": with_help,
        "violations": max(0, applicable - with_help),
        "ok_ratio": round(ok_ratio, 4),
        "offenders": offenders,
        "note": "RAW: ayuda por formulario (enlace a ayuda/FAQ/soporte o hints/tooltip por campo)."
    }

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    rctx.help_availability_test = [
      { "form_selector": str, "has_form_help_link": bool, "has_field_help": bool, "has_page_help": bool, "notes": str|None }
    ]
    Debe haber algún tipo de ayuda (form/field/page) para cada formulario.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 3.3.5; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "help_availability_test", []))
    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = d.get("note","") + " | RENDERED: sin 'help_availability_test', se reusó RAW."
        return d

    applicable = 0
    with_help = 0
    offenders: List[Dict[str, Any]] = []

    for it in data:
        if not isinstance(it, dict): continue
        applicable += 1
        ok = bool(it.get("has_form_help_link")) or bool(it.get("has_field_help")) or bool(it.get("has_page_help"))
        if ok:
            with_help += 1
        else:
            offenders.append({"form_selector": _s(it.get("form_selector")), "reason": "Formulario sin ayuda (runtime)."})

    ok_ratio = 1.0 if applicable == 0 else (with_help / max(1, applicable))
    return {
        "rendered": True,
        "applicable": applicable,
        "with_help": with_help,
        "violations": max(0, applicable - with_help),
        "ok_ratio": round(ok_ratio, 4),
        "offenders": offenders,
        "note": "RENDERED: verificación de ayuda por formulario (enlace, hint, ayuda global cercana)."
    }

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str]=None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False, "ai_message":"IA no configurada."}
    need = int(details.get("violations", 0) or 0) > 0
    if not need: return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "offenders": (details.get("offenders", []) or [])[:15],
        "html_snippet": (html_sample or "")[:2200],
        "recipes": [
            "Añade un enlace '¿Necesitas ayuda?' junto al título del formulario.",
            "Incluye hints por campo vinculados con aria-describedby.",
            "Ofrece un enlace a 'Preguntas frecuentes' o chat de soporte."
        ]
    }
    prompt = (
        "Eres auditor WCAG 3.3.5 (Help, AAA). "
        "Propón ayudas concretas (links, hints, tooltips) y snippets accesibles. "
        "Devuelve JSON: { suggestions:[{form_selector?, help_type, snippet?, rationale}], manual_review?:bool }"
    )
    try:
        ans = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ans, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_3_3_5(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext]=None,
    html_for_ai: Optional[str]=None
) -> CriterionOutcome:

    if mode == CheckMode.RENDERED:
        if rendered_ctx is None:
            details=_compute_counts_raw(ctx); details["warning"]="Se pidió RENDERED sin rendered_ctx; fallback a RAW."; src="raw"
        else:
            details=_compute_counts_rendered(rendered_ctx); src="rendered"
    else:
        details=_compute_counts_raw(ctx); src="raw"

    manual_required=False
    if mode == CheckMode.AI:
        ai=_ai_review(details, html_sample=html_for_ai); details["ai_info"]=ai; src="ai"
        manual_required = bool(ai.get("manual_review", False))

    violations = int(details.get("violations", 0) or 0)
    applicable = int(details.get("applicable", 0) or 0)
    
    # Ultra estricto: PASS solo si 100%, PARTIAL >= 80%, FAIL < 80%
    if applicable == 0 or violations == 0:
        passed = True
        details["ratio"] = 1.0
    else:
        ok_count = applicable - violations
        ratio = ok_count / applicable
        details["ratio"] = ratio
        # PARTIAL si >= 80%, FAIL si < 80%
        if ratio >= 0.80:
            passed = True  # verdict_from_counts detectará partial
        else:
            passed = False

    verdict = verdict_from_counts(details, passed)
    score0  = score_from_verdict(verdict)
    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0, details=details,
        level=meta.get("level","AAA"), principle=meta.get("principle","Comprensible"),
        title=meta.get("title","Ayuda"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
