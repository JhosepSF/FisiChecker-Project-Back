# audits/checks/criteria/p2/c_2_1_1_keyboard.py
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

CODE = "2.1.1"

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
        if v is None:
            return None
        if isinstance(v, int):
            return v
        sv = _s(v).strip()
        if sv == "":
            return None
        return int(sv)
    except Exception:
        return None

NATIVE_INTERACTIVE = {
    ("a", "href"),
    ("button", None),
    ("input", None),
    ("select", None),
    ("textarea", None),
    ("summary", None),  # dentro de details
    ("option", None),
}

INTERACTIVE_ROLES = {
    "button","link","menuitem","menuitemcheckbox","menuitemradio",
    "checkbox","radio","switch","tab","tabpanel","textbox",
    "combobox","listbox","option","gridcell","rowheader","columnheader",
    "treeitem","slider","spinbutton","dialog"
}

MOUSE_EVENTS = ("onclick","onmousedown","onmouseup","onmouseenter","onmouseover","ondblclick","oncontextmenu","ondragstart","ondrop","ondragover")
KEY_EVENTS = ("onkeydown","onkeyup","onkeypress")

def _is_native_interactive(el: Dict[str, Any]) -> bool:
    tag = _lower(el.get("tag"))
    if not tag:
        return False
    # <a> requiere href para ser interactivo nativo en teclado
    if tag == "a":
        href = _s(el.get("href") or el.get("xlink:href") or "")
        return bool(href.strip())
    # input hidden NO cuenta
    if tag == "input":
        t = _lower(el.get("type"))
        return t != "hidden"
    # otros de la lista
    for t, req in NATIVE_INTERACTIVE:
        if tag == t and (req is None or el.get(req)):
            return True
    return False

def _has_any_mouse_handler(el: Dict[str, Any]) -> bool:
    for k in MOUSE_EVENTS:
        if el.get(k) is not None:
            return True
    # frameworks: data-onclick, @click, x-on:click...
    attrs = " ".join([_lower(k) for k in getattr(el, "keys", lambda: [])()])
    if any(tok in attrs for tok in ("data-onclick","@click","x-on:click","(click)","on:click")):
        return True
    # clases sugestivas
    cls = _lower(el.get("class"))
    if any(h in cls for h in ("btn","button","clickable","pointer","cursor-pointer")):
        return True
    return False

def _has_any_key_handler(el: Dict[str, Any]) -> bool:
    for k in KEY_EVENTS:
        if el.get(k) is not None:
            return True
    attrs = " ".join([_lower(k) for k in getattr(el, "keys", lambda: [])()])
    if any(tok in attrs for tok in ("(keydown)","(keyup)","(keypress)","@keydown","@keyup","x-on:keydown")):
        return True
    return False

def _role_interactive(el: Dict[str, Any]) -> Optional[str]:
    r = _lower(el.get("role"))
    return r if r in INTERACTIVE_ROLES else None

def _tabindex(el: Dict[str, Any]) -> Optional[int]:
    return _int_or_none(el.get("tabindex"))

def _is_focusable(el: Dict[str, Any]) -> bool:
    """
    Foco por teclado:
      - nativo interactivo (sin tabindex=-1)
      - o role interactivo con tabindex >= 0
      - o tabindex >= 0 explícito
    aria-hidden/inert/disabled bloquean el foco
    """
    if _bool(el.get("inert")) or _bool(el.get("aria-hidden")):
        return False
    if _bool(el.get("disabled")) or _bool(el.get("aria-disabled")):
        return False

    ti = _tabindex(el)
    if ti is not None and ti < 0:
        return False

    if _is_native_interactive(el):
        return True

    if _role_interactive(el) is not None and (ti is None or ti >= 0):
        return True

    if ti is not None and ti >= 0:
        return True

    return False

