# audits/checks/criteria/p2/c_2_1_3_keyboard_no_exception.py
from typing import Dict, Any, List, Optional, Tuple

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.1.3"

# -------------------------------------------------------------------
# Utilidades comunes (alineadas con 2.1.1/2.1.2)
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
    ("summary", None),
    ("option", None),
}

INTERACTIVE_ROLES = {
    "button","link","menuitem","menuitemcheckbox","menuitemradio",
    "checkbox","radio","switch","tab","tabpanel","textbox",
    "combobox","listbox","option","gridcell","rowheader","columnheader",
    "treeitem","slider","spinbutton","dialog","scrollbar"
}

MOUSE_EVENTS = (
    "onclick","onmousedown","onmouseup","onmouseenter","onmouseover",
    "ondblclick","oncontextmenu","ondragstart","ondrop","ondragover"
)
KEY_EVENTS = ("onkeydown","onkeyup","onkeypress")
POINTER_PATH_EVENTS = (
    "onmousemove","onpointermove","ontouchmove","ondrag","ondragstart","ondragover","ondragend"
)

def _is_native_interactive(el: Dict[str, Any]) -> bool:
    tag = _lower(el.get("tag"))
    if not tag:
        return False
    if tag == "a":
        href = _s(el.get("href") or el.get("xlink:href") or "")
        return bool(href.strip())
    if tag == "input":
        t = _lower(el.get("type"))
        return t != "hidden"
    for t, req in NATIVE_INTERACTIVE:
        if tag == t and (req is None or el.get(req)):
            return True
    return False

