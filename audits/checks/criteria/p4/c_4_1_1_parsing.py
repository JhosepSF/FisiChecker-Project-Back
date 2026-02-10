# audits/checks/criteria/p4/c_4_1_1_parsing.py
from typing import Dict, Any, List, Optional, Tuple, Set
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "4.1.1"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

REF_ATTRS = ("for", "aria-labelledby", "aria-describedby", "headers")

def _as_list(x):
    if not x: return []
    if isinstance(x, list): return x
    return list(x)

def _s(v: Any) -> str:
    return "" if v is None else str(v)

def _get_attr(node: Any, name: str) -> Optional[str]:
    try:
        if isinstance(node, dict):
            val = node.get(name);  return _s(val) if val is not None else None
        if hasattr(node, "get"):
            val = node.get(name)  # type: ignore[attr-defined]
            if val is None: return None
            if isinstance(val, list):  # BeautifulSoup: class puede ser list
                try: return " ".join([_s(x) for x in val])
                except Exception: return " ".join([str(x) for x in val])
            return _s(val)
    except Exception:
        pass
    return None

def _collect_all_ids(ctx: PageContext) -> List[str]:
    soup = getattr(ctx, "soup", None)
    if soup is None: return []
    out: List[str] = []
    try:
        for el in soup.find_all(True):
            try:
                i = el.get("id")  # type: ignore[attr-defined]
                if isinstance(i, str) and i.strip():
                    out.append(i.strip())
            except Exception:
                continue
    except Exception:
        pass
    return out

def _split_tokens(v: Optional[str]) -> List[str]:
    if not v: return []
    return [t for t in re.split(r"\s+", v.strip()) if t]

def _node_text(node: Any) -> str:
    if isinstance(node, dict):
        for k in ("text","inner_text","aria-label","title"):
            t = node.get(k)
            if isinstance(t, str) and t.strip():
                return t.strip()
        return ""
    try:
        if hasattr(node, "get_text"):
            t = node.get_text()  # type: ignore[attr-defined]
            return t.strip() if isinstance(t, str) else ""
    except Exception:
        pass
    return ""

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    4.1.1 (A) — Parsing:
    Heurísticas automatizables:
      - IDs duplicados.
      - Referencias a IDs inexistentes (for, aria-labelledby, aria-describedby, headers).
      - Atributos/entidades mal formados no son fiables de detectar con BS, pero se reporta NA si no hay HTML.
    """
    soup = getattr(ctx, "soup", None)
    if soup is None:
        return {"na": True, "note": "No se proveyó DOM; no es posible auditar Parsing.", "ok_ratio": 1.0}

    # 1) IDs duplicados
    all_ids = _collect_all_ids(ctx)
    seen: Set[str] = set()
    dups: Dict[str, int] = {}
    for i in all_ids:
        if i in seen:
            dups[i] = dups.get(i, 1) + 1
        else:
            seen.add(i)

    # 2) Referencias a IDs inexistentes
    broken_refs: List[Dict[str, Any]] = []
    valid_ids = set(all_ids)
    try:
        for el in soup.find_all(True):
            for attr in REF_ATTRS:
                try:
                    val = el.get(attr)  # type: ignore[attr-defined]
                except Exception:
                    val = None
                if not val: 
                    continue
                tokens = _split_tokens(_s(val))
                missing = [t for t in tokens if t and t not in valid_ids]
                if missing:
                    broken_refs.append({
                        "tag": _s(getattr(el, "name", "")),
                        "attr": attr,
                        "value": _s(val),
                        "missing_ids": missing[:10],
                        "context": _node_text(el)[:120]
                    })
    except Exception:
        pass

    violations = len(dups) + len(broken_refs)
    details: Dict[str, Any] = {
        "duplicate_ids_count": len(dups),
        "duplicate_ids": [{"id": k, "occurrences": v} for k, v in list(dups.items())[:30]],
        "broken_references_count": len(broken_refs),
        "broken_references": broken_refs[:50],
        "ok_ratio": 1.0 if violations == 0 else 0.0,
        "note": (
            "RAW: 4.1.1 valida IDs duplicados y referencias a IDs inexistentes (for, aria-labelledby, aria-describedby, headers). "
            "Errores sintácticos más sutiles requieren validadores HTML especializados."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    rctx.parsing_test = {
      "duplicate_ids": List[{id:str, occurrences:int}],
      "broken_references": List[{tag,attr,value,missing_ids,context}]
    }
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 4.1.1; no se pudo evaluar en modo renderizado."}

    data = getattr(rctx, "parsing_test", None)
    if not isinstance(data, dict):
        d = _compute_counts_raw(rctx); d["rendered"]=True
        d["note"] = d.get("note","") + " | RENDERED: sin 'parsing_test', se reusó RAW."
        return d

    dups = _as_list(data.get("duplicate_ids"))
    brks = _as_list(data.get("broken_references"))
    violations = len(dups) + len(brks)
    return {
        "rendered": True,
        "duplicate_ids_count": len(dups),
        "duplicate_ids": dups[:50],
        "broken_references_count": len(brks),
        "broken_references": brks[:80],
        "ok_ratio": 1.0 if violations == 0 else 0.0,
        "note": "RENDERED: resultados aportados por extractor/validador."
    }

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str]=None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False, "ai_message":"IA no configurada."}
    need = (details.get("duplicate_ids_count",0) or 0) > 0 or (details.get("broken_references_count",0) or 0) > 0
    if not need: return {"ai_used": False, "manual_required": False}
    ctx_json = {
        "dups": details.get("duplicate_ids", [])[:25],
        "broken": details.get("broken_references", [])[:25],
        "html_snippet": (html_sample or "")[:2400]
    }
    prompt = (
        "Eres auditor WCAG 4.1.1 (Parsing). "
        "Propón correcciones para IDs duplicados y referencias rotas (for/aria-*/headers). "
        "Devuelve JSON: {suggestions:[{issue, fix, snippet?}], manual_review?:bool, summary?:string}"
    )
    try:
        ans = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ans, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_4_1_1(
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

    violations = int(details.get("duplicate_ids_count",0) or 0) + int(details.get("broken_references_count",0) or 0)
    passed = (violations == 0)

    verdict = verdict_from_counts(details, passed)
    score0=score_from_verdict(verdict)
    meta=WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0, details=details,
        level=meta.get("level","A"), principle=meta.get("principle","Robusto"),
        title=meta.get("title","Parsing"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
