# audits/checks/criteria/p1/c_1_4_1_use_of_color.py
from typing import Dict, Any, List, Optional
import re
import unicodedata

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional 
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  # si no existe, el modo IA queda deshabilitado

CODE = "1.4.1"

# -------------------------
# Utilidades
# -------------------------

def _as_list(x):
    if not x:
        return []
    if isinstance(x, list):
        return x
    return list(x)

def _bool(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")

def _norm(s: Optional[str]) -> str:
    if not s:
        return ""
    s2 = unicodedata.normalize("NFKD", s)
    s2 = s2.encode("ascii", "ignore").decode("ascii")
    return s2.lower().strip()

# -------------------------
# Heurísticas (fuera de contraste)
# 1.4.1 prohíbe que el color sea el ÚNICO medio para transmitir info/acción/estado.
# -------------------------

def _link_has_noncolor_cue(a: Dict[str, Any]) -> bool:
    """
    Consideramos 'no-color' cues para enlaces:
      - subrayado (text-decoration: underline)
      - icono adyacente (↗, 🔗) o 'has_icon'
      - estilo botón/chip (border/badge/pill) indicado por flags del extractor
      - distinto peso/tipo (bold/italic) marcado por flags
    """
    if _bool(a.get("has_icon")) or _bool(a.get("has_adjacent_icon")):
        return True
    deco = (a.get("text_decoration") or a.get("computed_text_decoration") or "").lower()
    if "underline" in deco:
        return True
    if _bool(a.get("is_button_style")) or _bool(a.get("has_border_bottom")):
        return True
    if _bool(a.get("is_bold")) or _bool(a.get("is_italic")):
        return True
    # si el extractor ya nos dio el veredicto
    if _bool(a.get("link_has_noncolor_cue")):
        return True
    return False

def _link_relies_on_color_only(a: Dict[str, Any]) -> bool:
    """
    Señalamos como riesgo si:
      - es un enlace 'inline' (no botón) y
      - NO tiene subrayado ni otras señales no-color, y
      - el extractor marca que el estilo es similar al texto circundante excepto por color.
    """
    if _bool(a.get("is_button_style")):
        return False  # botones/cta suelen tener múltiples señales
    if _link_has_noncolor_cue(a):
        return False
    # heurística del extractor: 'surrounding_text_same_style' excepto color
    if _bool(a.get("surrounding_same_except_color")):
        return True
    # fallback: si explícitamente se marcó
    if _bool(a.get("link_color_only")):
        return True
    # si sabemos que NO hay underline y no hay otra pista → riesgo
    deco = (a.get("text_decoration") or a.get("computed_text_decoration") or "").lower()
    if "underline" not in deco:
        return True
    return False

_REQ_WORDS = {"requerido","obligatorio","required","mandatory"}
_ERR_WORDS = {"error","invalido","inválido","incorrecto","requerido","requerida","required","invalid"}

def _required_relies_on_color_only(ctrl: Dict[str, Any]) -> bool:
    """
    Campo requerido indicado solo por color del label/borde:
      - is_required True
      - label SIN '*' ni palabras de requerido
      - sin texto/helper que lo indique
      - extractor marca que la única diferencia visual es color (label_color_only / border_color_only)
    """
    if not _bool(ctrl.get("is_required")) and not _bool(ctrl.get("aria-required")):
        return False
    label = _norm(ctrl.get("label_text") or "")
    placeholder = _norm(ctrl.get("placeholder") or "")
    helptext = _norm(ctrl.get("help_text") or ctrl.get("aria-describedby_text") or "")
    has_star = "*" in (ctrl.get("label_text") or "")
    says_req = any(w in label for w in _REQ_WORDS) or any(w in helptext for w in _REQ_WORDS)
    if has_star or says_req:
        return False
    if _bool(ctrl.get("required_color_only")):
        return True
    # heurística: marcado por extractor como 'label_color_only' o 'border_color_only'
    if _bool(ctrl.get("label_color_only")) or _bool(ctrl.get("border_color_only")):
        return True
    # si no tenemos pistas, no marcamos
    return False

def _error_relies_on_color_only(ctrl: Dict[str, Any]) -> bool:
    """
    Estado de error solo por color (rojo/borde) sin texto/ícono:
      - has_error_state True
      - no hay error_message_text ni icono de error
      - extractor marca 'error_color_only'
    """
    if not _bool(ctrl.get("has_error_state")):
        return False
    if (ctrl.get("error_message_text") or "").strip():
        return False
    if _bool(ctrl.get("has_error_icon")):
        return False
    if _bool(ctrl.get("error_color_only")):
        return True
    # bordes/labels rojos sin texto
    if _bool(ctrl.get("label_is_red")) or _bool(ctrl.get("border_is_red")):
        return True
    return False

def _status_relies_on_color_only(badge: Dict[str, Any]) -> bool:
    """
    Badges/etiquetas de estado diferenciadas solo por color (success/warn/error).
      - no hay texto (o es ambiguo: '●')
      - no hay icono con forma distinta
      - extractor marca 'color_only'
    """
    text = _norm(badge.get("text") or badge.get("title") or "")
    if text and text not in {"●", "•", ""}:
        return False
    if _bool(badge.get("has_icon")) or _bool(badge.get("has_shape_marker")):
        return False
    if _bool(badge.get("color_only")) or _bool(badge.get("status_color_only")):
        return True
    return False

def _chart_uses_color_only(ch: Dict[str, Any]) -> bool:
    """
    Gráficos/leyendas con series/categorías distinguibles solo por color:
      - series_count > 1
      - legend_labels_present False
      - no hay patrones/marcadores diferentes
    """
    if int(ch.get("series_count") or 0) <= 1:
        return False
    if _bool(ch.get("legend_labels_present")):
        return False
    if _bool(ch.get("series_have_distinct_markers")) or _bool(ch.get("uses_patterns")):
        return False
    # marca explícita del extractor:
    if _bool(ch.get("uses_color_only")):
        return True
    # si no hay labels y no hay marcadores → riesgo
    return True

# -------------------------
# Núcleo del criterio
# -------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW: marcamos casos donde el color parece ser el ÚNICO medio para transmitir:
      - Enlaces inline sin subrayado/indicadores (solo cambian color).
      - Campos requeridos/errores indicados solo por color.
      - Badges/estados diferenciados solo por color.
      - Gráficos/leyendas con distinción solo por color.
    No se verifica contraste (eso es 1.4.3/1.4.11).
    """
    links = _as_list(getattr(ctx, "links", []))
    controls = _as_list(getattr(ctx, "form_controls", []) or getattr(ctx, "inputs", []) or [])
    badges = _as_list(getattr(ctx, "badges", []) or getattr(ctx, "status_indicators", []) or [])
    charts = _as_list(getattr(ctx, "charts", []) or getattr(ctx, "graphs", []) or [])

    # Enlaces
    links_total = 0
    links_color_only = 0
    link_offenders: List[Dict[str, Any]] = []
    for a in links:
        if (a.get("tag") or "a").lower() not in {"a","link"}:
            continue
        links_total += 1
        if _link_relies_on_color_only(a):
            links_color_only += 1
            link_offenders.append({
                "type": "link",
                "text": (a.get("text") or a.get("aria-label") or a.get("title") or "")[:140],
                "id": a.get("id", ""),
                "class": a.get("class", []),
                "reason": "Enlace inline diferenciado solo por color (sin subrayado ni otra pista)."
            })

    # Formularios: requerido / error
    ctrls_total = 0
    required_color_only = 0
    error_color_only = 0
    ctrl_offenders: List[Dict[str, Any]] = []
    for c in controls:
        tag = (c.get("tag") or "").lower()
        if tag not in {"input","select","textarea"} and (c.get("role") or "") not in {"textbox","combobox","listbox"}:
            continue
        ctrls_total += 1
        if _required_relies_on_color_only(c):
            required_color_only += 1
            ctrl_offenders.append({
                "type": "required",
                "id": c.get("id",""),
                "name": c.get("name",""),
                "label": (c.get("label_text") or "")[:140],
                "reason": "Campo requerido indicado solo por color (sin texto/asterisco)."
            })
        if _error_relies_on_color_only(c):
            error_color_only += 1
            ctrl_offenders.append({
                "type": "error",
                "id": c.get("id",""),
                "name": c.get("name",""),
                "label": (c.get("label_text") or "")[:140],
                "reason": "Estado de error indicado solo por color (sin mensaje ni icono)."
            })

    # Badges/estados
    badges_total = len(badges)
    badges_color_only = 0
    badge_offenders: List[Dict[str, Any]] = []
    for b in badges:
        if _status_relies_on_color_only(b):
            badges_color_only += 1
            badge_offenders.append({
                "type": "badge",
                "id": b.get("id",""),
                "text": (b.get("text") or "")[:100],
                "class": b.get("class", []),
                "reason": "Estado/resultado diferenciado solo por color."
            })

    # Gráficos/leyendas
    charts_total = len(charts)
    charts_color_only = 0
    chart_offenders: List[Dict[str, Any]] = []
    for ch in charts:
        if _chart_uses_color_only(ch):
            charts_color_only += 1
            chart_offenders.append({
                "type": "chart",
                "id": ch.get("id",""),
                "series_count": int(ch.get("series_count") or 0),
                "reason": "Gráfico/leyenda distingue series/categorías solo por color."
            })

    violations = links_color_only + required_color_only + error_color_only + badges_color_only + charts_color_only
    denom = max(1, links_total + ctrls_total + badges_total + charts_total)
    ok_ratio = round(max(0.0, min(1.0,
        (denom - violations) / denom
    )), 4)

    details: Dict[str, Any] = {
        "links_total": links_total,
        "links_color_only": links_color_only,
        "controls_total": ctrls_total,
        "required_color_only": required_color_only,
        "error_color_only": error_color_only,
        "badges_total": badges_total,
        "badges_color_only": badges_color_only,
        "charts_total": charts_total,
        "charts_color_only": charts_color_only,
        "ok_ratio": ok_ratio,
        "offenders": link_offenders + ctrl_offenders + badge_offenders + chart_offenders,
        "note": (
            "RAW: 1.4.1 exige que el color NO sea el único medio para transmitir información, acción o estado. "
            "Se señalan enlaces inline sin subrayado u otras pistas; campos 'requeridos' o 'en error' indicados solo por color; "
            "badges/estados sin texto/icono; y gráficos/leyendas que distinguen categorías solo por color. "
            "Este check no evalúa contraste (1.4.3/1.4.11)."
        )
    }

    # N/A si no hay absolutamente nada que revisar en este criterio
    if links_total == 0 and ctrls_total == 0 and badges_total == 0 and charts_total == 0:
        details["na"] = True

    return details

# -------------------------
# Rendered
# -------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    Con DOM post-render (Playwright) puedes:
      - Extraer 'text-decoration' real de <a> (subrayado).
      - Marcar 'surrounding_same_except_color' comparando estilos computados.
      - Detectar mensajes de error visibles y asteriscos generados por CSS (::after).
      - Inspeccionar leyendas de gráficos (series con marker/pattern).
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.4.1; no se pudo evaluar en modo renderizado."}
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note","") + " | RENDERED: usa estilos computados (subrayado/::after), y leyendas efectivas en gráficos.").strip()
    return d

# -------------------------
# IA opcional
# -------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    Sugerencias automáticas:
      - Enlaces: añadir subrayado/u otra pista no-color.
      - Formularios: añadir '*' o '(requerido)' y mensajes de error textuales/íconos.
      - Badges/estados: añadir texto/icono y/o patrón/forma.
      - Gráficos: añadir leyenda textual, marcadores distintos o patrones de relleno.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    if not details.get("offenders"):
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "links_color_only": details.get("links_color_only", 0),
            "required_color_only": details.get("required_color_only", 0),
            "error_color_only": details.get("error_color_only", 0),
            "badges_color_only": details.get("badges_color_only", 0),
            "charts_color_only": details.get("charts_color_only", 0),
        },
        "offenders": details.get("offenders", [])[:20],
        "html_snippet": (html_sample or "")[:2500],
    }
    prompt = (
        "Actúa como auditor WCAG 1.4.1 (Uso del color). Para cada offender, propone correcciones no basadas en color: "
        "a) Enlaces → subrayado u otro indicador; "
        "b) Requeridos → '*' o '(requerido)'; "
        "c) Errores → texto de error e icono; "
        "d) Badges → texto/icono/patrón; "
        "e) Gráficos → leyenda textual y marcadores/patrones distintos. "
        "Devuelve JSON: { suggestions: [{type, reason, css_fix?, html_fix?, copy_fix?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------
# Orquestación
# -------------------------

def run_1_4_1(
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
    if details.get("na") is True:
        verdict = "na"
        passed = False
        score0 = score_from_verdict(verdict)
        score_hint = None
    else:
        hard = (
            details.get("links_color_only", 0)
            + details.get("required_color_only", 0)
            + details.get("error_color_only", 0)
            + details.get("badges_color_only", 0)
            + details.get("charts_color_only", 0)
        )
        passed = (hard == 0)
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
        title=meta.get("title", "Uso del color"),
        source=src,
        score_hint=score_hint,
        manual_required=manual_required
    )