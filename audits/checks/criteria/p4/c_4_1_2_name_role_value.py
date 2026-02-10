# audits/checks/criteria/p4/c_4_1_2_name_role_value.py
from typing import Dict, Any, List, Optional, Tuple, Set
import re
import unicodedata

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "4.1.2"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

# Conjunto minimalista de roles de widgets y si requieren nombre accesible
ROLES_NAME_REQUIRED: Dict[str, bool] = {
    # controles activables
    "button": True, "link": True, "switch": True, "checkbox": True, "radio": True,
    "tab": True, "menuitem": True, "menuitemcheckbox": True, "menuitemradio": True,
    # entradas/edición
    "textbox": True, "searchbox": True, "combobox": True, "spinbutton": True, "slider": True,
    "option": True,
    # agrupaciones con nombre visible (normalmente)
    "group": False, "radiogroup": False, "tablist": False, "toolbar": False,
    # informativos
    "progressbar": False, "timer": False, "status": False, "alert": False, "dialog": False,
}

# Estados/propiedades requeridos por rol (mínimo viable)
ROLE_REQUIRED_STATES: Dict[str, List[str]] = {
    "checkbox": ["aria-checked"],
    "switch": ["aria-checked"],
    "radio": ["aria-checked"],
    "option": ["aria-selected"],
    "tab": ["aria-selected"],
    "slider": ["aria-valuemin", "aria-valuemax", "aria-valuenow"],
    "spinbutton": ["aria-valuemin", "aria-valuemax", "aria-valuenow"],
    "progressbar": ["aria-valuemin", "aria-valuemax", "aria-valuenow"],
}

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
            if val is None: return None
            if isinstance(val, list):
                return " ".join([_s(x) for x in val])
            return _s(val)
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

def _accessible_name(node: Dict[str, Any], soup, labels_for: Dict[str, str]) -> str:
    # 1) aria-label
    al = _get_attr(node, "aria-label")
    if al and al.strip(): return al.strip()
    # 2) aria-labelledby
    ll = _get_attr(node, "aria-labelledby")
    if ll:
        txt = _resolve_ids_text(soup, ll)
        if txt.strip(): return txt.strip()
    # 3) label for
    cid = _get_attr(node, "id") or ""
    if cid and labels_for.get(cid, "").strip():
        return labels_for[cid].strip()
    # 4) contenido textual visible
    return _get_text(node)

def _is_widget(node: Dict[str, Any]) -> bool:
    tag = _lower(node.get("tag"))
    role = _lower(node.get("role"))
    if role: 
        return True
    if tag in {"input","button","select","textarea"}:
        return True
    # elementos custom potencialmente interactivos
    cls = _get_attr(node, "class") or ""
    if re.search(r"\b(button|btn|link|toggle|switch|tab)\b", cls, re.I):
        return True
    return False

def _role_of(node: Dict[str, Any]) -> str:
    role = _lower(node.get("role"))
    if role: return role
    tag = _lower(node.get("tag"))
    t = _lower(node.get("type"))
    # mapear nativos comunes
    if tag == "a" and (_get_attr(node, "href") or ""):
        return "link"
    if tag == "button":
        return "button"
    if tag == "input":
        if t in {"button","submit","reset","image"}: return "button"
        if t in {"checkbox"}: return "checkbox"
        if t in {"radio"}: return "radio"
        # text, search, email, etc
        return "textbox"
    if tag in {"select"}:
        return "combobox"  # heurístico
    if tag in {"textarea"}:
        return "textbox"
    return role or ""

