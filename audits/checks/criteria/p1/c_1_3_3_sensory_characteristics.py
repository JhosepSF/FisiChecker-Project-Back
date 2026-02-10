# audits/checks/criteria/p1/c_1_3_3_sensory_characteristics.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional 
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  # si no existe, el modo IA queda deshabilitado

CODE = "1.3.3"

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

_COLOR_WORDS = {
    "rojo","roja","verde","azul","amarillo","amarilla","negro","negra","blanco","blanca",
    "naranja","morado","lila","violeta","rosado","rosa","celeste","cian","turquesa","gris",
    "plomo","fucsia","marrón","marron","beige","dorado","plateado"
}
_SHAPE_WORDS = {
    "círculo","circulo","cuadrado","rectángulo","rectangulo","triángulo","triangulo",
    "rombo","estrella","flecha","ovalo","óvalo","hexágono","hexagono","icono","ícono","íconos","iconos"
}
_LOCATION_WORDS = {
    "izquierda","derecha","arriba","abajo","superior","inferior","a la izquierda","a la derecha",
    "columna izquierda","columna derecha","panel izquierdo","panel derecho","primer cuadro","segundo cuadro"
}
_SENSORY_WORDS = {
    "sonido","audio","pitido","campana","alarma","vibración","vibracion","tono","beep","bip"
}

# patrones típicos de instrucciones dependientes de características sensoriales
_PATTERNS = [
    re.compile(r"\b(botón|boton|enlace|link)\s+(rojo|verde|azul|amarill[oa]|neg[r|ra]|blanc[oa])", re.I),
    re.compile(r"\b(haz clic|click|presiona|pulse|selecciona)\s+(el|la)\s+(botón|boton|enlace)\s+(de|en)\s+(color)\s+(\w+)", re.I),
    re.compile(r"\b(haz clic|click|presiona|pulse|selecciona)\s+(en|el)\s+(círculo|circulo|cuadrado|triángulo|triangulo|flecha)", re.I),
    re.compile(r"\b(a la|en la|en el)\s+(izquierda|derecha|parte superior|parte inferior)\b", re.I),
    re.compile(r"\b(sigue|use|utiliza|utilice)\s+el\s+sonido\b", re.I),
]

def _text_has_sensory_cues(text: str) -> Tuple[bool, Dict[str, bool]]:
    t = (text or "").strip()
    if not t:
        return False, {"color": False, "shape": False, "location": False, "sound": False, "pattern": False}
    low = t.lower()

    has_color = any(w in low for w in _COLOR_WORDS)
    has_shape = any(w in low for w in _SHAPE_WORDS)
    has_location = any(w in low for w in _LOCATION_WORDS)
    has_sound = any(w in low for w in _SENSORY_WORDS)
    has_pattern = any(p.search(t) for p in _PATTERNS)

    flagged = has_color or has_shape or has_location or has_sound or has_pattern
    return flagged, {
        "color": has_color,
        "shape": has_shape,
        "location": has_location,
        "sound": has_sound,
        "pattern": has_pattern
    }

