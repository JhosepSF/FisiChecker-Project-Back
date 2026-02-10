# audits/checks/criteria/p2/c_2_3_3_animation_from_interactions.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict
from ..applicability import ensure_na_if_no_applicable, normalize_pass_for_applicable

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.3.3"

# -------------------------------------------------------------------
# Utilidades
# -------------------------------------------------------------------

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

def _bool(v: Any) -> bool:
    sv = _lower(v)
    return sv in ("true", "1", "yes")

# Heurísticas de “animación por interacción”
TRIGGERS = ("hover","focus","click","tap","press","scroll","drag","pointer","keydown","keyup")

CLASS_HINTS = (
    "parallax","scroll-parallax","tilt", "hover-animate","shake-on-hover",
    "scroll-animate","spin-on-click","bounce-on-hover","headshake","rubberband",
)

# -------------------------------------------------------------------
# Recolección (RAW)
# -------------------------------------------------------------------

def _collect_from_explicit(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Preferimos una lista explícita del extractor, p. ej.:
      ctx.interaction_animations = [
        {
          "selector": ".card",
          "label": "tarjeta destacada",
          "trigger": "hover|focus|click|scroll|drag|...",
          "motion": True,                         # hay movimiento/transform/scroll-linked
          "essential": bool,                      # si el extractor pudo inferir que es esencial
          "can_disable": bool,                    # reconoce toggle global/local
          "respects_prm": bool,                   # respeta @media (prefers-reduced-motion: reduce)
        }, ...
      ]
    """
    out: List[Dict[str, Any]] = []
    for it in _as_list(getattr(ctx, "interaction_animations", [])):
        if isinstance(it, dict):
            out.append(it)
    return out

def _collect_from_animations(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Fallback: derivar de ctx.animations, buscando 'trigger' y propiedades de movimiento.
      Esperado en cada item: {selector?, label?, trigger?, properties?, respects_prm?, essential?, can_disable?}
    """
    out: List[Dict[str, Any]] = []
    for a in _as_list(getattr(ctx, "animations", [])):
        if not isinstance(a, dict):
            continue
        trig = _lower(a.get("trigger"))
        props = _lower(a.get("properties") or a.get("animation_name") or a.get("keyframes"))
        motion = any(p in props for p in ("transform","translate","rotate","scale","scroll-timeline","offset-path","parallax","position"))
        if trig in TRIGGERS or any(h in _lower(a.get("class") or "") for h in CLASS_HINTS):
            out.append({
                "selector": _s(a.get("selector") or a.get("id")),
                "label": _s(a.get("label") or a.get("aria-label")),
                "trigger": trig if trig in TRIGGERS else "unknown",
                "motion": bool(motion),
                "essential": _bool(a.get("essential")),
                "can_disable": _bool(a.get("can_disable")),
                "respects_prm": _bool(a.get("respects_prm")),
                "source": "animations"
            })
    return out

def _collect_from_classes(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Heurística por clases/nombres si no hay datos estructurados.
    """
    out: List[Dict[str, Any]] = []
    for coll in ("widgets","custom_components","sections","cards","panels","headers","banners"):
        for n in _as_list(getattr(ctx, coll, [])):
            if not isinstance(n, dict):
                continue
            cls = _lower(n.get("class"))
            if any(h in cls for h in CLASS_HINTS):
                out.append({
                    "selector": _s(n.get("selector") or n.get("id")),
                    "label": _s(n.get("label") or n.get("aria-label") or n.get("heading") or n.get("text")),
                    "trigger": "scroll",          # la mayoría de estos hints acompañan desplazamiento
                    "motion": True,
                    "essential": _bool(n.get("essential")),
                    "can_disable": _bool(n.get("can_disable")),
                    "respects_prm": _bool(n.get("respects_prm")),
                    "source": f"class_hint:{coll}"
                })
    return out

def _collect_css_support(ctx: PageContext) -> Dict[str, Any]:
    """
    Señales globales de soporte a prefers-reduced-motion (PRM).
    Esperado opcionalmente:
      ctx.css_features = { "has_prm_reduce": bool, "selectors_in_prm": int }
      ctx.motion_toggle = { "present": bool, "persisted": bool }
    """
    cssf = getattr(ctx, "css_features", {}) or {}
    togg = getattr(ctx, "motion_toggle", {}) or {}
    return {
        "has_prm_reduce": _bool(cssf.get("has_prm_reduce")),
        "prm_selectors": int(cssf.get("selectors_in_prm") or 0),
        "has_toggle": _bool(togg.get("present")),
        "toggle_persists": _bool(togg.get("persisted")),
    }

def _collect_candidates(ctx: PageContext) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cands: List[Dict[str, Any]] = []
    cands.extend(_collect_from_explicit(ctx))
    cands.extend(_collect_from_animations(ctx))
    cands.extend(_collect_from_classes(ctx))
    support = _collect_css_support(ctx)
    return cands, support

# -------------------------------------------------------------------
# Evaluación (RAW)
# -------------------------------------------------------------------

def _is_applicable(it: Dict[str, Any]) -> bool:
    """
    Aplica si hay animación con movimiento disparada por interacción (no esencial).
    """
    if _bool(it.get("essential")):
        return False
    trig = _lower(it.get("trigger"))
    return (trig in TRIGGERS or trig == "unknown") and bool(it.get("motion"))

def _has_disable_mechanism(it: Dict[str, Any], support: Dict[str, Any]) -> bool:
    """
    Cumple si:
      - el componente puede deshabilitarse (can_disable=True), o
      - respeta prefers-reduced-motion: reduce (respects_prm=True), o
      - existe un toggle global de “reducir/pausar animaciones” (has_toggle=True).
    """
    return bool(it.get("can_disable")) or bool(it.get("respects_prm")) or bool(support.get("has_prm_reduce")) or bool(support.get("has_toggle"))

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW: 2.3.3 exige que las animaciones de movimiento disparadas por interacción
    puedan deshabilitarse, salvo que sean esenciales. Se acepta respetar
    'prefers-reduced-motion: reduce' o un toggle global/local. 
    """
    items, support = _collect_candidates(ctx)

    examined = len(items)
    applicable = 0
    compliant = 0
    violations = 0
    unknown = 0
    offenders: List[Dict[str, Any]] = []
    types_count: Dict[str, int] = {}

    for it in items:
        trig = _lower(it.get("trigger") or "unknown")
        types_count[trig] = types_count.get(trig, 0) + 1

        if not _is_applicable(it):
            continue
        applicable += 1

        if _has_disable_mechanism(it, support):
            compliant += 1
        else:
            # Si no sabemos si respeta PRM y no vemos toggle, marcamos violación conservadora
            violations += 1
            offenders.append({
                "selector": it.get("selector"),
                "label": it.get("label"),
                "trigger": trig,
                "reason": "Animación de movimiento por interacción sin mecanismo aparente para deshabilitar."
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, compliant / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "items_examined": examined,
        "applicable": applicable,
        "compliant": compliant,
        "violations": violations,
        "unknown": unknown,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "types_count": types_count,
        "support": support,
        "note": (
            "RAW: 2.3.3 (AAA) requiere poder deshabilitar animaciones de movimiento disparadas por interacción. "
            "Se acepta respeto de 'prefers-reduced-motion: reduce' o un control (toggle) que las desactive. "
            "Animaciones esenciales quedan excluidas."
        )
    }
    return details

# -------------------------------------------------------------------
# RENDERED (prueba en ejecución)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede aportar:
      rctx.animation_from_interactions_test = [
        {
          "selector": str,
          "trigger": "hover|focus|click|scroll|...",
          "observed_motion_when_prm_reduce": bool,  # PRM=reduce activado en el entorno de prueba
          "has_user_toggle": bool,                   # sitio ofrece toggle de desactivar animación
          "toggle_effective": bool,                  # el toggle realmente desactiva la animación
          "essential": bool,
          "notes": str
        }, ...
      ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.3.3; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    tests = _as_list(getattr(rctx, "animation_from_interactions_test", []))
    if not tests:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'animation_from_interactions_test'.").strip()
        return d

    applicable = 0
    compliant = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for t in tests:
        if not isinstance(t, dict):
            continue
        if _bool(t.get("essential")):
            continue

        trig = _lower(t.get("trigger") or "unknown")

        applicable += 1

        prm_ok = not bool(t.get("observed_motion_when_prm_reduce"))
        toggle_ok = bool(t.get("has_user_toggle")) and bool(t.get("toggle_effective"))

        if prm_ok or toggle_ok:
            compliant += 1
        else:
            violations += 1
            offenders.append({
                "selector": _s(t.get("selector")),
                "trigger": trig,
                "reason": "En ejecución: PRM=reduce no detiene la animación y no hay toggle efectivo para desactivarla."
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, compliant / max(1, applicable))), 4)

    d.update({
        "applicable": applicable,
        "compliant": compliant,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders + _as_list(d.get("offenders", [])),
        "note": (d.get("note","") + " | RENDERED: verificación con prefers-reduced-motion y toggle de sitio.").strip()
    })
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: recomienda respetar PRM y/o proveer toggles:
      - Encapsular animaciones dentro de @media (prefers-reduced-motion: reduce) { animation: none; transition-duration: 0.01ms; }
      - Exponer 'Reducir movimiento' global con persistencia (localStorage/cookie).
      - Para parallax/scroll: degradar a posición fija o transformaciones mínimas cuando PRM=reduce.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    needs = (details.get("violations", 0) or 0) > 0
    if not needs:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "support": details.get("support", {}),
        "offenders": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2200],
    }
    prompt = (
        "Actúa como auditor WCAG 2.3.3 (Animation from Interactions, AAA). "
        "Propón correcciones para deshabilitar animaciones de movimiento disparadas por interacción: "
        "- Respetar 'prefers-reduced-motion: reduce' y cortar animaciones; "
        "- Añadir toggle global/local con persistencia; "
        "- Degradar parallax/scroll a estático con PRM. "
        "Devuelve JSON: { suggestions: [{selector?, trigger?, css_fix?, js_fix?, toggle_design?, persistence?, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_2_3_3(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None
) -> CriterionOutcome:
    # 1) Detalles según modo
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
        manual_required = ai_info.get("manual_review", False)

    # 3) Aplicabilidad / NA
    ensure_na_if_no_applicable(details, applicable_keys=("applicable",),
                               note_suffix="no se detectaron animaciones basadas en interacción aplicables")

    # 4) passed / verdict / score
    passed = normalize_pass_for_applicable(details, violations_key="violations", applicable_keys=("applicable",))

    verdict = verdict_from_counts(details, passed)
    score0 = score_from_verdict(verdict)

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE,
        passed=passed,
        verdict=verdict,
        score_0_2=score0,
        details=details,
        level=meta.get("level", "AAA"),
        principle=meta.get("principle", "Operable"),
        title=meta.get("title", "Animación a partir de interacciones"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
