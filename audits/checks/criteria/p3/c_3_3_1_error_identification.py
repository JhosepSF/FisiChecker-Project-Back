# audits/checks/criteria/p3/c_3_3_1_error_identification.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "3.3.1"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

ERROR_WORDS_RE = re.compile(
    r"(error|inv[aá]lido|incorrect[oa]|requerid[oa]|obligatorio|missing|invalid|"
    r"must\s+be|please\s+enter|is\s+required|formato|format[oa])",
    re.I
)

ALERT_REGION_SELECTOR = re.compile(r"\b(alert|status)\b", re.I)

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

def _has_alert_region(soup) -> bool:
    if soup is None: return False
    try:
        if soup.find(attrs={"role":"alert"}) or soup.find(attrs={"aria-live": True}):
            return True
        # cualquier región con role=status o alert
        if soup.find(attrs={"role": re.compile(r"(alert|status)", re.I)}):
            return True
    except Exception:
        pass
    return False

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    3.3.1 (A) — Si se detecta un error de entrada, el error se identifica al usuario.
    RAW (heurístico):
      - Controles con aria-invalid="true" → se espera mensaje cercano o referenciado (aria-describedby) con palabras de error.
      - Busca mensajes con clases/patrones de “error” cerca del control (estático).
      - Señala ausencia de regiones de anuncio (role="alert"/aria-live) como información complementaria.
    """
    soup = getattr(ctx, "soup", None)
    controls = [n for n in _as_list(getattr(ctx, "form_controls", []) or getattr(ctx, "inputs", [])) if isinstance(n, dict)]

    applicable = 0  # número de controles invalid
    with_message = 0
    missing_message = 0
    offenders: List[Dict[str, Any]] = []

    for n in controls:
        if not _is_form_control(n):
            continue
        aria_invalid = _lower(n.get("aria-invalid")) == "true"
        if not aria_invalid:
            continue
        applicable += 1

        # 1) aria-describedby apunta a texto con indicios de error
        desc = _get_attr(n, "aria-describedby")
        desc_text = _resolve_ids_text(soup, desc)
        found = bool(desc_text and ERROR_WORDS_RE.search(desc_text))

        # 2) título/label del control contiene indicios (menos fiable)
        if not found:
            nameish = " ".join([_get_text(n), _s(n.get("label_text") or ""), _s(n.get("placeholder") or ""), _s(n.get("title") or "")])
            found = bool(ERROR_WORDS_RE.search(nameish))

        # 3) hermanos/cercanos con clase error
        if not found and soup is not None:
            try:
                el = None
                cid = _get_attr(n, "id")
                if cid:
                    el = soup.find(id=cid)
                if el is None:
                    nm = _get_attr(n, "name")
                    if nm:
                        el = soup.find(attrs={"name": nm})
                if el is not None:
                    # busca hermanos <span|div> con clase error|invalid
                    sibs = list(el.find_all_next(limit=3))
                    for s in sibs:
                        cls = _get_attr(s, "class") or ""
                        txt = _get_text(s)
                        if re.search(r"(error|invalid|help|message)", cls, re.I) and ERROR_WORDS_RE.search(txt or ""):
                            found = True
                            break
            except Exception:
                pass

        if found:
            with_message += 1
        else:
            missing_message += 1
            offenders.append({
                "id": _s(n.get("id")), "name": _s(n.get("name")), "tag": _s(n.get("tag")),
                "reason": "aria-invalid='true' sin mensaje de error identificable (aria-describedby o cercano)."
            })

    details: Dict[str, Any] = {
        "applicable": applicable,
        "with_message": with_message,
        "missing_message": missing_message,
        "has_alert_region": _has_alert_region(soup),
        "ok_ratio": 1.0 if applicable == 0 else (1.0 if missing_message == 0 else max(0.0, min(1.0, with_message / max(1, applicable)))),
        "offenders": offenders,
        "note": (
            "RAW: se revisan controles con aria-invalid='true' y presencia de mensaje de error (aria-describedby, texto cercano o clases 'error'). "
            "role='alert'/aria-live se informa como apoyo, no obligatorio para aprobar."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    rctx.error_identification_test = [
      { "selector": str, "invalid": bool, "has_error_message": bool,
        "message_text": str|None, "via": "describedby|inline|alert|other" }
    ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 3.3.1; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "error_identification_test", []))
    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = d.get("note","") + " | RENDERED: sin 'error_identification_test', se reusó RAW."
        return d

    applicable = 0
    with_message = 0
    missing_message = 0
    offenders: List[Dict[str, Any]] = []

    for it in data:
        if not isinstance(it, dict): continue
        if not bool(it.get("invalid")): continue
        applicable += 1
        if bool(it.get("has_error_message")):
            with_message += 1
        else:
            missing_message += 1
            offenders.append({"selector": _s(it.get("selector")), "reason": "Campo inválido sin mensaje (runtime)."})

    ok_ratio = 1.0 if applicable == 0 else (1.0 if missing_message == 0 else max(0.0, min(1.0, with_message / max(1, applicable))))
    return {
        "rendered": True,
        "applicable": applicable,
        "with_message": with_message,
        "missing_message": missing_message,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: verificación explícita de mensajes de error cuando el campo es inválido."
    }

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False, "ai_message":"IA no configurada."}
    need = int(details.get("missing_message", 0) or 0) > 0
    if not need:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "offenders": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2200],
        "recipes": [
            "Añade <span id='email-error' class='error'>Ingresa un correo válido.</span> y enlázalo con aria-describedby.",
            "Usa role='alert' en contenedores de errores para lectores de pantalla.",
            "Evita mostrar solo color/ícono; incluye texto claro cerca del campo."
        ]
    }
    prompt = (
        "Eres auditor WCAG 3.3.1 (Error Identification, A). "
        "Genera mensajes de error textuales y cómo asociarlos a campos (aria-describedby). "
        "Devuelve JSON: { suggestions:[{field_id?, message, snippet, rationale}], manual_review?:bool, summary?:string }"
    )
    try:
        ans = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ans, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_3_3_1(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None
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
        manual_required = bool(ai.get("manual_required", False))

    applicable = int(details.get("applicable", 0) or 0)
    missing = int(details.get("missing_message", 0) or 0)
    
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
        level=meta.get("level","A"), principle=meta.get("principle","Comprensible"),
        title=meta.get("title","Identificación de errores"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
