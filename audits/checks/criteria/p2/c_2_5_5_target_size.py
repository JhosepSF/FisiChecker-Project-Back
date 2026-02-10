# audits/checks/criteria/p2/c_2_5_5_target_size.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.5.5"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

BTN_SM_RE = re.compile(r"\b(btn\-xs|btn\-sm|small|xs|tiny|chip|badge|tag|pill)\b", re.I)
ICON_ONLY_RE = re.compile(r"\b(icon\-only|only\-icon|btn\-icon|iconButton)\b", re.I)

def _as_list(x):
    if not x: return []
    if isinstance(x, list): return x
    return list(x)

def _s(v: Any) -> str:
    return "" if v is None else str(v)

def _lower(v: Any) -> str:
    return _s(v).strip().lower()

def _num(v: Any) -> Optional[float]:
    try:
        if v is None: return None
        if isinstance(v, (int, float)): return float(v)
        s = _s(v)
        if s == "": return None
        return float(s)
    except Exception:
        return None

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

def _get_text(node: Any) -> str:
    if isinstance(node, dict):
        for k in ("text","label","aria-label","title","inner_text","accessible_name"):
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

def _is_link_or_control(n: Dict[str, Any]) -> bool:
    tag = _lower(n.get("tag"))
    role = _lower(n.get("role"))
    href = _s(n.get("href"))
    t = _lower(n.get("type"))
    if tag in {"button","a","input","select","textarea","summary"}:
        if tag == "a":
            return bool(href)
        if tag == "input" and t in {"hidden","image"}:
            return False
        return True
    if role in {"button","link","switch","tab","menuitem","menuitemcheckbox","menuitemradio","option","slider","spinbutton"}:
        return True
    return False

