# audits/checks/criteria/p3/c_3_3_6_error_prevention_all.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "3.3.6"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

CONFIRM_RE = re.compile(
    r"(confirmar|revise|revisar|resumen|summary|review|step\s*\d+\s*of\s*\d+)",
    re.I
)
REVERSIBLE_RE = re.compile(
    r"(cancelar|anular|deshacer|undo|revert|reembols[oa]|refund|editar|cambiar)",
    re.I
)
VALIDATION_HINT_RE = re.compile(
    r"(formato|format|ejemplo|example|debe\s+ser|should\s+be|inv[aá]lido|invalid|requerid[oa]|required|error)",
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

def _forms_in_page(ctx: PageContext):
    soup = getattr(ctx, "soup", None)
    if soup is None:
        controls = _as_list(getattr(ctx, "inputs", []))
        return controls and [None] or []
    try:
        return list(soup.find_all("form"))
    except Exception:
        return []

def _form_text(form) -> str:
    try:
        return (form.get_text() or "") if hasattr(form, "get_text") else ""
    except Exception:
        return ""

def _has_review_step(text: str) -> bool:
    return bool(CONFIRM_RE.search(text or ""))

def _has_reversible_signals(text: str) -> bool:
    return bool(REVERSIBLE_RE.search(text or ""))

def _has_validation_signals(text: str) -> bool:
    return bool(VALIDATION_HINT_RE.search(text or ""))

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    3.3.6 (AAA): Para TODAS las páginas que envían datos, al menos UNO:
      (1) la acción es reversible, (2) validación con posibilidad de corrección,
      (3) revisión/confirmación antes del envío final.
    RAW (heurístico en una página): inspecciona cada formulario.
    """
    page_text = _page_text(ctx)
    forms = _forms_in_page(ctx)

    if not forms:
        return {"applicable": 0, "ok_ratio": 1.0, "offenders": [], "note": "Sin formularios; NA para 3.3.6."}

    applicable = 0
    ok_cases = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for idx, f in enumerate(forms[:25]):
        applicable += 1
        ftxt = page_text if f is None else _form_text(f)
        reversible = _has_reversible_signals(page_text + " " + ftxt)
        review = _has_review_step(page_text + " " + ftxt)
        validation = _has_validation_signals(page_text + " " + ftxt)

        if reversible or review or validation:
            ok_cases += 1
        else:
            violations += 1
            offenders.append({"form_index": idx, "reason": "Formulario sin reversible/revisión/validación (heurístico)."})

    ok_ratio = 1.0 if applicable == 0 else (ok_cases / max(1, applicable))
    return {
        "applicable": applicable,
        "ok_cases": ok_cases,
        "violations": violations,
        "ok_ratio": round(ok_ratio, 4),
        "offenders": offenders,
        "note": "RAW: exige los mismos caminos de prevención que 3.3.4 pero aplicados a todos los formularios."
    }

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    rctx.error_prevention_all_test = [
      { "form_selector": str,
        "reversible": bool,
        "has_review_step": bool,
        "has_validation_and_correction": bool,
        "notes": str|None }
    ]
    Violación si ninguno de los tres es True.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 3.3.6; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "error_prevention_all_test", []))
    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = d.get("note","") + " | RENDERED: sin 'error_prevention_all_test', se reusó RAW."
        return d

    applicable = 0
    ok_cases = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for it in data:
        if not isinstance(it, dict): continue
        applicable += 1
        reversible = bool(it.get("reversible"))
        review = bool(it.get("has_review_step"))
        validation = bool(it.get("has_validation_and_correction"))
        if reversible or review or validation:
            ok_cases += 1
        else:
            violations += 1
            offenders.append({
                "form_selector": _s(it.get("form_selector")),
                "reason": "Sin reversible/revisión/validación (runtime).",
                "notes": _s(it.get("notes"))
            })

    ok_ratio = 1.0 if applicable == 0 else (ok_cases / max(1, applicable))
    return {
        "rendered": True,
        "applicable": applicable,
        "ok_cases": ok_cases,
        "violations": violations,
        "ok_ratio": round(ok_ratio, 4),
        "offenders": offenders,
        "note": "RENDERED: evaluación por formulario de reversibilidad, revisión o validación con corrección."
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
        "offenders": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2200],
        "recipes": [
            "Añadir pantalla de revisión antes de enviar cualquier formulario.",
            "Incluir validaciones con mensajes y permitir corrección en línea.",
            "Proveer 'Deshacer' o 'Editar' tras el envío cuando sea posible."
        ]
    }
    prompt = (
        "Eres auditor WCAG 3.3.6 (Error Prevention — All, AAA). "
        "Propón acciones para asegurar reversible/revisión/validación en todos los formularios. "
        "Devuelve JSON: { suggestions:[{form_selector?, change, snippet?, rationale}], manual_review?:bool }"
    )
    try:
        ans = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ans, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_3_3_6(
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
        title=meta.get("title","Prevención de errores (todas)"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