def _is_actionable(el: Dict[str, Any]) -> bool:
    """
    Consideramos 'actionable' si:
      - es nativo interactivo, o
      - tiene role interactivo, o
      - tiene manejadores de mouse que sugieren acción (click, drag, etc.)
    """
    return _is_native_interactive(el) or (_role_interactive(el) is not None) or _has_any_mouse_handler(el)

def _is_exempt(el: Dict[str, Any]) -> bool:
    """
    Excluye elementos irrelevantes para 2.1.1:
      - disabled / aria-disabled
      - aria-hidden / inert
      - puramente decorativos
    """
    return _bool(el.get("disabled")) or _bool(el.get("aria-disabled")) or _bool(el.get("aria-hidden")) or _bool(el.get("inert")) or _bool(el.get("is_decorative"))

# -------------------------------------------------------------------
# Núcleo RAW
# -------------------------------------------------------------------

def _collect_actionables(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Reúne candidatos de UI/acción de diversas colecciones del extractor.
    """
    items: List[Dict[str, Any]] = []
    for src in ("buttons","links","form_controls","inputs","controls","widgets","custom_components","icons","chips","tabs","toggles","menu_items","cards","list_items"):
        for n in _as_list(getattr(ctx, src, [])):
            if isinstance(n, dict):
                nn = dict(n)
                nn["__source"] = src
                items.append(nn)
    # fallback: anchors de soup si el extractor no pobló 'links'
    for n in _as_list(getattr(ctx, "anchors", [])):
        if isinstance(n, dict):
            nn = dict(n); nn["__source"] = "anchors"
            items.append(nn)
    return items

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.1.1 (Teclado): Toda funcionalidad debe estar disponible desde teclado.
    RAW (heurístico):
      - todo elemento 'actionable' debe ser accesible con teclado:
          * focusable (no tabindex negativo, no aria-hidden/inert)
          * si no es nativo: tener role interactivo o tabindex>=0
          * si depende de mouse (onclick/drag...), debe tener alternativa de teclado (keydown/keyup/keypress)
      - detecta patrones de gestos solo puntero (drag) sin alternativa explícita (riesgo)
    """
    items = _collect_actionables(ctx)

    examined = 0
    applicable = 0
    kb_ok = 0
    fails_focus = 0
    fails_no_key_handler = 0
    pointer_only_gesture = 0
    unknown = 0

    offenders: List[Dict[str, Any]] = []

    for el in items:
        examined += 1
        if _is_exempt(el):
            continue

        actionable = _is_actionable(el)
        if not actionable:
            continue
        applicable += 1

        focusable = _is_focusable(el)
        has_key = _has_any_key_handler(el) or _is_native_interactive(el)  # nativo ya trae soporte para Enter/Espacio en la mayoría de casos
        has_mouse_only = _has_any_mouse_handler(el) and not has_key

        # Gestos de arrastre (no es 100% de 2.1.1, pero si no hay alternativa, sugiere que no es operable por teclado)
        drag_like = any(k in el for k in ("draggable","ondragstart","ondrop","ondragover","onpointerdown","onpointermove"))
        drag_flag = (drag_like and not has_key and _role_interactive(el) is None and not _is_native_interactive(el))

        if not focusable:
            fails_focus += 1
            offenders.append({
                "type": "not_focusable",
                "source": el.get("__source"),
                "id": _s(el.get("id")),
                "class": _s(el.get("class")),
                "role": _s(el.get("role")),
                "tabindex": el.get("tabindex"),
                "reason": "Elemento accionable no es enfocable por teclado (tabindex negativo / aria-hidden / inert / sin mecanismo de foco)."
            })
            continue

        if has_mouse_only:
            fails_no_key_handler += 1
            offenders.append({
                "type": "no_keyboard_handler",
                "source": el.get("__source"),
                "id": _s(el.get("id")),
                "class": _s(el.get("class")),
                "role": _s(el.get("role")),
                "reason": "Elemento con handlers de mouse pero sin alternativa de teclado (keydown/keyup/keypress) y no nativo."
            })
            continue

        if drag_flag:
            pointer_only_gesture += 1
            offenders.append({
                "type": "pointer_only_gesture",
                "source": el.get("__source"),
                "id": _s(el.get("id")),
                "class": _s(el.get("class")),
                "reason": "Funcionalidad de arrastre/puntero sin evidencia de alternativa por teclado."
            })
            # No hacemos 'continue' para permitir contarlo como riesgo, pero no como fail duro todavía.

        # si llegó aquí, lo consideramos OK de teclado
        kb_ok += 1

    violations = fails_focus + fails_no_key_handler
    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, kb_ok / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "examined": examined,
        "applicable": applicable,
        "keyboard_ok": kb_ok,
        "fails_focus": fails_focus,
        "fails_no_key_handler": fails_no_key_handler,
        "pointer_only_gesture": pointer_only_gesture,  # riesgo (pide revisión/alternativa)
        "unknown": unknown,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 2.1.1 exige que toda funcionalidad sea operable por teclado. "
            "Se comprueba foco por teclado y presencia de alternativas de teclado cuando hay handlers de mouse. "
            "Gestos solo puntero (drag) se marcan como riesgo si no hay evidencia de alternativa."
        )
    }
    
    if applicable == 0:
        details["na"] = True
        details["ok_ratio"] = None
        details["note"] = details.get("note","") + " | NA: no se detectaron elementos accionables para evaluar operabilidad por teclado."
    
    return details

