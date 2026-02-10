# audits/checks/criteria/p3/c_3_3_3_error_suggestion.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "3.3.3"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

SUGGESTION_RE = re.compile(
    r"(debe\s+ser|usa[r]?\s+formato|ejemplo|example|e\.?g\.?|formato\s+v[áa]lido|"
    r"should\s+be|enter\s+a\s+valid|expected\s+format|for\s+example)",
    re.I
)

def _as_list(x):
    if not x: return []
    if isinstance(x, list): return x
    return list(x)

def _s(v: Any) -> str:
    return "" if v is None else str(v)

def _lower(v: Any) -> str:
    return _s(v).strip().lower()

def _get_attr(node: Any, name: str) -> Optional[str]:
    try:
        if isinstance(node, dict):
            val = node.get(name);  return _s(val) if val is not None else None
        if hasattr(node, "get"):
            val = node.get(name)  # type: ignore[attr-defined]
            return _s(val) if val is not None else None
    except Exception:
        pass
    return None

def _get_text(node: Any) -> str:
    if isinstance(node, dict):
        for k in ("text","inner_text","aria-label","title","label"):
            v = node.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""
    try:
        if hasattr(node, "get_text"):
            t = node.get_text()  # type: ignore[attr-defined]
            if isinstance(t, str) and t.strip():
                return t.strip()
    except Exception:
        pass
    return ""

def _resolve_ids_text(soup, ids_str: Optional[str]) -> str:
    if soup is None or not ids_str:
        return ""
    ids = [i for i in ids_str.strip().split() if i]
    texts: List[str] = []
    for i in ids[:6]:
        try:
            el = soup.find(id=i)
            if el is not None:
                tt = _get_text(el)
                if tt:
                    texts.append(tt)
        except Exception:
            continue
    return " ".join(texts)

def _is_form_control(n: Dict[str, Any]) -> bool:
    tag = _lower(n.get("tag"))
    role = _lower(n.get("role"))
    t = _lower(n.get("type"))
    if tag in {"input","textarea","select"}:
        if tag == "input" and t in {"hidden","button","submit","reset","image"}:
            return False
        return True
    if role in {"textbox","combobox","listbox","spinbutton","slider"}:
        return True
    return False

def _has_suggestion_for(n: Dict[str, Any], soup) -> bool:
    """
    Busca sugerencia asociada al control:
      - aria-describedby → texto con patrones de sugerencia/ejemplo.
      - title / aria-label con ejemplo/formato.
      - placeholder con 'ej:' / 'example' (aceptado como sugerencia, NO como etiqueta).
    """
    # describedby
    dby = _get_attr(n, "aria-describedby")
    txt = _resolve_ids_text(soup, dby)
    if txt and SUGGESTION_RE.search(txt):
        return True
    # title/aria-label
    if SUGGESTION_RE.search(_s(n.get("title") or "") + " " + _s(n.get("aria-label") or "")):
        return True
    # placeholder con ejemplo (ej:, e.g., example)
    ph = _s(n.get("placeholder") or "")
    if re.search(r"\b(ej\.?|ejemplo|example|e\.?g\.?)\b", ph, re.I):
        return True
    return False

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    3.3.3 (AA) — Si se detectan errores de entrada automáticamente, se proporcionan sugerencias para corregirlos.
    RAW (heurístico):
      - Considera “error detectado” cuando aria-invalid="true".
      - Busca sugerencia asociada al control (aria-describedby, title/aria-label, placeholder con 'ej:').
    """
    soup = getattr(ctx, "soup", None)
    controls = [n for n in _as_list(getattr(ctx, "form_controls", []) or getattr(ctx, "inputs", [])) if isinstance(n, dict)]

    applicable = 0
    with_suggestion = 0
    missing_suggestion = 0
    offenders: List[Dict[str, Any]] = []

    for n in controls:
        if not _is_form_control(n):
            continue
        if _lower(n.get("aria-invalid")) != "true":
            continue
        applicable += 1
        if _has_suggestion_for(n, soup):
            with_suggestion += 1
        else:
            missing_suggestion += 1
            offenders.append({
                "id": _s(n.get("id")), "name": _s(n.get("name")), "tag": _s(n.get("tag")),
                "reason": "Campo inválido sin sugerencia de corrección (ejemplo/formato esperado)."
            })

    details: Dict[str, Any] = {
        "applicable": applicable,
        "with_suggestion": with_suggestion,
        "missing_suggestion": missing_suggestion,
        "ok_ratio": 1.0 if applicable == 0 else (1.0 if missing_suggestion == 0 else max(0.0, min(1.0, with_suggestion / max(1, applicable)))),
        "offenders": offenders,
        "note": (
            "RAW: usa aria-invalid='true' como señal de error detectado y busca sugerencias ligadas al control "
            "(aria-describedby, title/aria-label, placeholder con 'ej:')."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    rctx.error_suggestion_test = [
      { "selector": str, "invalid_detected": bool, "had_suggestion": bool, "suggestion_text": str|None }
    ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 3.3.3; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "error_suggestion_test", []))
    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = d.get("note","") + " | RENDERED: sin 'error_suggestion_test', se reusó RAW."
        return d

    applicable = 0
    with_suggestion = 0
    missing_suggestion = 0
    offenders: List[Dict[str, Any]] = []

    for it in data:
        if not isinstance(it, dict): continue
        if not bool(it.get("invalid_detected")): continue
        applicable += 1
        if bool(it.get("had_suggestion")):
            with_suggestion += 1
        else:
            missing_suggestion += 1
            offenders.append({"selector": _s(it.get("selector")), "reason": "Campo inválido sin sugerencia (runtime)."})

    ok_ratio = 1.0 if applicable == 0 else (1.0 if missing_suggestion == 0 else max(0.0, min(1.0, with_suggestion / max(1, applicable))))
    return {
        "rendered": True,
        "applicable": applicable,
        "with_suggestion": with_suggestion,
        "missing_suggestion": missing_suggestion,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: verificación explícita de sugerencias ante error detectado."
    }

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str]=None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False, "ai_message":"IA no configurada."}
    need = int(details.get("missing_suggestion", 0) or 0) > 0
    if not need:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "offenders": (details.get("offenders", []) or [])[:25],
        "html_snippet": (html_sample or "")[:2400],
        "recipes": [
            "Añade pista: <span id='email-hint' class='hint'>Ej.: nombre@dominio.com</span> + aria-describedby.",
            "Si hay patrón, documenta formato: <input pattern='\\d{4}-\\d{2}-\\d{2}' title='Formato: AAAA-MM-DD'>.",
            "Corrige inmediatamente junto al campo, no solo arriba del formulario."
        ]
    }
    prompt = (
        "Eres auditor WCAG 3.3.3 (Error Suggestion, AA). "
        "Genera mensajes de sugerencia/ejemplo por campo y cómo enlazarlos. "
        "Devuelve JSON: { suggestions:[{field_id?, hint, snippet, rationale}], manual_review?:bool, summary?:string }"
    )
    try:
        ans = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ans, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_3_3_3(
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
        ai = _ai_review(details, html_sample=html_for_ai); details["ai_info"]=ai; src="ai"
        manual_required = bool(ai.get("manual_review", False))

    applicable = int(details.get("applicable", 0) or 0)
    missing = int(details.get("missing_suggestion", 0) or 0)
    
    # Ultra estricto: PASS solo si 100%, PARTIAL >= 80%, FAIL < 80%
    if applicable == 0 or missing == 0:
        passed = True
        details["ratio"] = 1.0
    else:
        ok_count = applicable - missing
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
        title=meta.get("title","Sugerencia ante errores"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
