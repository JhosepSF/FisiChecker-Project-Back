# audits/checks/criteria/p3/c_3_2_4_consistent_identification.py
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

CODE = "3.2.4"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

URL_RE = re.compile(r"https?://", re.I)

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

def _get_text(node: Any) -> str:
    if isinstance(node, dict):
        for k in ("aria-label","title","text","inner_text","label"):
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

def _canon_name(s: str) -> str:
    t = unicodedata.normalize("NFKD", s or "").encode("ascii","ignore").decode("ascii")
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t

def _canon_href(href: Optional[str]) -> str:
    h = _s(href)
    if not h: return ""
    h = h.split("#")[0]
    h = h.split("?")[0]
    if h.endswith("/") and len(h) > 1: h = h[:-1]
    # quitar dominio si lo hay
    if URL_RE.match(h):
        try:
            from urllib.parse import urlparse
            p = urlparse(h)
            h = p.path or "/"
        except Exception:
            pass
    return h or "/"

def _action_key_for_control(n: Dict[str, Any]) -> str:
    """
    Intenta derivar una 'clave de acción' para anclas y botones/inputs:
      - href (normalizado)
      - formaction / data-action / data-target / aria-controls
      - onclick con URL (muy heurístico)
    """
    tag = _lower(n.get("tag"))
    href = _canon_href(_get_attr(n, "href"))
    if tag == "a" and href:
        return f"href:{href}"
    for k in ("formaction", "data-action", "data-target", "aria-controls"):
        v = _get_attr(n, k)
        if v: return f"{k}:{_canon_name(v)}"
    oc = _get_attr(n, "onclick") or ""
    m = re.search(r"(https?://[^\s'\";]+|/[^\s'\";]+)", oc, re.I)
    if m:
        return f"onclick:{_canon_href(m.group(1))}"
    # fallback: role + type
    role = _lower(n.get("role"))
    t = _lower(n.get("type"))
    if role or t:
        return f"{role or 'ctrl'}:{t or tag}"
    return tag or "control"

def _accessible_name(n: Dict[str, Any]) -> str:
    # prioridad a aria-label/title, luego texto
    name = _get_attr(n, "aria-label") or _get_attr(n, "title") or _s(n.get("text") or n.get("inner_text") or "")
    if not name:
        name = _s(n.get("label") or n.get("name") or n.get("id") or "")
    return _canon_name(name)

def _is_interactive(n: Dict[str, Any]) -> bool:
    tag = _lower(n.get("tag"))
    role = _lower(n.get("role"))
    t = _lower(n.get("type"))
    href = _s(n.get("href"))
    if tag in {"a","button","input","select","textarea"}:
        if tag == "a": return bool(href)
        if tag == "input" and t in {"hidden"}: return False
        return True
    if role in {"button","link","switch","tab","menuitem","option","slider","spinbutton"}:
        return True
    return False

