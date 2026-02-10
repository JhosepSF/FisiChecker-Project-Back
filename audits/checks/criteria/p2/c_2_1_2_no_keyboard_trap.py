# audits/checks/criteria/p2/c_2_1_2_no_keyboard_trap.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.1.2"

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

def _int_or_none(v: Any) -> Optional[int]:
    try:
        if v is None: return None
        if isinstance(v, int): return v
        sv = _s(v).strip()
        if sv == "": return None
        return int(sv)
    except Exception:
        return None

# Pistas de librerías comunes de "focus trap" (válidas si hay salida por teclado)
FOCUS_TRAP_HINTS = ("focus-trap", "focus_trap", "focus-lock", "focuslock", "cdk-focus-trap", "cdkTrapFocus")

def _looks_like_focus_zone(el: Dict[str, Any]) -> bool:
    """
    Heurística: posibles zonas que gestionan el foco (diálogos, overlays, menús).
    """
    role = _lower(el.get("role"))
    cls = _lower(el.get("class"))
    attrs = " ".join([_lower(k) for k in getattr(el, "keys", lambda: [])()])
    if role in ("dialog","alertdialog","menu","listbox","tree","grid","tabpanel","tooltip","combobox","menuitem","listbox"):
        return True
    if any(h in cls for h in ("modal","dialog","drawer","offcanvas","popover","dropdown","menu","tooltip")):
        return True
    if any(h in attrs for h in FOCUS_TRAP_HINTS):
        return True
    if _bool(el.get("aria_modal")) or _lower(el.get("aria-modal")) == "true":
        return True
    return False

# -------------------------------------------------------------------
# Qué exige 2.1.2
# -------------------------------------------------------------------
# No debe haber "trampas" de teclado: una vez el foco entra en un componente, el usuario
# debe poder mover el foco fuera de él usando solo teclado, o bien debe existir un mecanismo
# claro para salir (p.ej., ESC cierra el componente y devuelve el foco al invocador).
# Ciclar el foco dentro de un modal abierto es aceptable SI hay forma de salir con teclado.

def _zone_violation_assessment(zone: Dict[str, Any]) -> Tuple[Optional[bool], List[str]]:
    """
    Devuelve (violates?/None, reasons). None = desconocido (RAW sin flags suficientes).
    """
    reasons: List[str] = []

    is_open = _bool(zone.get("is_open")) or True  # por defecto consideramos abierta si el extractor la listó
    if not is_open:
        return None, ["Zona cerrada; no aplicable."]

    # Señales fuertes desde extractor si existen:
    # - tab_cycles_inside: TAB/Shift+TAB no pueden escapar.
    # - is_trapping: detectado por prueba (RENDERED) → dura.
    # - can_escape_with_keyboard: ESC/shortcut cierra o mueve foco fuera.
    tab_cycles = _bool(zone.get("tab_cycles_inside")) or _bool(zone.get("traps_tab")) or _bool(zone.get("trap_focus"))
    can_escape = _bool(zone.get("can_escape_with_keyboard")) or _bool(zone.get("esc_dismiss")) or _bool(zone.get("has_close_button"))
    requires_pointer_to_exit = _bool(zone.get("requires_pointer_to_exit"))
    prevents_tab_default = _bool(zone.get("prevents_tab_default"))  # p.ej., keydown Tab + preventDefault sin gestionar salida

    # Si explícitamente requiere ratón para salir → violación
    if requires_pointer_to_exit:
        reasons.append("Requiere puntero para salir del componente.")
        return True, reasons

    if prevents_tab_default and not can_escape:
        reasons.append("Se cancela TAB sin mecanismo alternativo para salir.")
        return True, reasons

    # Sola presencia de ciclo TAB no es violación si hay salida por teclado (ESC/cerrar)
    if tab_cycles and not can_escape:
        reasons.append("TAB/Shift+TAB ciclan dentro y no hay ESC/cierre con teclado.")
        return True, reasons

    if tab_cycles and can_escape:
        return False, ["Ciclo de TAB interno, pero hay mecanismo de salida por teclado (aceptable)."]

    # Sin señales claras → desconocido en RAW
    return None, ["Desconocido en RAW (faltan flags de trampa/salida)."]

