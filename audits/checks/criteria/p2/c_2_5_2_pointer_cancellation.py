# audits/checks/criteria/p2/c_2_5_2_pointer_cancellation.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.5.2"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

DOWN_ATTRS = ("onmousedown","ontouchstart","onpointerdown")
UPSAFE_ATTRS = ("onclick","onmouseup","ontouchend","onpointerup")

RISKY_INLINE_NAV = re.compile(r"(location\.href|window\.location|document\.location|submit\(|dispatchEvent\(|click\(\))", re.I)

def _as_list(x):
    if not x:
        return []
    if isinstance(x, list):
        return x
    return list(x)

def _s(v: Any) -> str:
    return "" if v is None else str(v)

def _lower(v: Any) -> str:
    return _s(v).strip().lower()

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

def _is_clickable_dict(n: Dict[str, Any]) -> bool:
    tag = _lower(n.get("tag"))
    role = _lower(n.get("role"))
    href = _s(n.get("href"))
    tabindex = _s(n.get("tabindex"))
    if tag in ("button","input") or (tag == "a" and href):
        return True
    if role in ("button","link","tab","menuitem","switch") and (href or tabindex != ""):
        return True
    # atributos inline de eventos también lo hacen “clickable”
    for a in (DOWN_ATTRS + UPSAFE_ATTRS + ("onclick",)):
        if (_s(n.get(a)) or "") != "":
            return True
    return False

def _collect_clickables(ctx: PageContext) -> List[Any]:
    out: List[Any] = []
    # Preferir inventario del extractor
    for coll in ("clickables","buttons","inputs","anchors","interactive_nodes"):
        for n in _as_list(getattr(ctx, coll, [])):
            if isinstance(n, dict) and _is_clickable_dict(n):
                out.append(n)
    # Si vacío, heurística mínima desde anchors/buttons del soup
    if not out:
        soup = getattr(ctx, "soup", None)
        if soup is not None:
            try:
                for a in soup.find_all("a"):
                    href = _get_attr(a, "href")
                    if href:
                        out.append({"tag":"a","href":href,"node":a})
                for b in soup.find_all("button"):
                    out.append({"tag":"button","node":b})
                for i in soup.find_all("input"):
                    out.append({"tag":"input","type":_lower(_get_attr(i, "type") or ""), "node": i})
            except Exception:
                pass
    return out