def _has_required_states(role: str, node: Dict[str, Any]) -> bool:
    reqs = ROLE_REQUIRED_STATES.get(role, [])
    for r in reqs:
        if _get_attr(node, r) is None:
            return False
    return True

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    4.1.2 (A) — Nombre, Rol, Valor:
      - Para widgets (role o controles nativos), el nombre accesible y el rol deben ser determinables.
      - Para roles que lo requieren, estados/propiedades (valor) deben exponerse (aria-checked, -selected, -valuenow...).
    """
    soup = getattr(ctx, "soup", None)
    labels_for = getattr(ctx, "labels_for", {}) or {}
    nodes: List[Dict[str, Any]] = []
    nodes += [n for n in _as_list(getattr(ctx, "buttons", [])) if isinstance(n, dict)]
    nodes += [n for n in _as_list(getattr(ctx, "anchors", [])) if isinstance(n, dict)]
    nodes += [n for n in _as_list(getattr(ctx, "inputs",  [])) if isinstance(n, dict)]
    nodes += [n for n in _as_list(getattr(ctx, "widgets", [])) if isinstance(n, dict)]

    applicable = 0
    with_name = 0
    with_role = 0
    with_required_states = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for n in nodes:
        if not _is_widget(n):
            continue
        applicable += 1

        role = _role_of(n)
        name = _accessible_name(n, soup, labels_for)
        need_name = ROLES_NAME_REQUIRED.get(role, False)

        # nombre
        has_name = bool(name.strip()) if need_name else True
        # rol
        has_role = bool(role)

        # estados/valor
        has_states = True
        if role in ROLE_REQUIRED_STATES:
            has_states = _has_required_states(role, n)

        if has_name: with_name += 1
        if has_role: with_role += 1
        if has_states: with_required_states += 1

        # marcar fallas
        local_viol = False
        if not has_role:
            local_viol = True
            offenders.append({
                "selector": _s(n.get("selector") or n.get("id") or n.get("name")),
                "reason": "Rol no determinable (custom sin role y no nativo).",
                "tag": _s(n.get("tag"))
            })
        if not has_name:
            local_viol = True
            offenders.append({
                "selector": _s(n.get("selector") or n.get("id") or n.get("name")),
                "reason": f"Falta nombre accesible para rol '{role}'.",
                "tag": _s(n.get("tag"))
            })
        if not has_states:
            local_viol = True
            offenders.append({
                "selector": _s(n.get("selector") or n.get("id") or n.get("name")),
                "reason": f"Rol '{role}' sin estados/propiedades requeridos ({', '.join(ROLE_REQUIRED_STATES.get(role, []))}).",
                "tag": _s(n.get("tag"))
            })
        if local_viol:
            violations += 1

    ok_ratio = 1.0 if applicable == 0 else max(0.0, min(1.0, (with_name + with_role + with_required_states) / max(1, (3*applicable))))

    details: Dict[str, Any] = {
        "applicable": applicable,
        "with_name": with_name,
        "with_role": with_role,
        "with_required_states": with_required_states,
        "violations": violations,
        "ok_ratio": round(ok_ratio, 4),
        "offenders": offenders,
        "note": (
            "RAW: verifica nombre/rol/valor en widgets (nativos o con role). "
            "Conjunto mínimo de roles y estados requeridos; confirmar en RENDERED cambios dinámicos."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    rctx.name_role_value_test = [
      { "selector": str, "role": str, "accessible_name": str|None,
        "required_states": List[str], "states_present": bool, "notes": str|None }
    ]
    Falla si role vacío, o si name requerido está vacío, o si states_present=False cuando required_states no vacío.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 4.1.2; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "name_role_value_test", []))
    if not data:
        d = _compute_counts_raw(rctx); d["rendered"]=True
        d["note"] = d.get("note","") + " | RENDERED: sin 'name_role_value_test', se reusó RAW."
        return d

    applicable = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for it in data:
        if not isinstance(it, dict): continue
        applicable += 1
        role = _lower(it.get("role"))
        name = _s(it.get("accessible_name"))
        req = [r for r in _as_list(it.get("required_states")) if isinstance(r, str)]
        has_states = bool(it.get("states_present"))

        need_name = ROLES_NAME_REQUIRED.get(role, False)
        has_role = bool(role)
        has_name = bool(name.strip()) if need_name else True

        if not has_role or not has_name or (req and not has_states):
            violations += 1
            offenders.append({
                "selector": _s(it.get("selector")),
                "role": role,
                "reason": "name/role/value incompleto.",
                "required_states": req,
                "states_present": has_states,
                "notes": _s(it.get("notes"))
            })

    ok_ratio = 1.0 if applicable == 0 else (1.0 if violations == 0 else 0.0)
    return {
        "rendered": True,
        "applicable": applicable,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: verificación explícita aportada por extractor."
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
        "offenders": (details.get("offenders", []) or [])[:25],
        "role_required_states": ROLE_REQUIRED_STATES,
        "html_snippet": (html_sample or "")[:2400]
    }
    prompt = (
        "Eres auditor WCAG 4.1.2 (Name, Role, Value). "
        "Para cada offender, sugiere cómo añadir role/nombre y estados ARIA requeridos. "
        "Devuelve JSON: {suggestions:[{selector?, change, snippet?, rationale}], manual_review?:bool}"
    )
    try:
        ans = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ans, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_4_1_2(
    ctx: PageContext,
    mode: CheckMode=CheckMode.RAW,
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
        manual_required=bool(ai.get("manual_review", False))

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
    score0=score_from_verdict(verdict)
    meta=WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0, details=details,
        level=meta.get("level","A"), principle=meta.get("principle","Robusto"),
        title=meta.get("title","Nombre, rol, valor"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