# ------------------------------------------------------------
# RAW (heurístico)
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.5.5 (AAA): Los objetivos de puntero deben medir al menos 44x44 CSS px.
    RAW no puede medir tamaño; en su lugar marca sospechas:
      - clases 'btn-sm', 'icon-only', 'chip', 'badge', etc.
      - enlaces de 1 carácter (p. ej., números de paginación) o solo-ícono sin texto.
    Las sospechas no prueban fallo, pero se cuentan como 'violations_suspicions' (estricto AAA).
    """
    anchors = [n for n in _as_list(getattr(ctx, "anchors", [])) if isinstance(n, dict)]
    buttons = [n for n in _as_list(getattr(ctx, "buttons", [])) if isinstance(n, dict)]
    inputs  = [n for n in _as_list(getattr(ctx, "inputs", [])) if isinstance(n, dict)]
    nodes = anchors + buttons + inputs

    applicable = 0
    suspicions = 0
    offenders: List[Dict[str, Any]] = []

    for n in nodes:
        if not _is_link_or_control(n):
            continue
        applicable += 1

        cls = _s(n.get("class"))
        text = _get_text(n)
        icon_hint = ICON_ONLY_RE.search(cls) or re.search(r"^\s*(?:[•·]|)$", text) or len(text.strip()) <= 1

        if BTN_SM_RE.search(cls) or icon_hint:
            suspicions += 1
            offenders.append({
                "selector": _s(n.get("selector") or n.get("id") or n.get("name")),
                "tag": _s(n.get("tag")),
                "class": cls[:160],
                "text": text[:60],
                "reason": "Sospecha de objetivo pequeño (clase 'sm'/icon-only/texto mínimo)."
            })

    ok_ratio = 1.0 if applicable == 0 else (0.0 if suspicions > 0 else 1.0)

    details: Dict[str, Any] = {
        "applicable": 1 if applicable > 0 else 0,
        "targets_examined": applicable,
        "violations_suspicions": suspicions,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: sin tamaño computable. Se marcan sospechas (clases 'btn-sm', 'icon-only', chips, badges, "
            "o enlaces de 1 carácter). Valida realmente en RENDERED con bounding boxes."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED (medición real)
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    El extractor puede aportar:
      rctx.target_size_test = [
        { "selector": str, "tag": str|None, "role": str|None,
          "width": float, "height": float,                 # CSS px (bounding box)
          "is_inline_link": bool, "in_sentence": bool,     # excepción "inline"
          "user_agent_control": bool,                      # excepción UA
          "essential": bool,                               # excepción esencial
          "has_equivalent_target": bool,                   # excepción: hay otro objetivo >=44x44
          "notes": str|None }
      ]
    Violación si min(width,height) < 44 y NO aplica ninguna excepción (inline, UA, essential, equivalente).
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.5.5; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "target_size_test", []))
    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = (d.get("note","") + " | RENDERED: sin 'target_size_test', se reusó RAW.").strip()
        return d

    applicable = 0
    ok = 0
    small = 0
    exceptions = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for it in data:
        if not isinstance(it, dict):
            continue
        w = _num(it.get("width")) or 0.0
        h = _num(it.get("height")) or 0.0
        if w <= 0.0 or h <= 0.0:
            continue

        applicable += 1
        is_small = (w < 44.0 or h < 44.0)
        if not is_small:
            ok += 1
            continue

        small += 1

        is_inline = bool(it.get("is_inline_link") or it.get("in_sentence"))
        ua = bool(it.get("user_agent_control"))
        essential = bool(it.get("essential"))
        has_equiv = bool(it.get("has_equivalent_target"))

        if is_inline or ua or essential or has_equiv:
            exceptions += 1
        else:
            violations += 1
            offenders.append({
                "selector": _s(it.get("selector")),
                "width": w, "height": h,
                "reason": "Objetivo < 44x44 sin excepción aplicable."
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, (ok + exceptions) / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "rendered": True,
        "targets_examined": applicable,
        "targets_ok": ok,
        "targets_small": small,
        "exceptions": exceptions,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: medición de bounding boxes y evaluación de excepciones (inline, UA control, esencial, equivalente)."
    }
    return details

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    needs = (details.get("violations", 0) or 0) > 0 or (details.get("violations_suspicions", 0) or 0) > 0
    if not needs:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "offenders": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2200],
        "recipes": [
            "Aumentar padding para alcanzar 44x44px; evitar solo aumentar font-size.",
            "Usar hit-area con ::before/::after posicionados para ampliar el objetivo.",
            "Para enlaces inline repetidos, proporcionar alternativa equivalente más grande (por ejemplo, botón 'Leer el artículo')."
        ]
    }
    prompt = (
        "Eres auditor WCAG 2.5.5 (Target Size, AAA). "
        "Propón cambios para llevar objetivos a >=44x44 o proporcionar equivalentes, justificando la excepción si aplica. "
        "Devuelve JSON: { suggestions: [{selector?, css_or_html, rationale}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_2_5_5(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None
) -> CriterionOutcome:

    if mode == CheckMode.RENDERED:
        if rendered_ctx is None:
            details = _compute_counts_raw(ctx); details["warning"] = "Se pidió RENDERED sin rendered_ctx; fallback a RAW."
            src = "raw"
        else:
            details = _compute_counts_rendered(rendered_ctx); src = "rendered"
    else:
        details = _compute_counts_raw(ctx); src = "raw"

    manual_required = False
    if mode == CheckMode.AI:
        ai_info = _ai_review(details, html_sample=html_for_ai)
        details["ai_info"] = ai_info; src = "ai"
        manual_required = bool(ai_info.get("manual_review", False))

    applicable = int(details.get("targets_examined", 0) or 0)
    violations = int(details.get("violations", 0) or 0) + int(details.get("violations_suspicions", 0) or 0)
    
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
    score0 = score_from_verdict(verdict)

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0, details=details,
        level=meta.get("level", "AAA"), principle=meta.get("principle", "Operable"),
        title=meta.get("title", "Tamaño del objetivo"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
