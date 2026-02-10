# audits/checks/criteria/p3/c_3_3_4_error_prevention_legal.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "3.3.4"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

LEGAL_FIN_DATA_RE = re.compile(
    r"(pago|pagar|compr(a|ar)|pedido|checkout|facturaci[oó]n|suscripci[oó]n|"
    r"transferencia|bancari[ao]|tarjeta|financ(i|e)r[oa]|legal|contrato|renuncia|t[eé]rminos|"
    r"declaraci[oó]n|impuesto|tax|invoice|billing|checkout|place\s+order)",
    re.I
)

CONFIRM_RE = re.compile(
    r"(confirmar|revise|revisar|revisi[oó]n|resumen|summary|review|step\s*\d+\s*of\s*\d+)",
    re.I
)
REVERSIBLE_RE = re.compile(
    r"(cancelar|anular|deshacer|undo|reembols[oa]|refund|revocar|withdraw|editar|cambiar)",
    re.I
)
VALIDATION_HINT_RE = re.compile(
    r"(formato|format|ejemplo|example|debe\s+ser|should\s+be|inv[aá]lido|invalid|requerid[oa]|required)",
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

def _scripts_text(ctx: PageContext) -> str:
    t = _s(getattr(ctx, "scripts_text", ""))
    if t: return t
    soup = getattr(ctx, "soup", None)
    if soup is None: return ""
    out: List[str] = []
    try:
        for sc in soup.find_all("script"):
            txt = sc.get_text()  # type: ignore[attr-defined]
            if isinstance(txt, str) and txt.strip():
                out.append(txt)
    except Exception:
        pass
    return "\n".join(out)

def _forms_in_page(ctx: PageContext):
    soup = getattr(ctx, "soup", None)
    if soup is None:
        # Fallback: si no hay soup, inferimos un único "form" si hay controles
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

def _looks_transactional(text: str) -> bool:
    return bool(LEGAL_FIN_DATA_RE.search(text or ""))

def _has_review_step(text: str) -> bool:
    return bool(CONFIRM_RE.search(text or ""))

def _has_reversible_signals(text: str, scripts: str) -> bool:
    return bool(REVERSIBLE_RE.search(text or "") or REVERSIBLE_RE.search(scripts or ""))

def _has_validation_signals(text: str) -> bool:
    return bool(VALIDATION_HINT_RE.search(text or ""))

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    3.3.4 (AA): Para transacciones legales/financieras/datos, al menos UNO:
      (1) la acción es reversible, (2) los datos se validan y se permite corregir,
      (3) se presenta revisión/confirmación antes de finalizar.
    RAW (heurístico): detecta formularios transaccionales por palabras clave y busca señales de (1)-(3).
    """
    page_text = _page_text(ctx)
    scripts = _scripts_text(ctx)
    forms = _forms_in_page(ctx)

    applicable = 0
    violations = 0
    ok_cases = 0
    offenders: List[Dict[str, Any]] = []

    if not forms:
        # página sin formularios; podría no aplicar salvo copy transaccional sin inputs
        if _looks_transactional(page_text):
            # texto transaccional sin mecanismo detectable — marcar NA con nota
            return {
                "applicable": 0,
                "ok_ratio": 1.0,
                "note": "Texto transaccional sin formularios detectados; revisión manual.",
                "offenders": []
            }
        return {"applicable": 0, "ok_ratio": 1.0, "offenders": [], "note": "Sin formularios."}

    for idx, f in enumerate(forms[:20]):
        ftxt = page_text if f is None else _form_text(f)
        if not _looks_transactional(ftxt + " " + page_text):
            continue
        applicable += 1

        reversible = _has_reversible_signals(page_text + " " + ftxt, scripts)
        has_review = _has_review_step(page_text + " " + ftxt)
        has_validation = _has_validation_signals(page_text + " " + ftxt)

        if reversible or has_review or has_validation:
            ok_cases += 1
        else:
            violations += 1
            offenders.append({
                "form_index": idx,
                "reason": "Formulario transaccional sin señales de reversibilidad, revisión o validación/corrección (heurístico)."
            })

    passed = (applicable == 0) or (violations == 0)
    ok_ratio = 1.0 if applicable == 0 else (1.0 if violations == 0 else (ok_cases / max(1, applicable)))

    details: Dict[str, Any] = {
        "applicable": applicable,
        "ok_cases": ok_cases,
        "violations": violations,
        "ok_ratio": round(ok_ratio, 4),
        "offenders": offenders,
        "note": (
            "RAW: detecta transacciones por palabras clave y busca (reversible / revisión / validación con corrección). "
            "Confirmar en RENDERED el flujo real."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    rctx.error_prevention_legal_test = [
      { "flow": "checkout|contract|transfer|other",
        "reversible": bool,
        "has_review_step": bool,
        "has_validation_and_correction": bool,
        "notes": str|None }
    ]
    Violación si para un flujo transaccional no se cumple al menos uno de los tres.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 3.3.4; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "error_prevention_legal_test", []))
    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = d.get("note","") + " | RENDERED: sin 'error_prevention_legal_test', se reusó RAW."
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
            offenders.append({ "flow": _s(it.get("flow")), "reason": "Sin reversible/revisión/validación." })

    ok_ratio = 1.0 if applicable == 0 else (ok_cases / max(1, applicable))
    return {
        "rendered": True,
        "applicable": applicable,
        "ok_cases": ok_cases,
        "violations": violations,
        "ok_ratio": round(ok_ratio, 4),
        "offenders": offenders,
        "note": "RENDERED: evaluación explícita de los tres caminos de prevención."
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
            "Añadir paso de revisión ('Revisar pedido') previo al pago.",
            "Marcar campos con validación y mostrar mensajes + corrección in situ.",
            "Ofrecer 'Cancelar/Deshacer' o períodos de gracia (p.ej., 24h) para revertir."
        ]
    }
    prompt = (
        "Eres auditor WCAG 3.3.4 (Error Prevention — Legal/Financial/Data, AA). "
        "Propón cambios para cumplir al menos uno: reversible / revisión / validación. "
        "Devuelve JSON: { suggestions:[{flow?, change, snippet?, rationale}], manual_review?:bool }"
    )
    try:
        ans = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ans, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_3_3_4(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext]=None,
    html_for_ai: Optional[str]=None
) -> CriterionOutcome:

    if mode == CheckMode.RENDERED:
        if rendered_ctx is None:
            details = _compute_counts_raw(ctx); details["warning"]="Se pidió RENDERED sin rendered_ctx; fallback a RAW."; src="raw"
        else:
            details = _compute_counts_rendered(rendered_ctx); src="rendered"
    else:
        details = _compute_counts_raw(ctx); src="raw"

    manual_required = False
    if mode == CheckMode.AI:
        ai=_ai_review(details, html_sample=html_for_ai); details["ai_info"]=ai; src="ai"
        manual_required = bool(ai.get("manual_review", False))

    applicable = int(details.get("applicable", 0) or 0)
    violations = int(details.get("violations", 0) or 0)
    
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
        level=meta.get("level","AA"), principle=meta.get("principle","Comprensible"),
        title=meta.get("title","Prevención de errores (legal, financiera, datos)"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
