# audits/checks/criteria/p1/c_1_4_13_content_on_hover_or_focus.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional (mismo mecanismo que 1.1.x–1.4.x)
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  # si no existe, el modo IA queda deshabilitado

CODE = "1.4.13"

# -------------------------------------------------------------------
# Utilidades
# -------------------------------------------------------------------

def _as_list(x):
    if not x:
        return []
    if isinstance(x, list):
        return x
    return list(x)

def _str(v: Any) -> str:
    return "" if v is None else str(v)

def _bool(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")

def _lower(s: Any) -> str:
    return _str(s).strip().lower()

# -------------------------------------------------------------------
# Heurísticas: detección de “contenido adicional” y disparadores
# -------------------------------------------------------------------

# Pistas comunes de tooltips/popovers/menus activados por hover/focus
TITLE_LIKE_ATTRS = ("title", "data-title", "data-tooltip", "aria-label")  # 'aria-label' no crea popup por sí sola, pero a veces coexiste
TRIGGER_ATTRS = ("aria-haspopup", "aria-expanded", "aria-controls", "data-popover", "data-menu")
ROLE_LIKE = ("tooltip", "dialog", "menu", "listbox", "tree", "grid")

def _looks_like_trigger(el: Dict[str, Any]) -> bool:
    if not isinstance(el, dict):
        return False
    # title nativo → riesgo (suele desaparecer al mover el puntero)
    for k in TITLE_LIKE_ATTRS:
        v = el.get(k)
        if isinstance(v, str) and v.strip():
            return True
    # aria-haspopup/controls/expanded
    for k in TRIGGER_ATTRS:
        v = el.get(k)
        if isinstance(v, str) and v.strip():
            return True
        if isinstance(v, bool) and v:
            return True
    # rol que típicamente abre overlay
    r = _lower(el.get("role"))
    if r in ("button","link") and any(el.get(k) for k in TRIGGER_ATTRS):
        return True
    if r in ("combobox","menuitem","treeitem","gridcell"):
        return True
    # clases típicas
    cls = _lower(el.get("class"))
    if any(h in cls for h in ("tooltip","popover","menu","dropdown","hovercard","hover-card")):
        return True
    return False

def _collect_triggers(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Candidatos: links, buttons, controles de formulario y elementos con 'title'/data-tooltip.
    Si el extractor ya provee 'hover_focus_overlays' o 'tooltips', se usan también.
    """
    triggers: List[Dict[str, Any]] = []
    for src in ("links","buttons","form_controls","chips","tabs","toggles","custom_components","icons"):
        for n in _as_list(getattr(ctx, src, [])):
            if isinstance(n, dict) and _looks_like_trigger(n):
                nn = dict(n); nn["__source"] = src
                triggers.append(nn)
    # Añade nodos que el extractor marque explícitamente
    for n in _as_list(getattr(ctx, "tooltips", [])):
        if isinstance(n, dict):
            nn = dict(n); nn["__source"] = "tooltips"
            triggers.append(nn)
    for n in _as_list(getattr(ctx, "hover_focus_overlays", [])):
        if isinstance(n, dict):
            nn = dict(n); nn["__source"] = "hover_focus_overlays"
            triggers.append(nn)
    return triggers

# -------------------------------------------------------------------
# Reglas 1.4.13 (qué verificamos)
# -------------------------------------------------------------------
# Cuando un contenido adicional se activa por hover/focus:
#  (A) Descartable (dismissible): existe un mecanismo para DESCARTAR sin mover el puntero ni el foco
#      (ESC, botón Cerrar alcanzable vía teclado, etc.), salvo que NO oculte ni reemplace otro contenido.
#  (B) Hoverable: si el disparo es por HOVER, el puntero puede moverse sobre el contenido adicional
#      sin que éste desaparezca.
#  (C) Persistente: permanece visible hasta que se quita el hover/focus, el usuario lo descarta,
#      o la info deja de ser válida (es decir, no se auto-oculta “al vuelo” mientras se está usando).

def _dismissible_ok(item: Dict[str, Any]) -> Tuple[Optional[bool], str]:
    """
    Devuelve (ok/None, motivo). None = desconocido en RAW.
    """
    # Excepción: si no obstruye ni reemplaza contenido → no exigimos descarte
    if _bool(item.get("does_not_obscure")) or (_lower(item.get("overlap_ratio")) in ("0","0.0")):
        return True, "No obstruye/reemplaza contenido (excepción)."

    # Señales de descarte
    if any(_bool(item.get(k)) for k in ("esc_dismiss","dismissible","has_close_button","close_button_present","can_dismiss_without_pointer_move")):
        return True, "Hay mecanismo de descarte (ESC/botón)."

    # Heurística: si el item proviene de title nativo → normalmente NO es descartable manualmente
    if item.get("__title_based"):
        return False, "Tooltip nativo por 'title' no es descartable sin mover puntero."

    # Desconocido en RAW si no hay flags
    return None, "Desconocido (sin flags en RAW)."

def _hoverable_ok(item: Dict[str, Any]) -> Tuple[Optional[bool], str]:
    # Solo aplica si el trigger incluye hover
    trig = _lower(item.get("trigger_mode") or item.get("trigger"))
    if "hover" not in trig and not _bool(item.get("hover_triggers")):
        return None, "No aplica (no se detecta trigger por hover)."
    if any(_bool(item.get(k)) for k in ("allows_pointer_over","pointer_can_move_over","hoverable","stays_open_on_hover")):
        return True, "Se puede mover puntero sobre el contenido adicional."
    if item.get("__title_based"):
        return False, "Tooltip nativo por 'title' suele desaparecer al mover el puntero."
    return None, "Desconocido (sin flags de hover)."

def _persistent_ok(item: Dict[str, Any]) -> Tuple[Optional[bool], str]:
    # Debe permanecer visible hasta quitar hover/focus o ser descartado. Timeouts agresivos fallan.
    if any(_bool(item.get(k)) for k in ("persists_until_blur_or_dismiss","persistent","stays_open_until_blur_or_dismiss")):
        return True, "Persistente hasta blur/dismiss."
    if _bool(item.get("hides_on_timeout")) and not _bool(item.get("timeout_only_when_invalid")):
        return False, "Se oculta por timeout mientras se usa (no cumple)."
    # titulo nativo suele autocerrar en cuanto se mueve el puntero (no persistente)
    if item.get("__title_based"):
        return False, "Tooltip 'title' no permanece visible al interactuar."
    return None, "Desconocido (sin flags de persistencia)."

def _mark_title_based(trigger: Dict[str, Any]) -> bool:
    """True si el trigger parece depender de atributo 'title' u homólogos."""
    for k in TITLE_LIKE_ATTRS:
        v = trigger.get(k)
        if isinstance(v, str) and v.strip() and k == "title":
            return True
    return False

# -------------------------------------------------------------------
# Núcleo RAW
# -------------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW: Heurístico sobre metadatos de disparadores y overlays (si el extractor los provee).
      - Marca especialmente el uso de 'title' nativo (suele fallar 1.4.13).
      - Usa flags si existen: trigger_mode, esc_dismiss, has_close_button, allows_pointer_over,
        persists_until_blur_or_dismiss, hides_on_timeout, overlap_ratio/does_not_obscure.
    """
    triggers = _collect_triggers(ctx)

    examined = len(triggers)
    applicable = 0
    pass_dismissible = 0
    pass_hoverable = 0
    pass_persistent = 0
    unknown = 0
    violations = 0

    offenders: List[Dict[str, Any]] = []

    for t in triggers:
        # Solo aplicamos si realmente hay “contenido adicional” esperado
        # (si el extractor lo marca o tenemos pistas claras)
        maybe_overlay = bool(_looks_like_trigger(t))
        if not maybe_overlay:
            continue
        applicable += 1

        # Marca si depende de 'title' nativo
        if _mark_title_based(t):
            t["__title_based"] = True

        ok_dismiss, why_dismiss = _dismissible_ok(t)
        ok_hover, why_hover = _hoverable_ok(t)
        ok_persist, why_persist = _persistent_ok(t)

        # Suma pases
        if ok_dismiss is True:   pass_dismissible += 1
        if ok_hover is True:     pass_hoverable += 1
        if ok_persist is True:   pass_persistent += 1

        # Violaciones duras:
        local_viol = 0
        reasons: List[str] = []

        if ok_dismiss is False:
            local_viol += 1; reasons.append(why_dismiss)
        if ok_hover is False:
            local_viol += 1; reasons.append(why_hover)
        if ok_persist is False:
            local_viol += 1; reasons.append(why_persist)

        if local_viol > 0:
            violations += 1
            offenders.append({
                "type": "hover_focus_violation",
                "source": t.get("__source"),
                "id": _str(t.get("id")),
                "class": _str(t.get("class")),
                "role": _str(t.get("role")),
                "trigger_mode": _str(t.get("trigger_mode") or t.get("trigger")),
                "reasons": reasons,
            })
        elif ok_dismiss is None or ok_hover is None or ok_persist is None:
            unknown += 1
            offenders.append({
                "type": "hover_focus_unknown",
                "source": t.get("__source"),
                "id": _str(t.get("id")),
                "class": _str(t.get("class")),
                "role": _str(t.get("role")),
                "hint": "Faltan flags para evaluar descartar/hover/persistencia en RAW."
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, (applicable - violations) / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "triggers_examined": examined,
        "applicable": applicable,
        "pass_dismissible": pass_dismissible,
        "pass_hoverable": pass_hoverable,
        "pass_persistent": pass_persistent,
        "unknown_behavior": unknown,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 1.4.13 requiere que el contenido adicional activado por hover/focus sea "
            "descartable sin mover puntero/foco (salvo que no obstruya), hoverable (si aplica) "
            "y persistente hasta blur/dismiss. El uso de 'title' nativo suele incumplir."
        )
    }
    
    # N/A si no hay contenido adicional aplicable
    if applicable == 0:
        details["na"] = True
        details["ok_ratio"] = None
    else:
        details["na"] = False
        
    return details

# -------------------------------------------------------------------
# RENDERED (simulación real de hover/focus)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.4.13; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    overlays = _as_list(getattr(rctx, "hover_focus_overlays", []))
    if not overlays:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'hover_focus_overlays'.").strip()
        # si tampoco hay aplicables detectados en RAW → N/A
        if int(d.get("applicable", 0) or 0) == 0:
            d["na"] = True
            d["ok_ratio"] = None
        return d

    examined = len(overlays)
    applicable = examined  # si vienen en rendered, son aplicables
    pass_dismissible = pass_hoverable = pass_persistent = 0
    violations = 0
    unknown = 0
    offenders: List[Dict[str, Any]] = []

    for it in overlays:
        does_not_obscure = _bool(it.get("does_not_obscure"))
        overlap_ratio = it.get("overlap_ratio")
        if isinstance(overlap_ratio, (int, float)) and overlap_ratio <= 0.01:
            does_not_obscure = True

        reasons = []

        # (A) Descartable
        ok_dismiss = True
        if not does_not_obscure:
            ok_dismiss = _bool(it.get("esc_dismiss")) or _bool(it.get("has_close_button")) or _bool(it.get("can_dismiss_without_pointer_move"))
            if not ok_dismiss:
                reasons.append("Sin ESC/botón Cerrar para descartar sin mover puntero/foco.")

        # (B) Hoverable si aplica
        trig = _lower(it.get("trigger_mode"))
        ok_hover = True
        if "hover" in trig:
            ok_hover = _bool(it.get("pointer_can_move_over"))
            if not ok_hover:
                reasons.append("Al mover puntero sobre el overlay, se oculta (no hoverable).")

        # (C) Persistente
        ok_persist = True
        if not _bool(it.get("persists_until_blur_or_dismiss")):
            if _bool(it.get("hides_on_timeout")) and not _bool(it.get("timeout_only_when_invalid")):
                ok_persist = False
                reasons.append("Se oculta por timeout mientras está en uso (no persistente).")

        if ok_dismiss and ok_hover and ok_persist:
            pass_dismissible += 1
            if "hover" in trig:
                pass_hoverable += 1
            pass_persistent += 1
        else:
            violations += 1
            offenders.append({
                "type": "hover_focus_violation",
                "trigger": _str(it.get("trigger_selector") or it.get("id") or it.get("role")),
                "trigger_mode": trig,
                "reasons": reasons
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, (applicable - violations) / max(1, applicable))), 4)

    d.update({
        "triggers_examined": examined,
        "applicable": applicable,
        "pass_dismissible": pass_dismissible,
        "pass_hoverable": pass_hoverable,
        "pass_persistent": pass_persistent,
        "unknown_behavior": unknown,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders + _as_list(d.get("offenders", [])),
        "note": (d.get("note","") + " | RENDERED: verificación directa de descartable/hoverable/persistente.").strip()
    })
    # si por alguna razón applicable volvió 0:
    if applicable == 0:
        d["na"] = True
        d["ok_ratio"] = None
    else:
        d["na"] = False
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: propone correcciones para cumplir 1.4.13:
      - Añadir botón Cerrar visible y manejador de ESC.
      - Mantener abierto mientras hover/focus en trigger u overlay (no timeouts arbitrarios).
      - Permitir mover el puntero al overlay sin que se cierre.
      - No usar tooltips nativos 'title'; usar componentes accesibles (role='tooltip'/'dialog').
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    offs = details.get("offenders", []) or []
    if not offs and (details.get("violations", 0) or 0) == 0:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "applicable": details.get("applicable", 0),
            "violations": details.get("violations", 0),
            "pass_dismissible": details.get("pass_dismissible", 0),
            "pass_hoverable": details.get("pass_hoverable", 0),
            "pass_persistent": details.get("pass_persistent", 0),
        },
        "offenders": offs[:20],
        "html_snippet": (html_sample or "")[:2400],
    }
    prompt = (
        "Actúa como auditor WCAG 1.4.13 (Content on Hover or Focus, AA). "
        "Para cada offender, propone fixes concretos: "
        "- Añadir mecanismo de cierre (botón visible + ESC) sin mover puntero/foco; "
        "- Evitar ocultar por timeout; "
        "- Mantener visible al mover el puntero sobre el overlay; "
        "- Evitar 'title' nativo, usar role='tooltip' con aria-describedby/controls; "
        "- Gestionar focus correctamente (devolver al trigger en cierre). "
        "Devuelve JSON: { suggestions: [{type, reason, html_fix?, js_fix?, css_fix?, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_1_4_13(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None
) -> CriterionOutcome:
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

    manual_required = False
    if mode == CheckMode.AI:
        ai_info = _ai_review(details, html_sample=html_for_ai)
        details["ai_info"] = ai_info
        src = "ai"
        manual_required = ai_info.get("manual_review", False)

    # --- veredicto
    applicable = int(details.get("applicable", 0) or 0)
    violations = int(details.get("violations", 0) or 0)
    unknown    = int(details.get("unknown_behavior", 0) or 0)

    if details.get("na") is True or applicable == 0:
        verdict = "na"
        passed = False
        score0 = score_from_verdict(verdict)
        score_hint = None
    else:
        if violations == 0 and unknown == 0:
            verdict = "pass"
            passed = True
        elif violations > 0 and violations < applicable:
            verdict = "partial"
            passed = False
        elif violations == 0 and unknown > 0:
            verdict = "partial"    # hay casos aplicables pero sin evidencia completa en RAW
            passed = False
            manual_required = True
        else:
            verdict = "fail"
            passed = False
        score0 = score_from_verdict(verdict)
        score_hint = details.get("ok_ratio")

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE,
        passed=passed,
        verdict=verdict,
        score_0_2=score0,
        details=details,
        level=meta.get("level", "AA"),
        principle=meta.get("principle", "Perceptible"),
        title=meta.get("title", "Contenido al pasar el cursor o al tener el foco"),
        source=src,
        score_hint=score_hint,
        manual_required=manual_required or (verdict in {"na","partial"} and src != "rendered")
    )