def _has_any_mouse_handler(el: Dict[str, Any]) -> bool:
    for k in MOUSE_EVENTS:
        if el.get(k) is not None:
            return True
    # frameworks (atributos “custom”)
    attrs = " ".join([_lower(k) for k in getattr(el, "keys", lambda: [])()])
    if any(tok in attrs for tok in ("data-onclick","@click","x-on:click","(click)","on:click")):
        return True
    # hints en class
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
    Enfocable por teclado:
      - nativo interactivo (sin tabindex -1)
      - role interactivo con tabindex >= 0
      - tabindex >= 0 explícito
    aria-hidden / inert / disabled bloquean foco.
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
      - tiene manejadores de mouse que sugieren acción
    """
    return _is_native_interactive(el) or (_role_interactive(el) is not None) or _has_any_mouse_handler(el)

def _requires_pointer_path(el: Dict[str, Any]) -> bool:
    """
    Heurística: la funcionalidad parece depender de trayectoria de puntero / gesto continuo.
    Indicadores:
      - handlers de movimiento (mousemove/pointermove/touchmove/drag…)
      - canvas/signature/draw/sortable/drag/slider/carousel en class
      - roles que suelen implicar arrastre/continuo (slider/scrollbar) si NO hay evidencia de soporte teclado
    """
    # eventos de trayectoria
    for k in POINTER_PATH_EVENTS:
        if el.get(k) is not None:
            return True

    cls = _lower(el.get("class"))
    style = _lower(el.get("style"))
    tag = _lower(el.get("tag"))
    name_id = (_lower(el.get("name")) + " " + _lower(el.get("id"))).strip()

    hints = ("drag","draggable","sortable","draw","signature","canvas","paint","scribble","slider","carousel","panzoom","pan-zoom","resize-handle")
    if any(h in cls for h in hints) or any(h in style for h in hints) or any(h in name_id for h in hints):
        return True
    if tag in ("canvas","svg") and (_has_any_mouse_handler(el) or any(el.get(k) is not None for k in POINTER_PATH_EVENTS)):
        return True

    # roles que requieren especial cuidado
    r = _role_interactive(el)
    if r in {"slider","scrollbar"}:
        # si no es input=range nativo y no hay key handlers → lo tratamos como gesto sin alternativa declarada
        if not (_is_native_interactive(el) and _lower(el.get("type")) == "range") and not _has_any_key_handler(el):
            return True

    return False

def _is_exempt(el: Dict[str, Any]) -> bool:
    return _bool(el.get("disabled")) or _bool(el.get("aria-disabled")) or _bool(el.get("aria-hidden")) or _bool(el.get("inert")) or _bool(el.get("is_decorative"))

# -------------------------------------------------------------------
# Núcleo RAW (más estricto que 2.1.1)
# -------------------------------------------------------------------

def _collect_candidates(ctx: PageContext) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for src in ("buttons","links","form_controls","inputs","controls","widgets","custom_components","icons","chips","tabs","toggles","menu_items","cards","list_items","sliders","carousels"):
        for n in _as_list(getattr(ctx, src, [])):
            if isinstance(n, dict):
                nn = dict(n); nn["__source"] = src
                items.append(nn)
    for n in _as_list(getattr(ctx, "anchors", [])):
        if isinstance(n, dict):
            nn = dict(n); nn["__source"] = "anchors"
            items.append(nn)
    return items

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.1.3 (AAA): Igual que 2.1.1, pero **sin excepción** para entradas dependientes de trayectoria.
    Cualquier funcionalidad basada en gestos/arrastre/dibujo debe tener alternativa por teclado.
    """
    items = _collect_candidates(ctx)

    examined = 0
    applicable = 0
    kb_ok = 0
    fails_focus = 0
    fails_no_key_handler = 0
    fails_pointer_path_no_kb = 0
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
        has_key = _has_any_key_handler(el) or _is_native_interactive(el)

        if not focusable:
            fails_focus += 1
            offenders.append({
                "type": "not_focusable",
                "source": el.get("__source"),
                "id": _s(el.get("id")),
                "class": _s(el.get("class")),
                "role": _s(el.get("role")),
                "reason": "Elemento accionable no es enfocable por teclado."
            })
            continue

        # mouse-only (sin alternativa por teclado) → violación en AAA
        if _has_any_mouse_handler(el) and not has_key and not _is_native_interactive(el):
            fails_no_key_handler += 1
            offenders.append({
                "type": "no_keyboard_handler",
                "source": el.get("__source"),
                "id": _s(el.get("id")),
                "class": _s(el.get("class")),
                "role": _s(el.get("role")),
                "reason": "Handlers de mouse sin alternativa de teclado."
            })
            # no continue; evaluamos también gesto/Trayectoria

        # trayectoria/puntero sin alternativa → violación explícita en 2.1.3
        if _requires_pointer_path(el) and not has_key:
            fails_pointer_path_no_kb += 1
            offenders.append({
                "type": "pointer_path_no_keyboard_alt",
                "source": el.get("__source"),
                "id": _s(el.get("id")),
                "class": _s(el.get("class")),
                "role": _s(el.get("role")),
                "reason": "Funcionalidad dependiente de trayectoria/gesto sin alternativa operable por teclado."
            })
            # seguimos contando como fail

        # Si llegó aquí y no falló nada, OK
        if (_has_any_mouse_handler(el) or _requires_pointer_path(el) or _role_interactive(el) or _is_native_interactive(el)):
            if has_key:
                kb_ok += 1

    violations = fails_focus + fails_no_key_handler + fails_pointer_path_no_kb
    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, kb_ok / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "examined": examined,
        "applicable": applicable,
        "keyboard_ok": kb_ok,
        "fails_focus": fails_focus,
        "fails_no_key_handler": fails_no_key_handler,
        "fails_pointer_path_no_kb": fails_pointer_path_no_kb,
        "unknown": unknown,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 2.1.3 (AAA) exige que toda funcionalidad sea operable por teclado **sin excepción**. "
            "Si depende de trayectorias/gestos (drag/draw/slider/carousel, etc.) debe existir alternativa de teclado."
        ),
        # Compatibilidad con tu enfoque anterior
        "mirrors_2_1_1": False  # ahora aplicamos reglas más estrictas que 2.1.1
    }
    
    if applicable == 0:
        details["na"] = True
        details["ok_ratio"] = None
        details["note"] = details.get("note","") + " | NA: no se detectaron elementos accionables para 2.1.3."

    
    return details

