# audits/checks/criteria/p3/c_3_2_2_on_input.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "3.2.2"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

NAV_JS_RE = re.compile(
    r"(location\.(href|assign|replace)\s*=|document\.location|window\.open\s*\(|"
    r"history\.(pushState|replaceState)\s*\(|router\.(push|replace)\s*\()",
    re.I,
)
SUBMIT_RE = re.compile(r"\.submit\s*\(", re.I)
CHANGE_HANDLER_RE = re.compile(r"(onchange\s*=|addEventListener\s*\(\s*['\"]change['\"])", re.I)
WARNING_RE = re.compile(
    r"(se\s+(actualizar[aá]|redirigir[aá]|cambiar[aá])\s+autom[aá]ticamente|"
    r"cambia\s+inmediatamente|auto(\s*|\-)?submit|updates\s+automatically|"
    r"will\s+navigate|changes\s+immediately)",
    re.I,
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

def _is_form_control(n: Dict[str, Any]) -> bool:
    tag = _lower(n.get("tag"))
    role = _lower(n.get("role"))
    t = _lower(n.get("type"))
    if tag in {"input","select","textarea"}:
        if tag == "input" and t in {"hidden"}: return False
        return True
    if role in {"textbox","combobox","listbox","radio","checkbox","switch"}:
        return True
    return False

def _find_parent_form_has_submit_button(el) -> bool:
    # Busca un botón de envío en el form contenedor (en DOM estático)
    if el is None: return False
    try:
        parent = getattr(el, "parent", None)
        depth = 0
        while parent is not None and depth < 5:
            if getattr(parent, "name", "") == "form":
                # ¿hay botón submit?
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
    3.2.2 (A): Cambiar el valor de un control no debe causar cambio de contexto automáticamente,
    a menos que se avise previamente o exista un botón/confirmación explícita.
    RAW:
      - Marca 'onchange' que navegan/envían automáticamente.
      - Detecta advertencias textuales globales.
      - Verifica si el control está dentro de un <form> con botón submit (preferible a autosubmit).
    """
    soup = getattr(ctx, "soup", None)
    inputs  = [n for n in _as_list(getattr(ctx, "inputs", [])) if isinstance(n, dict)]
    selects = [n for n in inputs if _lower(n.get("tag")) == "select"] + [n for n in _as_list(getattr(ctx, "selects", [])) if isinstance(n, dict)]
    others  = [n for n in inputs if _lower(n.get("tag")) in {"input","textarea"}]
    nodes = selects + others

    page_txt = _page_text(ctx)
    has_global_warning = bool(WARNING_RE.search(page_txt))

    applicable = 0
    violations = 0
    warned = 0
    with_submit_avail = 0
    offenders: List[Dict[str, Any]] = []

    # 1) onChange inline
    for n in nodes:
        if not _is_form_control(n): continue
        applicable += 1
        oc = _get_attr(n, "onchange")
        if oc and (NAV_JS_RE.search(oc) or SUBMIT_RE.search(oc)):
            # ¿hay advertencia global o submit en form?
            warned_here = has_global_warning
            submit_here = False

            # si tenemos soup: intenta localizar nodo real por id/name para buscar <form> y botón submit
            if soup is not None:
                try:
                    sel_id = _get_attr(n, "id")
                    el = None
                    if sel_id:
                        el = soup.find(id=sel_id)
                    if el is None:
                        # fallback por name
                        nm = _get_attr(n, "name")
                        if nm: el = soup.find(attrs={"name": nm})
                    submit_here = _find_parent_form_has_submit_button(el)
                except Exception:
                    pass

            if warned_here:
                warned += 1
            elif submit_here:
                with_submit_avail += 1
            else:
                violations += 1
                offenders.append({
                    "selector": _s(n.get("selector") or n.get("id") or n.get("name")),
                    "tag": _s(n.get("tag")),
                    "reason": "onchange provoca navegación/envío sin aviso previo ni botón explícito.",
                    "snippet": oc[:160]
                })

    # 2) JS global: listeners 'change' con navegación/submit
    scripts = _scripts_text(ctx)
    if CHANGE_HANDLER_RE.search(scripts) and (NAV_JS_RE.search(scripts) or SUBMIT_RE.search(scripts)):
        # si hay advertencia global, no lo tratamos como violación directa, solo advertido
        if has_global_warning:
            warned += 1
        else:
            violations += 1
            offenders.append({"reason": "Scripts escuchan 'change' y pueden navegar/enviar (heurístico).", "evidence": "scripts"})

    ok_ratio = 1.0 if applicable == 0 else (0.0 if violations > 0 else 1.0)

    details: Dict[str, Any] = {
        "applicable": 1 if applicable > 0 else 0,
        "controls_examined": applicable,
        "violations": violations,
        "warned_cases": warned,
        "with_submit_available": with_submit_avail,
        "has_global_warning_text": has_global_warning,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: se marcan 'onchange' que causan navegación/submit. Se atenúa si hay aviso claro o botón submit en el form."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED (prueba de input)
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    El extractor puede aportar:
      rctx.input_change_test = [
        { "selector": str, "triggers_navigation_on_change": bool,
          "triggers_submit_on_change": bool,
          "has_prior_warning": bool, "has_submit_button": bool, "notes": str|None }
      ]
    Violación si 'triggers_*' es True y además no hay 'has_prior_warning' ni 'has_submit_button'.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 3.2.2; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "input_change_test", []))
    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = (d.get("note","") + " | RENDERED: sin 'input_change_test', se reusó RAW.").strip()
        return d

    applicable = 0
    violations = 0
    warned = 0
    with_submit = 0
    offenders: List[Dict[str, Any]] = []

    for it in data:
        if not isinstance(it, dict): continue
        applicable += 1
        trig = bool(it.get("triggers_navigation_on_change")) or bool(it.get("triggers_submit_on_change"))
        if not trig:
            continue
        warned_here = bool(it.get("has_prior_warning"))
        submit_here = bool(it.get("has_submit_button"))

        if warned_here:
            warned += 1
        elif submit_here:
            with_submit += 1
        else:
            violations += 1
            offenders.append({
                "selector": _s(it.get("selector")),
                "reason": "Cambio de contexto en 'change' sin aviso ni botón explícito (runtime).",
                "notes": _s(it.get("notes"))
            })

    ok_ratio = 1.0 if applicable == 0 else (1.0 if violations == 0 else 0.0)
    details: Dict[str, Any] = {
        "rendered": True,
        "controls_examined": applicable,
        "violations": violations,
        "warned_cases": warned,
        "with_submit_available": with_submit,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: detección de navegación/envío al cambiar valor y presencia de aviso/botón."
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
            "Eliminar lógica de navegación de 'onchange' y moverla al botón 'Ir'/'Aplicar'.",
            "Si debe cambiar de contexto en 'change', añadir aviso textual claro junto al control.",
            "Preferir un <button type='submit'> dentro del <form>."
        ]
    }
    prompt = (
        "Eres auditor WCAG 3.2.2 (On Input, A). "
        "Propón ajustes para evitar cambios de contexto automáticos en 'change' o añadir aviso/botón. "
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

def run_3_2_2(
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
        manual_required = bool(ai.get("manual_review", False))

    violations = int(details.get("violations", 0) or 0)
    applicable = int(details.get("controls_examined", 0) or details.get("applicable", 0) or 0)
    passed = (applicable == 0) or (violations == 0)

    verdict = verdict_from_counts(details, passed)
    score0 = score_from_verdict(verdict)
    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0, details=details,
        level=meta.get("level","A"), principle=meta.get("principle","Comprensible"),
        title=meta.get("title","Al introducir datos"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
