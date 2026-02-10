# audits/checks/criteria/p2/c_2_4_3_focus_order.py
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

CODE = "2.4.3"

# -------------------------------------------------------------------
# Utilidades
# -------------------------------------------------------------------

FOCUSABLE_TAGS = (
    "a","button","input","select","textarea","summary"
)

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

def _is_focusable_dict(n: Dict[str, Any]) -> bool:
    tag = _lower(n.get("tag"))
    role = _lower(n.get("role"))
    href = _s(n.get("href"))
    tabindex = _s(n.get("tabindex"))
    contenteditable = _lower(n.get("contenteditable"))
    disabled = _bool(n.get("disabled"))
    hidden_attr = _bool(n.get("hidden"))
    aria_hidden = _bool(n.get("aria-hidden"))

    if disabled or hidden_attr:
        return False
    if aria_hidden:
        # si aria-hidden="true", no debería ser focusable (lo tratamos como candidato para violación si además lo es)
        pass

    if tag in FOCUSABLE_TAGS:
        if tag == "a":
            return bool(href)
        return not disabled

    # tabindex
    if tabindex != "":
        try:
            ti = int(tabindex)  # puede ser 0, >0, <0
            return ti >= 0
        except Exception:
            pass

    # contenteditable suele ser focusable
    if contenteditable in ("true","plaintext-only"):
        return True

    # roles interactivos comunes
    if role in ("button","link","checkbox","radio","combobox","switch","menuitem","menuitemcheckbox","menuitemradio","tab","option","slider","spinbutton"):
        return True

    return False

