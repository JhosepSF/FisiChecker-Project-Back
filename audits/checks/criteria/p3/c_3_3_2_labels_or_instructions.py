# audits/checks/criteria/p3/c_3_3_2_labels_or_instructions.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "3.3.2"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

REQ_HINT_RE = re.compile(
    r"(campos?\s+obligatorios|requerid[oa]s?|required\s+fields?|indica[dn]\s+con\s+\*|\(requerido\)|\(obligatorio\)|"
    r"use\s+format|formato\s+requerido|ejemplo|example)",
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

def _has_page_instructions(ctx: PageContext) -> bool:
    soup = getattr(ctx, "soup", None)
    if soup is None:
        return bool(REQ_HINT_RE.search(_s(getattr(ctx, "document_text",""))))
    try:
        txt = soup.get_text()  # type: ignore[attr-defined]
        return bool(REQ_HINT_RE.search(txt or ""))
    except Exception:
        return False

def _has_accessible_name(ctrl: Dict[str, Any], labels_for: Dict[str,str], soup) -> bool:
    # 1) label for
    cid = _get_attr(ctrl, "id") or ""
    if cid and cid in labels_for and labels_for.get(cid, "").strip():
        return True
    # 2) aria-label o title
    if _get_attr(ctrl, "aria-label") or _get_attr(ctrl, "title"):
        return True
    # 3) aria-labelledby resolviendo a texto
    al = _get_attr(ctrl, "aria-labelledby")
    if soup is not None and al:
        txt = _resolve_ids_text(soup, al)
        if txt.strip():
            return True
    # 4) placeholder solo NO es suficiente para el nombre accesible, pero cuenta como instrucción mínima
    return False

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

def _is_applicable_control(ctrl: Dict[str, Any]) -> bool:
    tag = _lower(ctrl.get("tag"))
    role = _lower(ctrl.get("role"))
    t = _lower(ctrl.get("type"))
    if tag in {"input","select","textarea"}:
        if tag == "input" and t in {"hidden","button","submit","reset","image"}:
            return False
        return True
    if role in {"textbox","combobox","listbox","spinbutton","slider","switch"}:
        return True
    return False

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    3.3.2 (A) — Se proporcionan etiquetas o instrucciones cuando el contenido requiere entrada de usuario.
    RAW:
      - Revisa nombre accesible (label for / aria-label / aria-labelledby).
      - Considera instrucciones de la página (indicaciones de obligatorio, formato, ejemplos).
      - Placeholder cuenta como instrucción mínima, NO como nombre accesible.
    """
    soup = getattr(ctx, "soup", None)
    labels_for = getattr(ctx, "labels_for", {}) or {}
    controls = [n for n in _as_list(getattr(ctx, "form_controls", []) or getattr(ctx, "inputs", [])) if isinstance(n, dict)]

    applicable = 0
    with_label = 0
    missing_label = 0
    placeholder_only = 0
    offenders: List[Dict[str, Any]] = []

    has_instructions = _has_page_instructions(ctx)

    for n in controls:
        if not _is_applicable_control(n):
            continue
        applicable += 1
        has_name = _has_accessible_name(n, labels_for, soup)
        ph = _s(n.get("placeholder")).strip()
        if has_name:
            with_label += 1
        else:
            if ph:
                placeholder_only += 1
                offenders.append({
                    "id": _s(n.get("id")), "name": _s(n.get("name")), "tag": _s(n.get("tag")),
                    "reason": "Solo placeholder (no es nombre accesible); añadir <label> o aria-label/labelledby."
                })
            else:
                missing_label += 1
                offenders.append({
                    "id": _s(n.get("id")), "name": _s(n.get("name")), "tag": _s(n.get("tag")),
                    "reason": "Falta etiqueta o instrucción asociada al control."
                })

    passed = (applicable == 0) or (missing_label == 0)
    ok_ratio = 1.0 if applicable == 0 else max(0.0, min(1.0, with_label / max(1, applicable)))

    details: Dict[str, Any] = {
        "applicable": applicable,
        "with_label": with_label,
        "missing_label": missing_label,
        "placeholder_only": placeholder_only,
        "has_page_instructions": has_instructions,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: exige nombre accesible por <label>/<aria-label>/<aria-labelledby>. "
            "El placeholder vale como instrucción pero no sustituye la etiqueta."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    rctx.labels_instructions_test = [
      { "selector": str, "has_accessible_name": bool, "placeholder_only": bool, "notes": str|None }
    ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 3.3.2; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "labels_instructions_test", []))
    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = d.get("note","") + " | RENDERED: sin 'labels_instructions_test', se reusó RAW."
        return d

    applicable = 0
    with_label = 0
    missing_label = 0
    placeholder_only = 0
    offenders: List[Dict[str, Any]] = []

    for it in data:
        if not isinstance(it, dict): continue
        applicable += 1
        if bool(it.get("has_accessible_name")):
            with_label += 1
        else:
            if bool(it.get("placeholder_only")):
                placeholder_only += 1
                offenders.append({"selector": _s(it.get("selector")), "reason": "Solo placeholder (no etiqueta).", "notes": _s(it.get("notes"))})
            else:
                missing_label += 1
                offenders.append({"selector": _s(it.get("selector")), "reason": "Falta etiqueta/instrucción.", "notes": _s(it.get("notes"))})

    ok_ratio = 1.0 if applicable == 0 else max(0.0, min(1.0, with_label / max(1, applicable)))
    return {
        "rendered": True,
        "applicable": applicable,
        "with_label": with_label,
        "missing_label": missing_label,
        "placeholder_only": placeholder_only,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: verificación directa de nombre accesible e instrucciones."
    }

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str]=None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False, "ai_message":"IA no configurada."}
    need = int(details.get("missing_label", 0) or 0) > 0 or int(details.get("placeholder_only", 0) or 0) > 0
    if not need:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "offenders": (details.get("offenders", []) or [])[:25],
        "html_snippet": (html_sample or "")[:2200],
        "recipes": [
            "<label for='phone'>Teléfono</label><input id='phone' name='phone' type='tel' aria-describedby='phone-hint'>",
            "<span id='phone-hint' class='hint'>Ej.: +51 987 654 321</span>",
            "Usa aria-labelledby cuando el texto visible actúa de etiqueta (p.ej., tarjeta con título)."
        ]
    }
    prompt = (
        "Eres auditor WCAG 3.3.2 (Labels or Instructions, A). "
        "Genera etiquetas/instrucciones claras y cómo asociarlas al control. "
        "Devuelve JSON: { suggestions:[{id?, name?, label_html?, hint_html?, rationale}], manual_review?:bool, summary?:string }"
    )
    try:
        ans = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ans, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_3_3_2(
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
    missing = int(details.get("missing_label", 0) or 0)
    
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
        title=meta.get("title","Etiquetas o instrucciones"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