# -------------------------------------------------------------------
# Núcleo RAW
# -------------------------------------------------------------------

def _collect_focus_zones(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Posibles zonas que gestionan foco:
      dialogs/modals/drawers/menus/popovers/dropdowns/sidebars,
      o 'focus_zones' explícito del extractor.
    """
    zones: List[Dict[str, Any]] = []
    for src in ("dialogs","modals","drawers","menus","popovers","dropdowns","sidebars","overlays"):
        for n in _as_list(getattr(ctx, src, [])):
            if isinstance(n, dict) and _looks_like_focus_zone(n):
                nn = dict(n); nn["__source"] = src
                zones.append(nn)
    for n in _as_list(getattr(ctx, "focus_zones", [])):
        if isinstance(n, dict):
            nn = dict(n); nn["__source"] = "focus_zones"
            zones.append(nn)
    return zones

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW (heurístico):
      - detecta zonas potenciales de trampa (modales/overlays/menús)
      - evalúa si TAB cicla dentro y si existe mecanismo de salida por teclado (ESC/botón cerrar)
      - marca desconocido si no hay flags suficientes (recomendar RENDERED)
    """
    zones = _collect_focus_zones(ctx)

    examined = len(zones)
    applicable = 0
    pass_zones = 0
    unknown = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for z in zones:
        applicable += 1
        violates, why = _zone_violation_assessment(z)
        if violates is True:
            violations += 1
            offenders.append({
                "type": "keyboard_trap",
                "source": z.get("__source"),
                "id": _s(z.get("id")),
                "class": _s(z.get("class")),
                "role": _s(z.get("role")),
                "reasons": why
            })
        elif violates is False:
            pass_zones += 1
        else:
            unknown += 1
            offenders.append({
                "type": "unknown",
                "source": z.get("__source"),
                "id": _s(z.get("id")),
                "class": _s(z.get("class")),
                "hint": "; ".join(why)
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, (applicable - violations) / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "zones_examined": examined,
        "applicable": applicable,
        "pass_zones": pass_zones,
        "unknown": unknown,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 2.1.2 (Sin trampa para el teclado). Se consideran zonas que gestionan foco "
            "(modales/overlays/menús). Violación si el foco queda atrapado y no hay salida por "
            "teclado (ESC/botón cerrar). Si faltan flags, se marca como 'unknown' y se recomienda RENDERED."
        )
    }
    
    if applicable == 0:
        details["na"] = True
        details["ok_ratio"] = None
        details["note"] = details.get("note", "") + " | NA: no se detectaron zonas que gestionen foco para evaluar."
    
    return details

# -------------------------------------------------------------------
# RENDERED (prueba real de escape de foco)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede ejecutar una prueba y exponer:
      rctx.keyboard_trap_test = [
        {
          "container_selector": str,
          "is_trapping": bool,                 # TAB/Shift+TAB no pueden sacar el foco fuera
          "tab_cycles_inside": bool,           # ciclo dentro del contenedor
          "can_escape_with_keyboard": bool,    # ESC/cerrar con teclado disponible
          "esc_dismiss": bool,
          "has_close_button": bool,            # botón Cerrar enfocable/activable con teclado
          "returns_focus_to_invoker": bool,    # al cerrar, devuelve foco al disparador
          "requires_pointer_to_exit": bool,
          "notes": str
        }, ...
      ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.1.2; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    tests = _as_list(getattr(rctx, "keyboard_trap_test", []))
    if not tests:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'keyboard_trap_test'.").strip()
        # ➜ NUEVO: si tampoco hay zonas del lado RAW, es NA
        if int(d.get("applicable", 0) or 0) == 0:
            d["na"] = True
            d["ok_ratio"] = None
            d["note"] += " | RENDERED→NA: sin zonas para evaluar."
        return d

    applicable = len(tests)
    violations = 0
    pass_zones = 0
    offenders: List[Dict[str, Any]] = []

    for t in tests:
        trapping = _bool(t.get("is_trapping")) or (_bool(t.get("tab_cycles_inside")) and not _bool(t.get("can_escape_with_keyboard")))
        can_escape = _bool(t.get("can_escape_with_keyboard")) or _bool(t.get("esc_dismiss")) or _bool(t.get("has_close_button"))
        requires_pointer = _bool(t.get("requires_pointer_to_exit"))

        if (trapping and not can_escape) or requires_pointer:
            violations += 1
            offenders.append({
                "type": "keyboard_trap_rendered",
                "container": _s(t.get("container_selector") or t.get("id")),
                "reasons": [
                    "Foco atrapado sin salida por teclado" if (trapping and not can_escape) else None,
                    "Requiere puntero para salir" if requires_pointer else None
                ]
            })
        else:
            pass_zones += 1

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, (applicable - violations) / max(1, applicable))), 4)

    d.update({
        "applicable": applicable,
        "pass_zones": pass_zones,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders + _as_list(d.get("offenders", [])),
        "note": (d.get("note","") + " | RENDERED: prueba de trampa de foco con TAB/Shift+TAB y mecanismos de salida.").strip()
    })

    # ➜ NUEVO: si tras pruebas no hay aplicables, también NA (caso extremo)
    if applicable == 0:
        d["na"] = True
        d["ok_ratio"] = None
        d["note"] += " | RENDERED→NA: sin zonas aplicables."
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: propone fixes típicos 2.1.2:
      - Añadir salida por teclado (Esc) que cierre el contenedor y devuelva el foco al disparador.
      - Botón 'Cerrar' enfocable y activable con Enter/Espacio.
      - Evitar cancelar TAB sin proveer navegación alternativa.
      - En componentes no modales (popover/tooltip), permitir que TAB salga del contenedor.
      - En modales, mantener ciclo interno solo mientras estén abiertos y con salida por teclado.
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
            "pass_zones": details.get("pass_zones", 0),
        },
        "offenders": offs[:25],
        "html_snippet": (html_sample or "")[:2400],
    }
    prompt = (
        "Actúa como auditor WCAG 2.1.2 (No Keyboard Trap, A). "
        "Para cada offender, sugiere fixes concretos: "
        "- Añadir handler de Escape que cierre el contenedor y devuelva el foco al invocador; "
        "- Incluir botón Cerrar con tabindex=0 y role='button' si es custom, accesible por Enter/Espacio; "
        "- No cancelar TAB; gestionar el ciclo de foco solo en modales y siempre con salida por teclado; "
        "- En popovers/menus no modales, permitir que TAB escape al contenido subyacente. "
        "Devuelve JSON: { suggestions: [{target, reason, js_fix?, html_fix?, aria_fix?, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_2_1_2(
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

    # ➜ NUEVO: NA si no aplica (applicable==0) o ya viene marcado
    is_na = bool(details.get("na")) or int(details.get("applicable", 0) or 0) == 0
    if is_na:
        details["na"] = True
        if details.get("ok_ratio") == 1:
            details["ok_ratio"] = None
        details["note"] = (details.get("note","") + " | NA: sin zonas aplicables para 2.1.2.").strip()
        verdict = verdict_from_counts(details, True)  # 'passed' irrelevante para NA
        score0 = score_from_verdict(verdict)

        meta = WCAG_META.get(CODE, {})
        return CriterionOutcome(
            code=CODE,
            passed=False,  # irrelevante en NA
            verdict=verdict,
            score_0_2=score0,
            details=details,
            level=meta.get("level", "A"),
            principle=meta.get("principle", "Operable"),
            title=meta.get("title", "Sin trampa para el teclado"),
            source=src,
            score_hint=details.get("ok_ratio"),
            manual_required=False
        )

    # 3) PASA/FALLA (solo si aplica)
    passed = (int(details.get("violations", 0) or 0) == 0)

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
        title=meta.get("title", "Sin trampa para el teclado"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required or (details.get("unknown", 0) > 0 and src != "rendered")
    )