def _collect_instruction_texts(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Extrae textos donde suelen aparecer instrucciones:
      - encabezados / párrafos / etiquetas / títulos / tooltips
      - botones, enlaces, controles (label_text, aria-label, title, placeholder)
      - regiones informativas (role=alert, status, note)
      - opcional: ctx.text_nodes si el extractor lo provee
    """
    out: List[Dict[str, Any]] = []

    # headings
    for h in _as_list(getattr(ctx, "headings", []) or []):
        out.append({"source": "heading", "text": h.get("text") or h.get("inner_text") or ""})

    # paragraphs / generic text blocks
    for p in _as_list(getattr(ctx, "paragraphs", []) or getattr(ctx, "text_blocks", []) or []):
        out.append({"source": "paragraph", "text": p.get("text") or p.get("inner_text") or ""})

    # labels de formularios
    for c in _as_list(getattr(ctx, "form_controls", []) or getattr(ctx, "inputs", []) or []):
        if c.get("label_text"):
            out.append({"source": "label", "text": c.get("label_text")})
        for key in ("aria-label", "title", "placeholder", "aria-describedby_text", "help_text"):
            if c.get(key):
                out.append({"source": f"control:{key}", "text": c.get(key)})

    # botones / links
    for b in _as_list(getattr(ctx, "buttons", []) or []):
        out.append({"source": "button", "text": b.get("text") or b.get("aria-label") or b.get("title") or ""})
    for a in _as_list(getattr(ctx, "links", []) or []):
        out.append({"source": "link", "text": a.get("text") or a.get("aria-label") or a.get("title") or ""})

    # regiones informativas
    for n in _as_list(getattr(ctx, "live_regions", []) or getattr(ctx, "notes", []) or []):
        out.append({"source": "region", "text": n.get("text") or n.get("aria-label") or ""})

    # texto plano si lo expones
    for t in _as_list(getattr(ctx, "text_nodes", []) or []):
        tx = t.get("text") or ""
        if tx.strip():
            out.append({"source": "textnode", "text": tx})

    return out

def _is_icon_only_interactive(el: Dict[str, Any]) -> bool:
    """
    Heurística: botón/enlace que solo tiene icono (svg/i) y no tiene accesible name.
    El extractor puede marcar 'icon_only' o 'is_icon_button'.
    """
    tag = (el.get("tag") or "").lower()
    if tag not in {"button","a"} and (el.get("role") not in {"button","link"}):
        return False
    name = (el.get("aria-label") or el.get("title") or el.get("text") or "").strip()
    if name:
        return False
    if el.get("icon_only") or el.get("is_icon_button") or el.get("has_icon"):
        return True
    # fallback: texto muy corto típico de iconos (p.ej., "▶", "×")
    txt = (el.get("text") or "").strip()
    return bool(txt and len(txt) <= 2)

# -------------------------
# Núcleo del criterio
# -------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    texts = _collect_instruction_texts(ctx)

    total_texts = len(texts)
    flagged = 0
    flagged_color = 0
    flagged_shape = 0
    flagged_location = 0
    flagged_sound = 0
    offenders_text: List[Dict[str, Any]] = []

    for item in texts:
        ok, kinds = _text_has_sensory_cues(item["text"])
        if ok:
            flagged += 1
            if kinds["color"]: flagged_color += 1
            if kinds["shape"]: flagged_shape += 1
            if kinds["location"]: flagged_location += 1
            if kinds["sound"]: flagged_sound += 1
            offenders_text.append({
                "type": "instruction_text",
                "source": item["source"],
                "snippet": (item["text"] or "")[:200],
                "kinds": [k for k, v in kinds.items() if v]
            })

    # Icon-only interactivos: fomentan instrucciones “haz clic en el ícono …”
    icon_only_offenders: List[Dict[str, Any]] = []
    icon_only_count = 0
    for el in _as_list(getattr(ctx, "buttons", []) or []) + _as_list(getattr(ctx, "links", []) or []):
        if _is_icon_only_interactive(el):
            icon_only_count += 1
            icon_only_offenders.append({
                "type": "icon_only_interactive",
                "tag": (el.get("tag") or el.get("role") or "").lower(),
                "id": el.get("id", ""),
                "class": el.get("class", []),
                "reason": "Elemento interactivo solo con icono, sin nombre accesible."
            })

    total_flags = flagged + icon_only_count

    ok_ratio = 1.0 if total_texts == 0 else round(max(0.0, min(1.0, (total_texts - flagged) / max(1, total_texts))), 4)

    details: Dict[str, Any] = {
        "texts_examined": total_texts,
        "flagged_texts": flagged,
        "flagged_color": flagged_color,
        "flagged_shape": flagged_shape,
        "flagged_location": flagged_location,
        "flagged_sound": flagged_sound,
        "icon_only_interactives": icon_only_count,
        "offenders": offenders_text + icon_only_offenders,
        "ok_ratio": ok_ratio,
        "note": (
            "RAW: 1.3.3 detecta indicios de instrucciones que dependen de color/forma/posición/sonido "
            "(p. ej., 'presiona el botón rojo', 'ver el círculo a la derecha'). "
            "También marca botones/enlaces solo con icono y sin nombre accesible. "
            "Heurístico: requiere revisión manual para confirmar el contexto."
        )
    }
    if total_texts == 0 and icon_only_count == 0:
        details["na"] = True

    return details

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    Con DOM post-render (Playwright) puedes mejorar:
      - Detectar botones con 'aria-label' vacío y solo <svg>/<i> visibles.
      - Extraer tooltips/labels computados del UI.
      - Mapear bounding boxes para confirmar referencias de posición (izquierda/derecha).
      - Localizar leyendas 'color-only' en la UI (clases 'text-danger', 'badge-green', etc.) si lo marcas.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.3.3; no se pudo evaluar en modo renderizado."}
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note", "") + " | RENDERED: refuerza icon-only y posición real por bounding boxes/ARIA.").strip()
    return d

# -------------------------
# IA opcional
# -------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    Pide a la IA reescrituras neutrales a características sensoriales:
      - Reemplazar 'botón rojo' por el nombre/texto del control.
      - Reemplazar 'a la derecha' por una referencia de etiqueta/encabezado/sección.
      - Añadir nombre accesible a icon-only.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    offenders = details.get("offenders", [])
    if not offenders:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "offenders": offenders[:15],
        "html_snippet": (html_sample or "")[:2500],
    }
    prompt = (
        "Eres auditor WCAG para 1.3.3 (Características sensoriales). "
        "Reescribe cada instrucción para NO depender de color/forma/posición/sonido. "
        "Si el offender es 'icon_only_interactive', propone un 'aria-label' o texto visible. "
        "Devuelve JSON: { suggestions: [{type, source?, snippet?, fix_text?, aria_label?}], "
        "manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------
# Orquestación
# -------------------------

def run_1_3_3(
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
        manual_required = ai_info.get("manual_required", False)

    # 3) passed / verdict / score
    if details.get("na") is True:
        verdict = "na"
        score0 = score_from_verdict(verdict)
        score_hint = None
    else:
        total_flags = details.get("flagged_texts", 0) + details.get("icon_only_interactives", 0)
        passed = (total_flags == 0)
        verdict = verdict_from_counts(details, passed)
        score0 = score_from_verdict(verdict)
        score_hint = details.get("ok_ratio")

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE,
        passed=(verdict == "pass"),
        verdict=verdict,
        score_0_2=score0,
        details=details,
        level=meta.get("level", "A"),
        principle=meta.get("principle", "Perceptible"),
        title=meta.get("title", "Características sensoriales"),
        source=src,
        score_hint=score_hint,
        manual_required=manual_required
    )