# -------------------------------------------------------------------
# RENDERED (prueba real; incluye gestos)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, además de 'keyboard_test' (como 2.1.1), el extractor puede exponer:
      rctx.pointer_gesture_test = [
        {
          "selector": str,
          "requires_pointer_path": bool,     # gesto continuo (arrastre/dibujo/slider libre)
          "has_keyboard_alternative": bool,  # flechas, +/- , botones mover, etc.
          "notes": str
        }, ...
      ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.1.3; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    kt = getattr(rctx, "keyboard_test", None)
    pt = getattr(rctx, "pointer_gesture_test", None)

    # Si no hay ninguna prueba y tampoco aplicables, es NA
    if not isinstance(kt, dict) and not isinstance(pt, list):
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionaron 'keyboard_test' ni 'pointer_gesture_test'.").strip()
        if int(d.get("applicable", 0) or 0) == 0:
            d["na"] = True
            d["ok_ratio"] = None
            d["note"] += " | RENDERED→NA: sin elementos/pruebas aplicables."
        return d

    # Complementa 'applicable' con lo observado en ejecución
    if isinstance(kt, dict):
        d["applicable"] = max(int(d.get("applicable", 0) or 0), int(kt.get("clickables_total") or 0))
    if isinstance(pt, list):
        d["applicable"] = max(int(d.get("applicable", 0) or 0), len(pt))

    # Si aún no hay aplicables, NA
    if int(d.get("applicable", 0) or 0) == 0:
        d["na"] = True
        d["ok_ratio"] = None
        d["note"] = (d.get("note","") + " | RENDERED→NA: sin elementos/pruebas aplicables.").strip()
        return d

    # --- Violaciones en ejecución (como ya tienes) ---
    if isinstance(kt, dict):
        mouse_only = int(kt.get("mouse_only_actions") or 0)
        unreachable = int(kt.get("unreachable_by_tab") or 0)
        if mouse_only > 0 or unreachable > 0:
            d["violations"] = int(d.get("violations", 0)) + 1
            d.setdefault("offenders", [])
            d["offenders"].append({
                "type": "keyboard_rendered",
                "mouse_only_actions": mouse_only,
                "unreachable_by_tab": unreachable,
                "reason": "En ejecución: elementos no responden a teclado o no son alcanzables por TAB."
            })
            d["ok_ratio"] = 0.0 if int(kt.get("clickables_total") or 0) > 0 else d.get("ok_ratio", 0.0)

    if isinstance(pt, list):
        path_fails = 0
        path_checks = 0
        for it in pt:
            if not isinstance(it, dict):
                continue
            path_checks += 1
            requires_path = _bool(it.get("requires_pointer_path"))
            has_kb_alt = _bool(it.get("has_keyboard_alternative"))
            if requires_path and not has_kb_alt:
                path_fails += 1
                d.setdefault("offenders", [])
                d["offenders"].append({
                    "type": "pointer_path_no_keyboard_alt_rendered",
                    "selector": _s(it.get("selector")),
                    "reason": "Gesto/Trayectoria sin alternativa operable por teclado (AAA)."
                })
        if path_fails > 0:
            d["violations"] = int(d.get("violations", 0)) + path_fails
            d["ok_ratio"] = 0.0 if path_checks > 0 else d.get("ok_ratio", 0.0)

    d["note"] = (d.get("note","") + " | RENDERED: teclado y gestos verificados en ejecución (sin excepción).").strip()
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: propone alternativas de teclado para funciones de trayectoria/gesto y correcciones de foco/handlers.
    Ejemplos: flechas para slider/scrollbar, botones mover/ordenar, +/- para zoom/ajuste, atajos de teclado,
    mapear Enter/Espacio a la acción, tabindex=0 y role adecuados, evitar aria-hidden/inert en interactivos.
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
            "fails_pointer_path_no_kb": details.get("fails_pointer_path_no_kb", 0),
        },
        "offenders": offs[:25],
        "html_snippet": (html_sample or "")[:2400],
    }
    prompt = (
        "Actúa como auditor WCAG 2.1.3 (Keyboard, No Exception, AAA). "
        "Para cada offender, propone alternativas de teclado y fixes concretos: "
        "- Para gestos/trayectorias (drag/draw/slider/carousel): flechas, +/- , botones mover, atajos; "
        "- Mapear Enter/Espacio y teclas a la misma acción que click/drag; "
        "- Asegurar foco con tabindex=0 y role correcto; "
        "- Evitar aria-hidden/inert en interactivos. "
        "Devuelve JSON: { suggestions: [{target, reason, js_fix?, html_fix?, aria_fix?, kb_alternative?, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_2_1_3(
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
        if details.get("ok_ratio") == 1:
            details["ok_ratio"] = None
        details["note"] = (details.get("note","") + " | NA: sin elementos aplicables para 2.1.3.").strip()
        verdict = verdict_from_counts(details, True)  # 'passed' irrelevante en NA
        score0 = score_from_verdict(verdict)

        meta = WCAG_META.get(CODE, {})
        return CriterionOutcome(
            code=CODE,
            passed=False,  # irrelevante en NA
            verdict=verdict,
            score_0_2=score0,
            details=details,
            level=meta.get("level", "AAA"),
            principle=meta.get("principle", "Operable"),
            title=meta.get("title", "Teclado (sin excepción)"),
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
        level=meta.get("level", "AAA"),
        principle=meta.get("principle", "Operable"),
        title=meta.get("title", "Teclado (sin excepción)"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
