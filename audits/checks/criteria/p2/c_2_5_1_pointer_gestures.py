# audits/checks/criteria/p2/c_2_5_1_pointer_gestures.py
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

CODE = "2.5.1"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

_DRAG_CLASSES = re.compile(
    r"(drag|draggable|sortable|resizable|slider|handle|panzoom|pan|swipe|carousel|slick|swiper|flickity|glide|mapbox|leaflet)",
    re.I,
)
_GESTURE_HINTS = re.compile(
    r"(desliza|arrastra|mant[eé]n|mueve|swipe|drag|pinch|pellizca|zoom con dos dedos|gira|rotate)",
    re.I,
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

def _get_attr(node: Any, name: str) -> Optional[str]:
    """Seguro para dict o Tag (BS4)."""
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

def _get_text(node: Any) -> str:
    if isinstance(node, dict):
        for k in ("text","label","aria-label","title","accessible_name","inner_text","help_text"):
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

def _nearby_has_alternative_buttons(node: Any) -> bool:
    """
    Heurística débil (RAW): si el mismo contenedor inmediato tiene botones 'prev/next', 'zoom +/-', 'reset',
    asumimos alternativa de un solo puntero sin gesto de trazo.
    """
    try:
        parent = getattr(node, "parent", None)
        if parent is None:
            return False
        if hasattr(parent, "find_all"):
            btns = parent.find_all(["button","a"])
            for b in btns[:12]:
                txt = (_get_text(b) or "").lower()
                aria = (_get_attr(b, "aria-label") or "").lower()
                if re.search(r"(prev|next|siguiente|anterior|zoom|\+|\-|\bmas\b|\bmenos\b|reset|reinci)", txt+ " " + aria):
                    return True
    except Exception:
        pass
    return False

# ------------------------------------------------------------
# Detección de “candidatos a gesto multipunto o de trazo”
# ------------------------------------------------------------

def _collect_gesture_candidates(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Busca widgets conocidos por requerir arrastre/gesto:
      - clases comunes (swiper/slick/carousel/drag/sortable/panzoom/map/leaflet/mapbox)
      - atributos draggable / data-*
      - textos de ayuda que digan “desliza/arrastra/pellizca”
    """
    soup = getattr(ctx, "soup", None)
    out: List[Dict[str, Any]] = []

    # 1) Desde un posible inventario del extractor
    for n in _as_list(getattr(ctx, "gesture_widgets", [])):
        if isinstance(n, dict):
            out.append(n)

    # 2) Heurística DOM si no hay inventario
    if soup is not None and not out:
        try:
            # cualquier nodo con clase “drag/slick/swiper/carousel/map…”
            all_nodes = soup.find_all(True)
            for el in all_nodes[:2000]:
                cls = _s(_get_attr(el, "class"))
                role = _lower(_get_attr(el, "role"))
                draggable = _bool(_get_attr(el, "draggable"))
                title = _s(_get_attr(el, "title"))
                aria = _s(_get_attr(el, "aria-label"))
                text = _get_text(el)
                hint_blob = " ".join([cls, role, title, aria, text])
                if _DRAG_CLASSES.search(cls) or draggable or _GESTURE_HINTS.search(hint_blob):
                    out.append({
                        "selector": _s(getattr(el, "name", "")) + "#" + _s(getattr(el, "get", lambda *_a, **_k: "")("id")),
                        "class": cls,
                        "role": role,
                        "title": title,
                        "aria_label": aria,
                        "text": (text or "")[:140],
                        "source": "heuristic"
                    })
        except Exception:
            pass

    return out

def _looks_essential(widget: Dict[str, Any]) -> bool:
    """
    Si parece un lienzo de dibujo / firma / herramienta de gestos *esenciales*, no contamos violación (nota informativa).
    """
    blob = " ".join([
        _lower(widget.get("class")),
        _lower(widget.get("role")),
        _lower(widget.get("title")),
        _lower(widget.get("aria_label")),
        _lower(widget.get("text")),
        _lower(widget.get("type")),
        _lower(widget.get("widget_type")),
    ])
    return bool(re.search(r"(signature|firma|lienzo|canvas|draw|dibujo|paint|pintar)", blob))

def _has_single_pointer_alternative(widget_node: Any) -> bool:
    """
    En RAW, si detectamos botones vecinos (prev/next/zoom +/-), asumimos alternativa de un solo puntero.
    Para dicts del extractor, revisa flag 'has_alternative_controls'.
    """
    if isinstance(widget_node, dict):
        if widget_node.get("has_alternative_controls") is True:
            return True
        # si trae 'node' (Tag) úsalo
        tn = widget_node.get("node")
        if tn is not None:
            return _nearby_has_alternative_buttons(tn)
        return False
    # Tag
    return _nearby_has_alternative_buttons(widget_node)

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.5.1 (A): La funcionalidad que usa gestos de trazo o multipunto debe poder operarse con un solo puntero
    sin necesidad de gesto trazado (ej., clic en botones, taps discretos).
    """
    soup = getattr(ctx, "soup", None)
    candidates = _collect_gesture_candidates(ctx)

    applicable = 0
    with_alternative = 0
    essential_like = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    # Si el extractor no pudo encontrar nada, asumimos NA salvo que existan pistas claras
    if not candidates and soup is not None:
        # pista mínima: carrouseles comunes
        try:
            if soup.find(attrs={"class": re.compile(r"(slick|swiper|carousel)", re.I)}):
                candidates = [{"selector": "auto-carousel", "class": "carousel"}]
        except Exception:
            pass

    for w in candidates:
        applicable += 1
        if _looks_essential(w):
            essential_like += 1
            continue

        has_alt = _has_single_pointer_alternative(w)
        if has_alt:
            with_alternative += 1
        else:
            violations += 1
            offenders.append({
                "widget": {k: w.get(k) for k in ("selector","class","role","title","aria_label","text") if w.get(k) is not None},
                "reason": "No se detectó alternativa de un solo puntero (botones/controles) para un widget con gesto trazado o multipunto."
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, with_alternative / max(1, applicable - essential_like))), 4)

    details: Dict[str, Any] = {
        "candidates_found": applicable,
        "essential_like": essential_like,
        "with_alternative": with_alternative,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 2.5.1 exige alternativa de un solo puntero para gestos de trazo/multipunto. "
            "Se consideran alternativas: botones prev/next para carruseles, +/- para zoom, "
            "tap sobre pista para sliders, etc. Casos esencialmente gestuales (firma/dibujo) no cuentan como violación."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede probar gestos y alternativas:
      rctx.gesture_test = [
        { "selector": str, "requires_path_gesture": bool, "requires_multipoint": bool,
          "has_single_pointer_alternative": bool, "essential": bool, "notes": str|None }, ...
      ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.5.1; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "gesture_test", []))
    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = (d.get("note","") + " | RENDERED: sin 'gesture_test', se reusó RAW.").strip()
        return d

    applicable = 0
    essential_like = 0
    with_alternative = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for t in data:
        if not isinstance(t, dict):
            continue
        requires = bool(t.get("requires_path_gesture")) or bool(t.get("requires_multipoint"))
        if not requires:
            continue
        applicable += 1
        if bool(t.get("essential")):
            essential_like += 1
            continue
        if bool(t.get("has_single_pointer_alternative")):
            with_alternative += 1
        else:
            violations += 1
            offenders.append({
                "selector": _s(t.get("selector")),
                "reason": "Se requiere gesto de trazo/multipunto sin alternativa de un solo puntero (runtime).",
                "notes": _s(t.get("notes"))
            })

    ok_ratio = 1.0 if applicable == 0 else (1.0 if violations == 0 else 0.0)
    details: Dict[str, Any] = {
        "rendered": True,
        "candidates_found": applicable,
        "essential_like": essential_like,
        "with_alternative": with_alternative,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: prueba de gestos y alternativas ejecutadas por el extractor."
    }
    return details

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    needs = (details.get("violations", 0) or 0) > 0
    if not needs:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "offenders": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2200],
        "recipes": [
            "Carrusel: añadir botones <button aria-label='Siguiente'> y <button aria-label='Anterior'>.",
            "Mapa: añadir controles +/- visibles con tabindex y rol adecuados.",
            "Slider custom: permitir clicks discretos en pista e incrementos con botones +/−.",
        ]
    }
    prompt = (
        "Eres auditor WCAG 2.5.1 (Pointer Gestures, A). "
        "Para cada offender, propone una alternativa de un solo puntero, con snippet HTML/CSS/JS mínimo y racional. "
        "Devuelve JSON: { suggestions: [{selector?, snippet, rationale}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_2_5_1(
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
        manual_required = bool(ai_info.get("manual_review", False))

    violations = int(details.get("violations", 0) or 0)
    candidates = int(details.get("candidates_found", 0) or 0)
    passed = (candidates == 0) or (violations == 0)

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
        title=meta.get("title", "Gestos con puntero"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