def _extract_focusables_from_dom(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Extrae candidatos focusables a partir de anchors, inputs y cualquier nodo con tabindex/role.
    El extractor puede ya proveer ctx.focusables; si no, las derivamos heurísticamente.
    """
    # Si el extractor ya nos dio una lista estructurada, úsala
    fl = _as_list(getattr(ctx, "focusables", []))
    if fl:
        return [x for x in fl if isinstance(x, dict)]

    out: List[Dict[str, Any]] = []

    # 1) anchors
    for a in _as_list(getattr(ctx, "anchors", [])):
        try:
            if isinstance(a, dict):
                if _is_focusable_dict(a):
                    out.append({
                        "selector": _s(a.get("selector") or a.get("id") or a.get("href")),
                        "tag": _lower(a.get("tag") or "a"),
                        "href": _s(a.get("href")),
                        "tabindex": _s(a.get("tabindex")),
                        "role": _lower(a.get("role")),
                        "aria-hidden": _lower(a.get("aria-hidden")),
                        "hidden": _lower(a.get("hidden")),
                        "inert": _lower(a.get("inert")),
                        "class": _s(a.get("class")),
                        "source": "anchors"
                    })
            else:
                # Tag BeautifulSoup
                if hasattr(a, "get"):
                    href = a.get("href")
                    if href:
                        out.append({
                            "selector": _s(a.get("id") or href),
                            "tag": "a",
                            "href": _s(href),
                            "tabindex": _s(a.get("tabindex")),
                            "role": _lower(a.get("role")),
                            "aria-hidden": _lower(a.get("aria-hidden")),
                            "hidden": _lower(a.get("hidden")),
                            "inert": _lower(a.get("inert")),
                            "class": _s(a.get("class")),
                            "source": "anchors(tag)"
                        })
        except Exception:
            continue

    # 2) inputs/selects/textarea/buttons si el extractor los expone
    for coll in ("inputs","form_controls","buttons","selects","textareas"):
        for n in _as_list(getattr(ctx, coll, [])):
            try:
                if isinstance(n, dict) and _is_focusable_dict(n):
                    out.append({
                        "selector": _s(n.get("selector") or n.get("id") or n.get("name")),
                        "tag": _lower(n.get("tag") or ""),
                        "type": _lower(n.get("type") or ""),
                        "tabindex": _s(n.get("tabindex")),
                        "role": _lower(n.get("role")),
                        "aria-hidden": _lower(n.get("aria-hidden")),
                        "hidden": _lower(n.get("hidden")),
                        "inert": _lower(n.get("inert")),
                        "class": _s(n.get("class")),
                        "source": coll
                    })
            except Exception:
                continue

    # 3) Genérico: elementos con tabindex si el extractor dejó 'nodes_with_tabindex'
    for n in _as_list(getattr(ctx, "nodes_with_tabindex", [])):
        try:
            if isinstance(n, dict) and _is_focusable_dict(n):
                out.append({
                    "selector": _s(n.get("selector") or n.get("id")),
                    "tag": _lower(n.get("tag") or ""),
                    "tabindex": _s(n.get("tabindex")),
                    "role": _lower(n.get("role")),
                    "aria-hidden": _lower(n.get("aria-hidden")),
                    "hidden": _lower(n.get("hidden")),
                    "inert": _lower(n.get("inert")),
                    "class": _s(n.get("class")),
                    "source": "nodes_with_tabindex"
                })
        except Exception:
            continue

    return out

def _tabindex_num(v: Any) -> Optional[int]:
    try:
        s = _s(v)
        if s == "":
            return None
        return int(s)
    except Exception:
        return None

# -------------------------------------------------------------------
# Heurísticas (RAW)
# -------------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.4.3 (Orden del foco). En modo RAW solo podemos detectar patrones de riesgo:
      - uso de tabindex positivo (>0),
      - elementos potencialmente ocultos/aria-hidden/inert que parecen focusables,
      - muchos focusables antes del contenido principal sin skip-link (señal débil),
      - mezcla abundante de tabindex custom (orden no natural).
    No podemos “probar” el orden real sin ejecución; para eso está RENDERED.
    """
    focusables = _extract_focusables_from_dom(ctx)
    total = len(focusables)

    positive_tabindex = 0
    hidden_focusable = 0
    aria_hidden_focusable = 0
    inert_focusable = 0
    custom_tabindex = 0  # cualquier tabindex presente (incl. 0 / >0 / <0) — métrica informativa
    offenders: List[Dict[str, Any]] = []

    for f in focusables:
        ti = _tabindex_num(f.get("tabindex"))
        if ti is not None:
            custom_tabindex += 1
            if ti > 0:
                positive_tabindex += 1
                offenders.append({
                    "selector": f.get("selector"),
                    "reason": "Uso de tabindex > 0 (puede alterar el orden natural del foco).",
                    "tabindex": ti,
                    "source": f.get("source")
                })
        # flags de visibilidad/ocultamiento
        aria_hidden = _bool(f.get("aria-hidden"))
        hidden_attr = _bool(f.get("hidden"))
        inert_attr = _bool(f.get("inert"))

        if hidden_attr:
            hidden_focusable += 1
            offenders.append({
                "selector": f.get("selector"),
                "reason": "Elemento con atributo 'hidden' pero potencialmente focusable.",
                "tabindex": ti,
                "source": f.get("source")
            })
        if aria_hidden:
            aria_hidden_focusable += 1
            offenders.append({
                "selector": f.get("selector"),
                "reason": "Elemento con aria-hidden='true' pero potencialmente focusable.",
                "tabindex": ti,
                "source": f.get("source")
            })
        if inert_attr:
            inert_focusable += 1
            offenders.append({
                "selector": f.get("selector"),
                "reason": "Elemento marcado 'inert' pero potencialmente focusable.",
                "tabindex": ti,
                "source": f.get("source")
            })

    # Señal débil: muchos focusables antes del main cuando no hay skip link
    landmarks = getattr(ctx, "landmarks", {}) or {}
    has_main = bool(landmarks.get("main"))
    skip_links = 0
    try:
        from ..p2.c_2_4_1_bypass_blocks import _collect_skip_links  # opcional si está disponible
        skip_links = len(_collect_skip_links(ctx))
    except Exception:
        skip_links = 0

    weak_signal_pre_main = 0
    if total >= 10 and not has_main and skip_links == 0 and positive_tabindex > 0:
        weak_signal_pre_main = 1
        offenders.append({
            "reason": "Patrón de riesgo: muchos focusables, sin 'main' ni skip-link y con tabindex>0.",
            "hint": "Verifique el orden lógico del foco y añada mecanismos de bypass."
        })

    # Aprobamos RAW si no hay señales de riesgo claras
    violations = positive_tabindex + hidden_focusable + aria_hidden_focusable + inert_focusable
    applicable = 1 if total > 0 else 0
    compliant = 1 if (applicable and violations == 0) else 0

    ok_ratio = 1.0 if applicable == 0 else (1.0 if violations == 0 else 0.0)

    details: Dict[str, Any] = {
        "focusables_found": total,
        "applicable": applicable,
        "compliant_raw": compliant,
        "violations_suspicions": violations,
        "positive_tabindex": positive_tabindex,
        "custom_tabindex_total": custom_tabindex,
        "hidden_focusable": hidden_focusable,
        "aria_hidden_focusable": aria_hidden_focusable,
        "inert_focusable": inert_focusable,
        "weak_signal_pre_main": weak_signal_pre_main,
        "offenders": offenders,
        "ok_ratio": ok_ratio,
        "note": (
            "RAW: 2.4.3 requiere que el orden del foco preserve significado y operabilidad. "
            "En estático, marcamos patrones de riesgo (tabindex>0, foco en ocultos/inert/aria-hidden). "
            "La verificación real del orden se hace en RENDERED."
        )
    }
    return details

# -------------------------------------------------------------------
# RENDERED (verificación en ejecución)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede exponer una secuencia real de tabulación:
      rctx.focus_order_test = [
        {
          "step": int,                       # 1..N
          "selector": str,
          "dom_position": int | None,        # índice relativo en DOM si lo tienes
          "tabindex": int | None,
          "is_visible": bool,
          "aria_hidden": bool,
          "inert": bool,
          "overlay_open": bool,              # hay modal/overlay activo
          "in_active_modal": bool,           # este elemento pertenece al modal activo
          "receives_focus": bool,            # realmente recibió foco al tabular
        }, ...
      ]

    Reglas (heurísticas):
      - Violación si recibe foco un elemento aria-hidden/inert/no visible.
      - Si overlay_open, el foco debe permanecer en el modal activo (in_active_modal=True).
      - Si hay muchos "saltos hacia atrás" de dom_position sin tabindex>0 declarado, pedimos revisión manual.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.4.3; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    seq = _as_list(getattr(rctx, "focus_order_test", []))
    if not seq:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'focus_order_test'.").strip()
        return d

    applicable = 1 if len(seq) > 0 else 0
    violations = 0
    manual_flags = 0
    offenders: List[Dict[str, Any]] = []

    back_jumps = 0
    comparable_pairs = 0
    prev_dom = None

    for t in seq:
        if not isinstance(t, dict):
            continue

        sel = _s(t.get("selector"))
        is_vis = bool(t.get("is_visible"))
        aria_hidden = bool(t.get("aria_hidden"))
        inert = bool(t.get("inert"))
        receives = bool(t.get("receives_focus"))
        overlay_open = bool(t.get("overlay_open"))
        in_modal = bool(t.get("in_active_modal"))
        ti = t.get("tabindex")

        # 1) Foco en ocultos/inert/aria-hidden
        if receives and (not is_vis or aria_hidden or inert):
            violations += 1
            offenders.append({
                "selector": sel,
                "reason": "Elemento oculto/aria-hidden/inert recibió foco en ejecución.",
                "observed": {"is_visible": is_vis, "aria_hidden": aria_hidden, "inert": inert}
            })

        # 2) Con overlay/modal, foco debe permanecer en el modal activo
        if receives and overlay_open and (not in_modal):
            violations += 1
            offenders.append({
                "selector": sel,
                "reason": "Con un modal/overlay activo, el foco se fue fuera del contexto activo.",
                "observed": {"overlay_open": overlay_open, "in_active_modal": in_modal}
            })

        # 3) Saltos hacia atrás por DOM (heurística informativa)
        dom_pos = t.get("dom_position")
        if isinstance(dom_pos, int):
            if isinstance(prev_dom, int):
                comparable_pairs += 1
                if dom_pos < prev_dom and not (isinstance(ti, int) and ti > 0):
                    back_jumps += 1
            prev_dom = dom_pos

    # Si más del 15% de los pares son “back-jumps”, pedimos revisión manual (no falla automáticamente)
    back_jump_ratio = (back_jumps / max(1, comparable_pairs)) if comparable_pairs > 0 else 0.0
    if back_jump_ratio > 0.15:
        manual_flags += 1
        offenders.append({
            "reason": "Se detectaron múltiples saltos hacia atrás en la secuencia de tabulación.",
            "back_jumps": back_jumps,
            "pairs_checked": comparable_pairs,
            "hint": "Revise tabindex>0, órdenes personalizados y componentes montados dinámicamente."
        })

    ok_ratio = 1.0 if applicable == 0 else (1.0 if violations == 0 else 0.0)

    d.update({
        "applicable": applicable,
        "violations_runtime": violations,
        "manual_flags": manual_flags,
        "back_jump_ratio": round(back_jump_ratio, 4),
        "ok_ratio": ok_ratio,
        "offenders": (_as_list(d.get("offenders")) + offenders),
        "note": (d.get("note","") + " | RENDERED: validación de foco en visibles/no-inertes y contención en modales; back-jumps como señal manual.").strip()
    })
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: recomienda:
      - Evitar tabindex>0; usar el orden DOM natural y tabindex=0 cuando sea necesario.
      - Asegurar que elementos aria-hidden/hidden/inert NO reciban foco.
      - Con modales: aria-modal='true', focus inicial dentro, fondo con inert/aria-hidden.
      - Mantener secuencia lógica (navegación→contenido→controles).
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    needs_help = (details.get("violations_suspicions", 0) or 0) > 0 \
                 or (details.get("violations_runtime", 0) or 0) > 0 \
                 or (details.get("manual_flags", 0) or 0) > 0

    if not needs_help:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "positive_tabindex": details.get("positive_tabindex", 0),
            "hidden_focusable": details.get("hidden_focusable", 0),
            "aria_hidden_focusable": details.get("aria_hidden_focusable", 0),
            "inert_focusable": details.get("inert_focusable", 0),
            "violations_runtime": details.get("violations_runtime", 0),
            "back_jump_ratio": details.get("back_jump_ratio", 0.0),
        },
        "offenders": (details.get("offenders", []) or [])[:25],
        "html_snippet": (html_sample or "")[:2200],
    }
    prompt = (
        "Eres auditor WCAG 2.4.3 (Focus Order). "
        "Para cada offender, propone correcciones: eliminar tabindex>0, usar DOM order, "
        "evitar foco en aria-hidden/hidden/inert, y contener foco en modales (aria-modal, inert en fondo). "
        "Devuelve JSON: { suggestions: [{selector?, issue, html_fix?, aria_fix?, css_fix?, js_fix?, notes?}], "
        "manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_2_4_3(
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

    # 3) passed / verdict / score
    applicable = int(details.get("applicable", 0) or 0)

    # Si tenemos RENDERED con violaciones en ejecución → falla.
    vr = int(details.get("violations_runtime", 0) or 0)
    # En RAW, si solo hay “sospechas”, marcamos como no-apto si son claras (tabindex>0 o foco en ocultos)
    vraw = int(details.get("violations_suspicions", 0) or 0)

    passed = (applicable == 0) or (vr == 0 and vraw == 0)

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
        title=meta.get("title", "Orden del foco"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required or (details.get("back_jump_ratio", 0.0) or 0.0) > 0.15
    )
