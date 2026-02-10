# audits/checks/criteria/p3/c_3_2_1_on_focus.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "3.2.1"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

NAV_JS_RE = re.compile(
    r"(location\.(href|assign|replace)\s*=|document\.location|window\.open\s*\(|"
    r"history\.(pushState|replaceState)\s*\(|router\.(push|replace)\s*\()",
    re.I,
)
SUBMIT_RE = re.compile(r"\.submit\s*\(", re.I)
FOCUS_HANDLER_RE = re.compile(r"(onfocus\s*=|addEventListener\s*\(\s*['\"]focus['\"])", re.I)

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
            val = node.get(name); return _s(val) if val is not None else None
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

def _scripts_text(ctx: PageContext) -> str:
    st = _s(getattr(ctx, "scripts_text", ""))
    if st: return st
    soup = getattr(ctx, "soup", None)
    if soup is None: return ""
    out: List[str] = []
    try:
        for sc in soup.find_all("script"):
            try:
                txt = sc.get_text()  # type: ignore[attr-defined]
                if isinstance(txt, str) and txt.strip():
                    out.append(txt)
            except Exception:
                continue
    except Exception:
        pass
    return "\n".join(out)

def _is_interactive(node: Dict[str, Any]) -> bool:
    tag = _lower(node.get("tag"))
    role = _lower(node.get("role"))
    t = _lower(node.get("type"))
    href = _s(node.get("href"))
    if tag in {"a","button","input","select","textarea"}:
        if tag == "a": return bool(href)
        if tag == "input" and t in {"hidden"}: return False
        return True
    if role in {"button","link","textbox","combobox","listbox","switch","tab","menuitem"}:
        return True
    return False

def _find_parent_form_has_submit(soup, el) -> bool:
    if soup is None or el is None: return False
    try:
        parent = getattr(el, "parent", None)
        depth = 0
        while parent is not None and depth < 5:
            if getattr(parent, "name", "") == "form":
                # busca botones submit dentro del form
                for b in parent.find_all(["button","input"]):
                    try:
                        if getattr(b, "name", "") == "button" and (b.get("type") or "").lower() in {"submit","image"}:  # type: ignore[attr-defined]
                            return True
                        if getattr(b, "name", "") == "input" and (b.get("type") or "").lower() in {"submit","image"}:   # type: ignore[attr-defined]
                            return True
                    except Exception:
                        continue
                return False
            parent = getattr(parent, "parent", None); depth += 1
    except Exception:
        pass
    return False

# ------------------------------------------------------------
# RAW (heurístico)
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    3.2.1 (A): Al recibir foco, un componente NO debe iniciar un cambio de contexto (navegar, enviar, abrir modal).
    RAW:
      - Marca elementos con 'onfocus' que ejecuten navegación / submit.
      - Revisa scripts globales buscando listeners 'focus' que hagan navegación/submit.
    """
    soup = getattr(ctx, "soup", None)
    anchors = [n for n in _as_list(getattr(ctx, "anchors", [])) if isinstance(n, dict)]
    buttons = [n for n in _as_list(getattr(ctx, "buttons", [])) if isinstance(n, dict)]
    inputs  = [n for n in _as_list(getattr(ctx, "inputs", [])) if isinstance(n, dict)]
    nodes = anchors + buttons + inputs

    applicable = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    # 1) Atributo inline 'onfocus'
    for n in nodes:
        if not _is_interactive(n):
            continue
        applicable += 1
        of = _get_attr(n, "onfocus")
        if of and (NAV_JS_RE.search(of) or SUBMIT_RE.search(of)):
            violations += 1
            offenders.append({
                "selector": _s(n.get("selector") or n.get("id") or n.get("name")),
                "tag": _s(n.get("tag")), "reason": "onfocus inicia navegación o submit.",
                "snippet": of[:160]
            })

    # 2) JS global con focus + nav/submit
    scripts = _scripts_text(ctx)
    if FOCUS_HANDLER_RE.search(scripts) and (NAV_JS_RE.search(scripts) or SUBMIT_RE.search(scripts)):
        # señal global — sin mapear a un nodo concreto
        violations += 1
        offenders.append({"reason": "Scripts escuchan 'focus' y pueden navegar/enviar (heurístico).", "evidence": "scripts"})

    ok_ratio = 1.0 if applicable == 0 else (0.0 if violations > 0 else 1.0)

    details: Dict[str, Any] = {
        "applicable": 1 if applicable > 0 else 0,
        "targets_examined": applicable,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: se marcan 'onfocus' y listeners de focus que provocan navegación/submit. "
            "Confirmar en RENDERED si hay dudas."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED (prueba de foco)
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    El extractor puede aportar:
      rctx.focus_change_test = [
        { "selector": str, "triggers_navigation_on_focus": bool,
          "triggers_submit_on_focus": bool, "triggers_modal_on_focus": bool, "notes": str|None }
      ]
    Violación si cualquiera de las flags es True.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 3.2.1; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "focus_change_test", []))
    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = (d.get("note","") + " | RENDERED: sin 'focus_change_test', se reusó RAW.").strip()
        return d

    applicable = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for it in data:
        if not isinstance(it, dict): continue
        applicable += 1
        if bool(it.get("triggers_navigation_on_focus")) or bool(it.get("triggers_submit_on_focus")) or bool(it.get("triggers_modal_on_focus")):
            violations += 1
            offenders.append({
                "selector": _s(it.get("selector")),
                "reason": "Cambio de contexto al recibir foco (runtime).",
                "notes": _s(it.get("notes"))
            })

    ok_ratio = 1.0 if applicable == 0 else (1.0 if violations == 0 else 0.0)
    details: Dict[str, Any] = {
        "rendered": True,
        "targets_examined": applicable,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: verificación de cambios de contexto al foco."
    }
    return details

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False, "ai_message": "IA no configurada."}
    need = (details.get("violations", 0) or 0) > 0
    if not need:
        return {"ai_used": False, "manual_required": False}
    ctx_json = {
        "offenders": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2200],
        "recipes": [
            "Mover la lógica de navegación al evento 'click' o a un botón explícito.",
            "Evitar submit en 'focus'; usar botón 'Enviar' o 'Continuar'.",
            "Si es imprescindible, añadir confirmación antes del cambio de contexto."
        ]
    }
    prompt = (
        "Eres auditor WCAG 3.2.1 (On Focus, A). "
        "Proporciona cambios para eliminar navegación/envío al foco. "
        "Devuelve JSON: { suggestions:[{selector?, change, snippet?, rationale}], manual_review?:bool, summary?:string }"
    )
    try:
        ai = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_3_2_1(
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

    violations = int(details.get("violations", 0) or 0)
    applicable = int(details.get("targets_examined", 0) or details.get("applicable", 0) or 0)
    passed = (applicable == 0) or (violations == 0)

    verdict = verdict_from_counts(details, passed)
    score0 = score_from_verdict(verdict)
    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0, details=details,
        level=meta.get("level","A"), principle=meta.get("principle","Comprensible"),
        title=meta.get("title","Al recibir foco"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