# ------------------------------------------------------------
# RAW (en una sola página)
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    3.2.4 (AA): Componentes con la misma funcionalidad deben identificarse de la misma manera.
    RAW (una página):
      - Agrupa anclas por destino (href normalizado) y compara los nombres accesibles.
      - Agrupa controles por 'clave de acción' (formaction/data-action/onclick URL/aria-controls).
      - Si hay ≥2 nombres distintos para la misma clave → inconsistencia.
    """
    anchors = [n for n in _as_list(getattr(ctx, "anchors", [])) if isinstance(n, dict)]
    buttons = [n for n in _as_list(getattr(ctx, "buttons", [])) if isinstance(n, dict)]
    inputs  = [n for n in _as_list(getattr(ctx, "inputs",  [])) if isinstance(n, dict)]
    nodes = anchors + buttons + inputs

    groups: Dict[str, Set[str]] = {}
    sample: Dict[str, List[Dict[str, Any]]] = {}

    applicable = 0
    for n in nodes:
        if not _is_interactive(n): 
            continue
        applicable += 1
        key = _action_key_for_control(n)
        name = _accessible_name(n)
        if key not in groups:
            groups[key] = set()
            sample[key] = []
        groups[key].add(name)
        if len(sample[key]) < 5:
            sample[key].append({
                "selector": _s(n.get("selector") or n.get("id") or n.get("name")),
                "tag": _s(n.get("tag")), "name": name
            })

    offenders: List[Dict[str, Any]] = []
    violations = 0
    for key, names in groups.items():
        # ignora claves con un solo uso
        if sum(1 for _ in sample.get(key, [])) < 2:
            continue
        # si hay 2+ nombres distintos no vacíos
        distinct = {n for n in names if n}
        if len(distinct) >= 2:
            violations += 1
            offenders.append({
                "action_key": key,
                "names": sorted(list(distinct))[:6],
                "examples": sample.get(key, [])[:5],
                "reason": "Misma funcionalidad con identificación distinta en la misma página."
            })

    ok_ratio = 1.0 if applicable == 0 else (1.0 if violations == 0 else 0.0)
    details: Dict[str, Any] = {
        "applicable": 1 if applicable > 0 else 0,
        "groups_examined": len(groups),
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: se agrupa por 'action_key' (href/formaction/data-action/onclick URL/aria-controls) y se comparan nombres accesibles. "
            "Si hay 2+ variantes para la misma acción, se marca inconsistencia."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED (comparación entre pantallas/páginas)
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    rctx.consistent_identification_test = [
      { "action_key": str, "names": List[str], "examples": List[{selector, tag, name}] }
    ]
    Violación si para una misma action_key hay 2+ nombres distintos (en conjunto de vistas auditadas).
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 3.2.4; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "consistent_identification_test", []))
    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = d.get("note","") + " | RENDERED: sin 'consistent_identification_test', se reusó RAW."
        return d

    violations = 0
    offenders: List[Dict[str, Any]] = []
    groups = 0
    for it in data:
        if not isinstance(it, dict): continue
        groups += 1
        names = { _s(n).strip().lower() for n in _as_list(it.get("names")) if isinstance(n, str) and _s(n).strip() }
        if len(names) >= 2:
            violations += 1
            offenders.append({
                "action_key": _s(it.get("action_key")),
                "names": sorted(list(names))[:8],
                "examples": _as_list(it.get("examples"))[:6],
                "reason": "Misma funcionalidad con identificación distinta (runtime/conjunto de vistas)."
            })

    ok_ratio = 1.0 if groups == 0 else (1.0 if violations == 0 else 0.0)
    return {
        "rendered": True,
        "groups_examined": groups,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: comparación de nombres accesibles por 'action_key' a través de vistas."
    }

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False, "ai_message": "IA no configurada."}
    need = int(details.get("violations", 0) or 0) > 0
    if not need:
        return {"ai_used": False, "manual_required": False}
    ctx_json = {
        "offenders": (details.get("offenders", []) or [])[:15],
        "html_snippet": (html_sample or "")[:2200],
        "guideline": "Usar el mismo nombre accesible para la misma funcionalidad (3.2.4 AA)."
    }
    prompt = (
        "Eres auditor WCAG 3.2.4 (Consistent Identification). "
        "Propón un nombre accesible canónico por 'action_key' y snippets para unificar (aria-label/title/texto). "
        "Devuelve JSON: {suggestions:[{action_key, canonical_name, snippet?, rationale}], manual_review?: bool}"
    )
    try:
        ans = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ans, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_3_2_4(
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

    groups = int(details.get("groups_examined", 0) or 0)
    violations = int(details.get("violations", 0) or 0)
    passed = (groups == 0) or (violations == 0)

    verdict = verdict_from_counts(details, passed)
    score0  = score_from_verdict(verdict)
    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0, details=details,
        level=meta.get("level","AA"), principle=meta.get("principle","Comprensible"),
        title=meta.get("title","Identificación consistente"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
