# audits/checks/criteria/p3/c_3_2_3_consistent_navigation.py
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

CODE = "3.2.3"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

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
    # normaliza para comparar "Inicio", "INICIO", "  inicio "
    t = unicodedata.normalize("NFKD", s or "").encode("ascii","ignore").decode("ascii")
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t

def _canon_href(href: Optional[str]) -> str:
    h = _s(href)
    if not h: return ""
    # quita query y hash
    h = h.split("#")[0].split("?")[0]
    # normaliza trailing slash
    if h.endswith("/") and len(h) > 1:
        h = h[:-1]
    return h

def _collect_nav_sequence(ctx: PageContext) -> List[str]:
    """
    Devuelve una "firma" lineal de la navegación principal encontrada
    (links dentro de <nav>, [role=navigation], header/banner y footer).
    Cada item es "name|href".
    """
    soup = getattr(ctx, "soup", None)
    if soup is None:
        # Fallback: usa anchors de ctx en orden de aparición
        seq: List[str] = []
        for a in _as_list(getattr(ctx, "anchors", [])):
            if not isinstance(a, dict): continue
            txt = _canon_name(_get_text(a))
            href = _canon_href(_get_attr(a, "href"))
            if not href: continue
            if txt or href:
                seq.append(f"{txt}|{href}")
        return seq[:120]

    nodes = []  # type: List[Any]
    try:
        nodes += _as_list(soup.find_all("nav"))
    except Exception: pass
    try:
        nodes += _as_list(soup.find_all(attrs={"role":"navigation"}))
    except Exception: pass
    try:
        nodes += _as_list(soup.find_all(["header","footer"]))
    except Exception: pass

    seen: Set[str] = set()
    seq: List[str] = []
    for container in nodes:
        try:
            for a in container.find_all("a"):
                href = _canon_href(a.get("href"))  # type: ignore[attr-defined]
                if not href: continue
                name = _canon_name(_s(getattr(a, "get_text", lambda: "")()))  # type: ignore[misc]
                key = f"{name}|{href}"
                if key in seen: 
                    continue
                seen.add(key)
                seq.append(key)
        except Exception:
            continue
    # si nada en landmarks, cae a todos los anchors
    if not seq:
        for a in _as_list(getattr(ctx, "anchors", [])):
            if not isinstance(a, dict): continue
            txt = _canon_name(_get_text(a))
            href = _canon_href(_get_attr(a, "href"))
            if not href: continue
            seq.append(f"{txt}|{href}")
    return seq[:200]

def _inversion_count(order_ref: Dict[str, int], seq: List[str]) -> int:
    """
    Cuenta inversiones de orden relativo para los elementos comunes entre order_ref y seq.
    """
    # filtra a comunes
    common = [it for it in seq if it in order_ref]
    count = 0
    for i in range(len(common)):
        for j in range(i+1, len(common)):
            if order_ref[common[i]] > order_ref[common[j]]:
                count += 1
    return count

# ------------------------------------------------------------
# RAW (heurístico con historial opcional)
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    3.2.3 (AA): Los mecanismos de navegación recurrentes deben presentarse en el mismo
    orden relativo cada vez que aparecen.
    RAW:
      - Calcula una 'firma' de navegación actual (secuencia de name|href).
      - Si se provee historial en ctx.nav_history_signatures (List[List[str]]), compara el orden relativo
        y reporta inversiones (cambios de orden).
      - Sin historial: NA operativa, pero se entrega 'signature' para consolidación por el runner.
    """
    sig = _collect_nav_sequence(ctx)
    history = _as_list(getattr(ctx, "nav_history_signatures", []))

    applicable = 1 if history else 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    if history:
        # comparamos contra cada firma previa, sumamos inversiones
        for idx, prev in enumerate(history[:10]):
            order_ref = {v: i for i, v in enumerate(prev)}
            inv = _inversion_count(order_ref, sig)
            if inv > 0:
                violations += inv
                offenders.append({"history_index": idx, "inversions": inv, "reason": "Cambio de orden relativo respecto a la firma histórica."})

    ok_ratio = 1.0 if applicable == 0 else (1.0 if violations == 0 else 0.0)
    details: Dict[str, Any] = {
        "applicable": applicable,
        "signature": sig,
        "history_count": len(history),
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: firma de navegación derivada de landmarks (<nav>, role=navigation, header/footer). "
            "Si se provee historial (ctx.nav_history_signatures), se cuentan inversiones del orden relativo."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    rctx.consistent_navigation_test = {
      "current_signature": List[str],  # ["inicio|/","productos|/shop", ...]
      "history_signatures": List[List[str]]  # firmas previas (misma normalización)
    }
    Violación = inversiones > 0 frente a cualquiera de las firmas previas relevantes.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 3.2.3; no se pudo evaluar en modo renderizado."}

    data = getattr(rctx, "consistent_navigation_test", None)
    if not isinstance(data, dict):
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = d.get("note","") + " | RENDERED: sin 'consistent_navigation_test', se reusó RAW."
        return d

    sig = [s for s in _as_list(data.get("current_signature")) if isinstance(s, str)]
    hist = [ [s for s in _as_list(h) if isinstance(s, str)] for h in _as_list(data.get("history_signatures")) ]

    applicable = 1 if hist else 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    if hist:
        for idx, prev in enumerate(hist[:15]):
            order_ref = {v: i for i, v in enumerate(prev)}
            inv = _inversion_count(order_ref, sig)
            if inv > 0:
                violations += inv
                offenders.append({"history_index": idx, "inversions": inv, "reason": "Cambio de orden relativo (runtime)."})

    ok_ratio = 1.0 if applicable == 0 else (1.0 if violations == 0 else 0.0)
    return {
        "rendered": True,
        "applicable": applicable,
        "signature": sig,
        "history_count": len(hist),
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: comparación directa contra firmas históricas provistas por el extractor."
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
        "signature": details.get("signature", []),
        "offenders": (details.get("offenders", []) or [])[:10],
        "guideline": "Mantener orden consistente de navegación (3.2.3 AA)."
    }
    prompt = (
        "Eres auditor WCAG 3.2.3 (Consistent Navigation). "
        "Propón un orden de navegación canónico y un snippet HTML para alinear el orden actual. "
        "Devuelve JSON: {suggestions:[{canonical_order: string[], rationale, snippet?}], manual_review?: bool}"
    )
    try:
        ans = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ans, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_3_2_3(
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
    violations = int(details.get("violations", 0) or 0)
    passed = (applicable == 0) or (violations == 0)

    verdict = verdict_from_counts(details, passed)
    score0  = score_from_verdict(verdict)
    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0, details=details,
        level=meta.get("level","AA"), principle=meta.get("principle","Comprensible"),
        title=meta.get("title","Navegación consistente"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