# -------------------------------------------------------------------
# RENDERED (prueba real de teclado)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED tu extractor puede simular navegación por teclado y devolver:
      rctx.keyboard_test = {
        "tab_stops": int,                  # número de paradas de TAB alcanzables
        "focusables_total": int,           # estimado de elementos foco-ables
        "operable_clickables_via_enter_space": int,
        "clickables_total": int,
        "broken_focus_order": bool,        # orden de foco incoherente/inesperado
        "offscreen_focus_traps": int,      # elementos entran al foco pero quedan fuera de viewport
        "unreachable_by_tab": int,         # elementos accionables no alcanzables por TAB
        "mouse_only_actions": int,         # clickables que no responden a Enter/Espacio
        "notes": str,
        "examples": [ {selector|role|text|reason}, ... ]
      }
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.1.1; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    kt = getattr(rctx, "keyboard_test", None)
    if not isinstance(kt, dict):
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'keyboard_test'.").strip()
        # Si ya es NA por falta de aplicables, mantenlo explícito.
        if int(d.get("applicable", 0) or 0) == 0:
            d["na"] = True
            d["ok_ratio"] = None
            d["note"] += " | RENDERED→NA: sin elementos accionables (o sin 'keyboard_test')."
        return d

    # Si hay 'keyboard_test', podemos complementar la aplicabilidad
    clickables_total = int(kt.get("clickables_total") or 0)
    d["applicable"] = max(int(d.get("applicable", 0) or 0), clickables_total)

    operable_by_keys = int(kt.get("operable_clickables_via_enter_space") or 0)
    unreachable = int(kt.get("unreachable_by_tab") or 0)
    mouse_only = int(kt.get("mouse_only_actions") or 0)
    broken_order = bool(kt.get("broken_focus_order"))
    offscreen_traps = int(kt.get("offscreen_focus_traps") or 0)

    # NA si tras complementar sigue sin haber aplicables
    if int(d.get("applicable", 0) or 0) == 0:
        d["na"] = True
        d["ok_ratio"] = None
        d["note"] = (d.get("note","") + " | RENDERED→NA: sin elementos accionables medibles.").strip()
        return d

    # Falta dura si hay clickables que no responden a teclado o inalcanzables
    hard_viol = 0
    if mouse_only > 0 or unreachable > 0:
        hard_viol += 1
    if broken_order or offscreen_traps > 0:
        d.setdefault("warnings", [])
        d["warnings"].append({"type":"focus_order_or_traps","broken_order":broken_order,"offscreen_traps":offscreen_traps})

    if hard_viol:
        d["violations"] = int(d.get("violations", 0)) + 1
        d.setdefault("offenders", [])
        d["offenders"].append({
            "type": "keyboard_rendered",
            "mouse_only_actions": mouse_only,
            "unreachable_by_tab": unreachable,
            "examples": (kt.get("examples") or [])[:20],
            "reason": "En ejecución: elementos accionables no responden a Enter/Espacio o no son alcanzables por TAB."
        })
        d["ok_ratio"] = 0.0 if clickables_total > 0 else d.get("ok_ratio", 0.0)

    d["note"] = (d.get("note","") + " | RENDERED: navegación por teclado simulada (TAB/Shift+TAB/Enter/Espacio).").strip()
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: propone fixes típicos 2.1.1:
      - Asegurar foco: tabindex=0 en contenedores interactivos personalizados; evitar tabindex negativo.
      - Añadir role adecuado (button/link) cuando sea un contenedor clickable.
      - Mapear Enter/Espacio a la acción (keydown/keyup → click/submit); evitar sólo click del mouse.
      - Proveer alternativa por teclado a gestos de arrastre (botones mover ↑↓←→, menús de acciones, etc.).
      - Evitar aria-hidden/inert en controles activos.
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
            "fails_focus": details.get("fails_focus", 0),
            "fails_no_key_handler": details.get("fails_no_key_handler", 0),
            "pointer_only_gesture": details.get("pointer_only_gesture", 0),
        },
        "offenders": offs[:25],
        "html_snippet": (html_sample or "")[:2400],
    }
    prompt = (
        "Actúa como auditor WCAG 2.1.1 (Keyboard, A). "
        "Para cada offender, sugiere fixes concretos: "
        "- Añadir tabindex=0 y role='button'/'link' si corresponde; "
        "- Manejar Enter (key='Enter') y Espacio (key=' ') disparando la misma acción que click; "
        "- Evitar tabindex negativo en controles; "
        "- No usar aria-hidden/inert en interactivos; "
        "- Alternativa por teclado a drag & drop (botones mover/ordenar, accesos de teclado). "
        "Devuelve JSON: { suggestions: [{target, reason, html_fix?, js_fix?, aria_fix?, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_2_1_1(
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

    # ➜ NA si no aplica (applicable==0) o si ya viene marcado
    is_na = bool(details.get("na")) or int(details.get("applicable", 0) or 0) == 0
    if is_na:
        details["na"] = True
        details["ok_ratio"] = None if details.get("ok_ratio") == 1 else details.get("ok_ratio")
        if "note" in details:
            details["note"] = (details["note"] + " | NA: sin elementos accionables para 2.1.1.").strip()
        verdict = verdict_from_counts(details, True)  
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
            title=meta.get("title", "Teclado"),
            source=src,
            score_hint=details.get("ok_ratio"),
            manual_required=False  # NA no requiere revisión
        )

    # 3) PASA/FALLA (solo si aplica)
    violations = int(details.get("violations", 0) or 0)
    applicable = int(details.get("applicable", 0) or 0)
    
    # Ultra estricto: PASS solo si 100%, PARTIAL >= 80%, FAIL < 80%
    if applicable == 0 or violations == 0:
        passed = True
        details["ratio"] = 1.0
    else:
        kb_ok = int(details.get("keyboard_ok", 0) or 0)
        ratio = kb_ok / applicable
        details["ratio"] = ratio
        # PARTIAL si >= 80%, FAIL si < 80%
        if ratio >= 0.80:
            passed = True  # verdict_from_counts detectará partial
        else:
            passed = False

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
        title=meta.get("title", "Teclado"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required or (details.get("pointer_only_gesture", 0) > 0 and src != "rendered")
    )