# ------------------------------------------------------------
# Evaluación
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.5.2 (A): Para activaciones con un solo puntero, al menos una de:
      (a) NO se activa en el down-event,
      (b) la finalización está en el up-event,
      (c) se puede abortar antes de completar (mover fuera del objetivo o cancelar),
      (d) se ofrece UNDO (reversible).
    RAW (estático) marca riesgo si hay inline handlers en down-event que hacen navegación/acción inmediata.
    """
    clickables = _collect_clickables(ctx)

    applicable = 0
    risky_down_handlers = 0
    safe_or_unknown = 0
    offenders: List[Dict[str, Any]] = []

    for n in clickables:
        applicable += 1
        # inline down-event con acción directa
        risk = False
        down_srcs = []
        for attr in DOWN_ATTRS:
            val = _get_attr(n, attr)
            if val and RISKY_INLINE_NAV.search(val):
                risk = True
                down_srcs.append({"attr": attr, "snippet": val[:160]})
        if risk:
            risky_down_handlers += 1
            offenders.append({
                "node": {k: n.get(k) for k in ("tag","href","id","class","role","type") if n.get(k) is not None},
                "reason": "Acción atada a evento 'down' con efecto inmediato (inline).",
                "evidence": down_srcs
            })
            continue

        # si solo hay onclick / up-events, consideramos seguro/indeterminado
        safe_or_unknown += 1

    violations = risky_down_handlers
    ok_ratio = 1.0 if applicable == 0 else (1.0 if violations == 0 else 0.0)

    details: Dict[str, Any] = {
        "applicable": 1 if applicable > 0 else 0,
        "targets_examined": applicable,
        "risky_down_handlers": risky_down_handlers,
        "safe_or_unknown": safe_or_unknown,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: se marcan como riesgos los handlers inline 'onmousedown/ontouchstart/onpointerdown' que navegan o ejecutan acción inmediata. "
            "Handlers en 'click'/'up' se consideran aceptables/indeterminados. La verificación robusta requiere RENDERED."
        )
    }
    return details

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    RENDERED permite simular interacción:
      rctx.pointer_cancel_test = [
        { "selector": str,
          "triggers_on_down": bool,                  # activa en down
          "completes_on_up": bool,                   # la acción se realiza en up
          "can_abort_before_completion": bool,       # se puede cancelar moviéndose fuera o con ESC
          "has_undo_after": bool,                    # ofrece deshacer/undo
          "notes": str|None }
      ]
    Violación si: triggers_on_down == True y (completes_on_up == False) y no (can_abort_before_completion or has_undo_after).
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.5.2; no se pudo evaluar en modo renderizado."}

    tests = _as_list(getattr(rctx, "pointer_cancel_test", []))
    if not tests:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = (d.get("note","") + " | RENDERED: sin 'pointer_cancel_test', se reusó RAW.").strip()
        return d

    applicable = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for t in tests:
        if not isinstance(t, dict):
            continue
        applicable += 1
        triggers_on_down = bool(t.get("triggers_on_down"))
        completes_on_up = bool(t.get("completes_on_up"))
        can_abort = bool(t.get("can_abort_before_completion"))
        has_undo = bool(t.get("has_undo_after"))

        # Criterio de fallo (estricto):
        # activa en down Y no completa en up Y no hay abort/undo
        if triggers_on_down and (not completes_on_up) and (not (can_abort or has_undo)):
            violations += 1
            offenders.append({
                "selector": _s(t.get("selector")),
                "reason": "Activación en 'down' sin posibilidad de abortar o deshacer.",
                "notes": _s(t.get("notes"))
            })

    ok_ratio = 1.0 if applicable == 0 else (1.0 if violations == 0 else 0.0)

    details: Dict[str, Any] = {
        "rendered": True,
        "targets_examined": applicable,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: verificación de cancelación de puntero mediante pruebas de interacción."
    }
    return details

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    needs = (details.get("violations", 0) or 0) > 0 or (details.get("risky_down_handlers", 0) or 0) > 0
    if not needs:
        return {"ai_used": False, "manual_required": False}

    offenders = (details.get("offenders", []) or [])[:20]
    ctx_json = {
        "offenders": offenders,
        "html_snippet": (html_sample or "")[:2200],
        "recipes": [
            "Cambiar 'onmousedown/ontouchstart' por 'onclick' (o 'pointerup') para completar en 'up'.",
            "Si se mantiene 'down', implementar cancelación moviendo el puntero fuera del objetivo sin activar.",
            "Proveer acción 'Deshacer' (undo) visible tras la activación (toasts con botón, banner, etc.).",
            "Evitar navegación inmediata en 'down' (usar preventDefault y esperar 'up').",
        ]
    }
    prompt = (
        "Eres auditor WCAG 2.5.2 (Pointer Cancellation, A). "
        "Para cada offender, propone cambios concretos (HTML/JS) para que la activación no ocurra en 'down', "
        "o sea abortable antes de completar, o tenga un 'Deshacer'. Devuelve JSON: "
        "{ suggestions: [{selector?, change, snippet?, rationale}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_2_5_2(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None
) -> CriterionOutcome:

    # 1) detalles según modo
    if mode == CheckMode.RENDERED:
        if rendered_ctx is None:
            details = _compute_counts_raw(ctx)
            details["warning"] = "Se pidió RENDERED sin rendered_ctx; fallback a RAW."
            src = "raw"
        else:
            details = _compute_counts_rendered(rendered_ctx)
            src = "rendered"
    else:
        details = _compute_counts_raw(ctx)
        src = "raw"

    # 2) IA opcional
    manual_required = False
    if mode == CheckMode.AI:
        ai_info = _ai_review(details, html_sample=html_for_ai)
        details["ai_info"] = ai_info
        src = "ai"
        manual_required = bool(ai_info.get("manual_review", False))

    # 3) passed / verdict / score
    violations = int(details.get("violations", 0) or 0)
    applicable = int(details.get("targets_examined", 0) or 0)
    passed = (applicable == 0) or (violations == 0)

    verdict = verdict_from_counts(details, passed)
    score0 = score_from_verdict(verdict)

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE,
        passed=passed,
        verdict=verdict,
        score_0_2=score0,
        details=details,
        level=meta.get("level", "A"),
        principle=meta.get("principle", "Operable"),
        title=meta.get("title", "Cancelación de puntero"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
