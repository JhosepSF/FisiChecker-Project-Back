# audits/checks/criteria/p1/c_1_3_2_meaningful_sequence.py
from typing import Dict, Any, List, Optional

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional 
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  

CODE = "1.3.2"

# -------------------------
# Utilidades
# -------------------------

def _bool_attr(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")

def _as_list(x) -> List[Dict[str, Any]]:
    if not x:
        return []
    if isinstance(x, list):
        return x
    return list(x)

_INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea", "summary"}
_INTERACTIVE_ROLES = {
    "button","link","checkbox","radio","switch","combobox","spinbutton","textbox",
    "tab","menuitem","menuitemcheckbox","menuitemradio","option","slider","treeitem"
}

def _is_focusable(el: Dict[str, Any]) -> bool:
    tag = (el.get("tag") or "").lower()
    role = (el.get("role") or "").lower()
    tabindex = el.get("tabindex")
    has_tabindex = (tabindex is not None) and str(tabindex).strip() != ""
    disabled = _bool_attr(el.get("disabled")) or _bool_attr(el.get("aria-disabled"))
    if disabled:
        return False
    if tag in _INTERACTIVE_TAGS:
        # <a> sin href no es focusable por defecto
        if tag == "a" and not (el.get("href") or "").strip():
            return bool(has_tabindex and int(str(tabindex)) >= 0)
        return True
    if role in _INTERACTIVE_ROLES:
        return True
    # tabindex>=0 vuelve focusable
    if has_tabindex and int(str(tabindex)) >= 0:
        return True
    return False

def _tabindex_value(el: Dict[str, Any]) -> Optional[int]:
    ti = el.get("tabindex")
    if ti is None:
        return None
    try:
        return int(str(ti).strip())
    except Exception:
        return None

def _is_visually_hidden(el: Dict[str, Any]) -> bool:
    """
    Señales típicas de ocultamiento visual (no exhaustivo).
    No disponemos de estilos computados aquí; dependemos del extractor.
    """
    cls = " ".join(el.get("class", [])).lower()
    return bool(
        _bool_attr(el.get("hidden")) or
        (el.get("style_display_none")) or
        (el.get("style_visibility_hidden")) or
        ("sr-only" in cls) or ("visually-hidden" in cls)
    )

def _css_order(el: Dict[str, Any]) -> Optional[int]:
    """
    Devuelve el 'order' de Flexbox si el extractor lo expone (css_order) o style_order.
    """
    for k in ("css_order", "style_order", "order"):
        if k in el and str(el.get(k)).strip() != "":
            try:
                return int(str(el.get(k)).strip())
            except Exception:
                return None
    return None

def _positioned_absolutely(el: Dict[str, Any]) -> bool:
    """
    Indica posibles reordenamientos visuales por posicionamiento.
    """
    pos = (el.get("css_position") or el.get("style_position") or "").lower()
    return pos in {"absolute", "fixed", "sticky"}

def _aria_flowto(el: Dict[str, Any]) -> bool:
    return bool((el.get("aria-flowto") or "").strip())

# -------------------------
# Núcleo del criterio
# -------------------------

def _gather_focusables(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Recolecta candidatos focusables desde varias colecciones del extractor.
    """
    # Fuentes posibles que tu extractor ya use
    controls = _as_list(getattr(ctx, "form_controls", []) or getattr(ctx, "inputs", []) or [])
    links = _as_list(getattr(ctx, "links", []))
    buttons = _as_list(getattr(ctx, "buttons", []))
    widgets = _as_list(getattr(ctx, "widgets", []))  # elementos con roles ARIA interactivos
    others = _as_list(getattr(ctx, "focusables", []))
    # Concatenamos y eliminamos duplicados por id/src/xpath si estuvieran
    seen = set()
    out: List[Dict[str, Any]] = []
    for el in controls + links + buttons + widgets + others:
        key = el.get("id") or el.get("xpath") or el.get("src") or id(el)
        if key in seen:
            continue
        seen.add(key)
        out.append(el)
    return out

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    nodes = _gather_focusables(ctx)
    total_focusables = 0
    positive_tabindex = 0
    focusable_hidden = 0
    focusable_aria_hidden = 0
    noninteractive_tabbable = 0
    flowto_count = 0

    css_reorder_flags = 0
    positioned_flags = 0

    offenders: List[Dict[str, Any]] = []

    for el in nodes:
        if not _is_focusable(el):
            ordv = _css_order(el)
            if isinstance(ordv, int) and ordv != 0:
                css_reorder_flags += 1
            if _positioned_absolutely(el):
                positioned_flags += 1
            if _aria_flowto(el):
                flowto_count += 1
            continue

        total_focusables += 1

        ti = _tabindex_value(el)
        if ti is not None and ti > 0:
            positive_tabindex += 1
            offenders.append({
                "tag": (el.get("tag") or el.get("role") or "").lower(),
                "id": el.get("id", ""),
                "name": el.get("name", ""),
                "class": el.get("class", []),
                "tabindex": ti,
                "reason": "Uso de tabindex>0 (puede romper la secuencia natural de foco)."
            })

        if _is_visually_hidden(el):
            focusable_hidden += 1
            offenders.append({
                "tag": (el.get("tag") or el.get("role") or "").lower(),
                "id": el.get("id", ""),
                "reason": "Elemento focusable oculto visualmente (puede desordenar la secuencia percibida)."
            })

        if _bool_attr(el.get("aria-hidden")):
            focusable_aria_hidden += 1
            offenders.append({
                "tag": (el.get("tag") or el.get("role") or "").lower(),
                "id": el.get("id", ""),
                "reason": "Elemento focusable con aria-hidden='true' (rompe la secuencia para AT)."
            })

        tag = (el.get("tag") or "").lower()
        role = (el.get("role") or "").lower()
        if (tag not in _INTERACTIVE_TAGS) and (role not in _INTERACTIVE_ROLES):
            ti0 = _tabindex_value(el)
            if ti0 is not None and ti0 >= 0:
                noninteractive_tabbable += 1
                offenders.append({
                    "tag": tag or role,
                    "id": el.get("id", ""),
                    "tabindex": ti0,
                    "reason": "Elemento no interactivo incluido en orden de tabulación (tabindex>=0)."
                })

        ordv = _css_order(el)
        if isinstance(ordv, int) and ordv != 0:
            css_reorder_flags += 1
            offenders.append({
                "tag": tag or role,
                "id": el.get("id", ""),
                "css_order": ordv,
                "reason": "Reordenamiento visual por CSS 'order' (puede desalinear DOM vs percepción)."
            })
        if _positioned_absolutely(el):
            positioned_flags += 1
            offenders.append({
                "tag": tag or role,
                "id": el.get("id", ""),
                "reason": "Posicionamiento absoluto/fijo (puede alterar la secuencia visual)."
            })

        if _aria_flowto(el):
            flowto_count += 1
            offenders.append({
                "tag": tag or role,
                "id": el.get("id", ""),
                "reason": "Uso de aria-flowto (altera el orden de lectura de AT; requiere revisión)."
            })

    # Violaciones que SÍ bloquean (en RAW)
    violations = positive_tabindex + focusable_hidden + focusable_aria_hidden + noninteractive_tabbable

    # ok_ratio: si no hay muestra, 1.0 (y lo marcamos como N/A)
    denom = total_focusables
    ok_ratio = 1.0 if denom == 0 else max(0.0, min(1.0, round((total_focusables - violations) / denom, 4)))

    details: Dict[str, Any] = {
        "focusables_total": total_focusables,
        "positive_tabindex": positive_tabindex,
        "focusable_hidden": focusable_hidden,
        "focusable_aria_hidden": focusable_aria_hidden,
        "noninteractive_tabbable": noninteractive_tabbable,
        "css_reorder_flags": css_reorder_flags,
        "positioned_flags": positioned_flags,
        "aria_flowto_count": flowto_count,
        "reading_sequence_mismatches": None,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 1.3.2 busca que el orden de presentación transmita el significado. "
            "Penaliza tabindex>0, elementos focusable ocultos o aria-hidden y no interactivos en el orden de tabulación. "
            "Señala (como revisión) reordenamientos visuales por CSS ('order', position abs/fixed) y uso de aria-flowto."
        )
    }

    # N/A si literalmente no hay nada que evaluar (todo en cero)
    if (
        total_focusables == 0 and
        positive_tabindex == 0 and
        focusable_hidden == 0 and
        focusable_aria_hidden == 0 and
        noninteractive_tabbable == 0 and
        css_reorder_flags == 0 and
        positioned_flags == 0 and
        flowto_count == 0
    ):
        details["na"] = True

    return details

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En DOM post-render (Playwright), puedes:
      - Calcular el orden REAL de tabulación (tab order) recorriendo focusables visibles.
      - Calcular orden VISUAL aproximado por bounding boxes (orden por top->left).
      - Comparar ambos órdenes vs el orden DOM (si lo expones) y contar desfases.
      - Marcar 'reading_sequence_mismatches' con el número de grandes inversiones detectadas.
    Para habilitar esto, tu extractor debería exponer:
      rctx.tab_order = [ {id, tag, bbox:{x,y,w,h}} ... ]  # secuencia de foco navegable
      rctx.visual_boxes = [ {id, tag, bbox:{x,y,w,h}} ... ]  # nodos relevantes en orden DOM
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.3.2; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)  # reutiliza conteos básicos
    d["rendered"] = True

    tab_order = _as_list(getattr(rctx, "tab_order", []))
    visual_boxes = _as_list(getattr(rctx, "visual_boxes", []))

    mismatches = 0
    if tab_order and visual_boxes:
        # Índices por id para comparar posiciones relativas
        idx_visual = { (n.get("id") or n.get("xpath") or f"v{ix}"): ix for ix, n in enumerate(visual_boxes) }
        prev_ix = None
        for node in tab_order:
            key = node.get("id") or node.get("xpath") or ""
            if key == "" or key not in idx_visual:
                continue
            ix = idx_visual[key]
            if prev_ix is not None and ix + 3 < prev_ix:
                # si el foco salta “muy atrás” respecto al flujo visual, contamos como un desfase
                mismatches += 1
            prev_ix = ix

    d["reading_sequence_mismatches"] = mismatches if (tab_order and visual_boxes) else None
    d["note"] = (
        d.get("note", "") +
        " | RENDERED: compara orden de foco vs flujo visual (por bounding boxes). "
        "Los desfases indican posible ruptura de secuencia significativa."
    ).strip()
    return d

# -------------------------
# IA opcional
# -------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    Si hay problemas, la IA sugiere fixes:
      - Sustituir tabindex>0 por orden DOM correcto (o tabindex=0 cuando proceda)
      - Quitar foco de elementos ocultos; sincronizar aria-hidden/hidden con foco
      - Evitar reordenamientos visuales que rompan lectura (alinea DOM con presentación)
      - Alternativas: skip links, navegación coherente, reestructurar contenedores
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    issues = (
        details.get("positive_tabindex", 0)
        + details.get("focusable_hidden", 0)
        + details.get("focusable_aria_hidden", 0)
        + details.get("noninteractive_tabbable", 0)
        + (details.get("reading_sequence_mismatches", 0) or 0)
    )
    if issues == 0:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "positive_tabindex": details.get("positive_tabindex", 0),
            "focusable_hidden": details.get("focusable_hidden", 0),
            "focusable_aria_hidden": details.get("focusable_aria_hidden", 0),
            "noninteractive_tabbable": details.get("noninteractive_tabbable", 0),
            "css_reorder_flags": details.get("css_reorder_flags", 0),
            "positioned_flags": details.get("positioned_flags", 0),
            "reading_sequence_mismatches": details.get("reading_sequence_mismatches", None),
        },
        "offenders": details.get("offenders", [])[:15],
        "html_snippet": (html_sample or "")[:2500],
    }
    prompt = (
        "Actúa como auditor WCAG 1.3.2 (Secuencia significativa). "
        "Propón fixes concretos para cada offender: "
        "- Reemplazar tabindex>0 por orden DOM natural (o tabindex=0) y ejemplo de HTML; "
        "- Quitar foco de elementos ocultos (ocultar con aria-hidden y tabindex='-1', o no renderizar); "
        "- Alinear DOM con presentación para evitar desorden por 'order' o 'position:absolute'; "
        "- Añadir skip links y asegurar que el foco sigue el flujo visual; "
        "Devuelve JSON: { suggestions: [{reason, fix_html, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------
# Orquestación
# -------------------------

def run_1_3_2(
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

    # IA opcional
    manual_required = False
    if mode == CheckMode.AI:
        ai_info = _ai_review(details, html_sample=html_for_ai)
        details["ai_info"] = ai_info
        src = "ai"
        manual_required = ai_info.get("manual_required", False)

    # Si el propio detalle marca N/A, forzamos verdict='na'
    if details.get("na") is True:
        verdict = "na"
        score0 = score_from_verdict(verdict)
    else:
        violations = (
            details.get("positive_tabindex", 0)
            + details.get("focusable_hidden", 0)
            + details.get("focusable_aria_hidden", 0)
            + details.get("noninteractive_tabbable", 0)
        )
        passed = (violations == 0)
        verdict = verdict_from_counts(details, passed)
        score0 = score_from_verdict(verdict)

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE,
        passed=(verdict == "pass"),
        verdict=verdict,
        score_0_2=score0,
        details=details,
        level=meta.get("level", "A"),
        principle=meta.get("principle", "Perceptible"),
        title=meta.get("title", "Secuencia significativa"),
        source=src,
        score_hint=(None if verdict == "na" else details.get("ok_ratio")),
        manual_required=manual_required or (details.get("css_reorder_flags", 0) > 0) or (details.get("positioned_flags", 0) > 0)
    )
