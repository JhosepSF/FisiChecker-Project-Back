# audits/checks/criteria/p1/c_1_4_2_audio_control.py
from typing import Dict, Any, List, Optional
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional 
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  # si no existe, el modo IA queda deshabilitado

CODE = "1.4.2"

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
    # acepta bools, "true"/"1"/"yes"
    return str(v).lower() in ("true", "1", "yes")

def _get_attr(el: Any, name: str) -> Optional[str]:
    """
    Acceso tolerante a atributos tanto si 'el' es Tag (BeautifulSoup) como si es dict (extractor avanzado).
    Para boolean attributes de HTML, BeautifulSoup guarda la key con valor True o ''.
    """
    if el is None:
        return None
    # dict
    if isinstance(el, dict):
        v = el.get(name)
        return (str(v) if v is not None else None)
    # BeautifulSoup Tag
    try:
        if hasattr(el, "get"):
            v = el.get(name)  # type: ignore[attr-defined]
            if v is None:
                return None
            # Atributos booleanos pueden venir como True o lista
            if isinstance(v, (list, tuple, set)):
                return " ".join(str(x) for x in v if x is not None)
            return str(v)
    except Exception:
        return None
    return None

def _has_attr_presence(el: Any, name: str) -> bool:
    """
    Para boolean attributes: consideramos verdadero si está presente aunque sea vacío.
    Además admite flags del extractor: has_{name}, is_{name}.
    """
    if el is None:
        return False
    # flags de extractor
    for k in (name, f"has_{name}", f"is_{name}"):
        if isinstance(el, dict) and el.get(k) is True:
            return True
    # Tag
    try:
        if hasattr(el, "attrs") and name in getattr(el, "attrs", {}):  # type: ignore[attr-defined]
            return True
    except Exception:
        pass
    # valor textual true-like
    v = _get_attr(el, name)
    return _bool(v) if v is not None else False

def _number_attr(el: Any, *names: str) -> Optional[float]:
    """Lee atributos numéricos como 'duration' o 'data-duration'."""
    for n in names:
        v = _get_attr(el, n)
        if v is None or str(v).strip() == "":
            continue
        try:
            return float(str(v).strip())
        except Exception:
            continue
    return None

def _src_url(el: Any) -> str:
    for k in ("src", "data-src", "data-url"):
        v = _get_attr(el, k)
        if v:
            return v.strip()
    return ""

def _is_iframe_autoplay(el: Any) -> bool:
    """
    Detecta <iframe> con autoplay (YouTube/Vimeo/SoundCloud típicos):
      - src ?autoplay=1
      - allow incluye 'autoplay'
    Consideramos 'muted=1' como mitigación.
    """
    tag = (getattr(el, "name", "") or "").lower()
    if isinstance(el, dict):
        tag = (el.get("tag") or "").lower()
    if tag != "iframe":
        return False
    src = (_src_url(el) or "").lower()
    allow = (_get_attr(el, "allow") or "").lower()
    if "autoplay=1" in src or "autoplay" in allow:
        # ¿muted?
        if ("mute=1" in src) or ("muted=1" in src) or ("&sound=0" in src):
            return False
        return True
    return False

def _has_user_controls(el: Any) -> bool:
    """
    Se acepta cualquiera de:
      - atributo 'controls'
      - botón accesible de pausa/detener (flag del extractor)
      - control de volumen/mute (flags del extractor)
    """
    if _has_attr_presence(el, "controls"):
        return True
    # flags del extractor o data-*
    flags = (
        "has_controls", "has_pause_button", "has_stop_button", "has_mute_button",
        "has_volume_control", "data-has-controls", "data-has-pause", "data-has-mute", "data-has-volume"
    )
    for f in flags:
        if _has_attr_presence(el, f):
            return True
    return False

def _is_autoplaying_with_sound(el: Any) -> bool:
    """
    Consideramos violación base cuando:
      - autoplay presente
      - NO muted
      - (para video) asumimos que tiene audio salvo 'muted' o flag has_audio_track=False
    """
    autoplay = _has_attr_presence(el, "autoplay")
    if not autoplay:
        return False
    # si está muted → no aplica 1.4.2
    if _has_attr_presence(el, "muted"):
        return False
    # extractor puede poner 'has_audio_track'
    hat = _get_attr(el, "has_audio_track")
    if hat is not None and str(hat).strip().lower() in ("false", "0", "no"):
        return False
    return True

def _is_short_audio(el: Any) -> bool:
    """
    Si la duración conocida <= 3s, no aplica 1.4.2.
    Acepta 'duration', 'data-duration' o 'audio_duration'.
    """
    dur = _number_attr(el, "duration", "data-duration", "audio_duration")
    return (dur is not None) and (dur <= 3.0)

# -------------------------
# Núcleo del criterio
# -------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW: marcamos audio que se reproduce automáticamente (>3s) sin mecanismo de PAUSA/STOP o control de VOLUMEN.
      - <audio> autoplay sin muted
      - <video> autoplay sin muted (asumimos que tiene audio)
      - <iframe> (p.ej., YouTube) con autoplay no muteado
    Señalamos cumplimiento cuando hay 'controls' o flags equivalentes.
    """
    soup = getattr(ctx, "soup", None)
    audios = _as_list(getattr(ctx, "audios", []))
    videos = _as_list(getattr(ctx, "videos", []))

    # (Opcional) recolectar iframes del soup si existe
    iframes = []
    try:
        if soup is not None and hasattr(soup, "find_all"):
            iframes = list(soup.find_all("iframe"))  # type: ignore[attr-defined]
    except Exception:
        iframes = []

    media_total = 0
    autoplay_with_sound = 0
    compliant_with_controls = 0
    assumed_short = 0
    violations = 0

    offenders: List[Dict[str, Any]] = []

    # --- <audio>
    for el in audios:
        media_total += 1
        if _is_autoplaying_with_sound(el):
            if _is_short_audio(el):
                assumed_short += 1
                continue
            autoplay_with_sound += 1
            if _has_user_controls(el):
                compliant_with_controls += 1
            else:
                violations += 1
                offenders.append({
                    "type": "audio",
                    "src": _src_url(el)[:180],
                    "has_controls": _has_user_controls(el),
                    "autoplay": True,
                    "muted": False,
                    "reason": "Audio autoplay (>3s probable) sin pausa/stop/volumen."
                })

    # --- <video> (con audio presumible)
    for el in videos:
        media_total += 1
        if _is_autoplaying_with_sound(el):
            if _is_short_audio(el):
                assumed_short += 1
                continue
            autoplay_with_sound += 1
            if _has_user_controls(el):
                compliant_with_controls += 1
            else:
                violations += 1
                offenders.append({
                    "type": "video",
                    "src": _src_url(el)[:180],
                    "has_controls": _has_user_controls(el),
                    "autoplay": True,
                    "muted": False,
                    "reason": "Video autoplay con audio (>3s probable) sin pausa/stop/volumen."
                })

    # --- <iframe> (YouTube/Vimeo/SoundCloud)
    for el in iframes:
        media_total += 1
        if _is_iframe_autoplay(el):
            autoplay_with_sound += 1
            # Desconocemos controles reales → si 'controls=0' en URL, lo marcamos fuerte
            src = (_src_url(el) or "").lower()
            controls_param = ("controls=0" in src) or ("controls=false" in src)
            if controls_param:
                violations += 1
                offenders.append({
                    "type": "iframe",
                    "src": _src_url(el)[:180],
                    "autoplay": True,
                    "muted": False,
                    "reason": "Iframe con autoplay y controles ocultos ('controls=0')."
                })
            else:
                # Sin certeza → requerimos revisión
                offenders.append({
                    "type": "iframe",
                    "src": _src_url(el)[:180],
                    "autoplay": True,
                    "muted": False,
                    "reason": "Iframe con autoplay; revisar que haya pausa/stop/volumen."
                })

    denom = max(1, autoplay_with_sound)
    ok_ratio = round(max(0.0, min(1.0, (compliant_with_controls + assumed_short) / denom)), 4)

    if autoplay_with_sound == 0:
        ok_ratio = 1.0
    else:
        denom = autoplay_with_sound
        ok_ratio = round(max(0.0, min(1.0, (compliant_with_controls + assumed_short) / max(1, denom))), 4)

    details: Dict[str, Any] = {
        "media_total": media_total,
        "autoplay_with_sound": autoplay_with_sound,
        "compliant_with_controls": compliant_with_controls,
        "assumed_short_leq_3s": assumed_short,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 1.4.2 exige un mecanismo para PAUSAR/DETENER o controlar VOLUMEN cuando se reproduce audio automáticamente (>3s). "
            "Se marcan <audio>/<video> con autoplay y sin muted; en iframes se detecta 'autoplay=1' y 'controls=0'. "
            "Si la duración conocida ≤3s, no aplica. En embeds se sugiere revisión cuando no podemos inferir controles."
        )
    }

    # ✅ N/A si no hay audio auto-reproducido con sonido
    if autoplay_with_sound == 0:
        details["na"] = True

    return details

# -------------------------
# Rendered
# -------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED (Playwright) puedes exponer:
      rctx.media_states = [
        {id, type:'audio'|'video', is_playing:bool, muted:bool, volume:float, duration:float|None,
         has_controls:bool, has_pause_button:bool, has_volume_control:bool}
      ]
    Con esto confirmamos reproducción real y duración.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.4.2; no se pudo evaluar en modo renderizado."}

    base = _compute_counts_raw(rctx)  # conserva offenders y métricas básicas
    base["rendered"] = True

    media_states = _as_list(getattr(rctx, "media_states", []))
    if not media_states:
        base["note"] = (base.get("note","") + " | RENDERED: no se expusieron 'media_states'.").strip()
        return base

    violations = base.get("violations", 0)
    compliant = base.get("compliant_with_controls", 0)
    assumed_short = base.get("assumed_short_leq_3s", 0)
    autoplay_with_sound = base.get("autoplay_with_sound", 0)

    # Ajustes con datos reales
    for ms in media_states:
        if not ms.get("is_playing"):
            continue
        if ms.get("muted"):
            continue
        dur = ms.get("duration")
        if isinstance(dur, (int, float)) and dur <= 3:
            # Si lo habíamos contado como riesgo, lo descontamos
            if autoplay_with_sound > 0:
                autoplay_with_sound -= 1
            assumed_short += 1
            continue
        has_ctrl = any([
            ms.get("has_controls"),
            ms.get("has_pause_button"),
            ms.get("has_volume_control"),
        ])
        if has_ctrl:
            compliant += 1
        else:
            violations += 1

    denom = max(1, autoplay_with_sound)
    base["autoplay_with_sound"] = autoplay_with_sound
    base["compliant_with_controls"] = compliant
    base["assumed_short_leq_3s"] = assumed_short
    base["violations"] = violations
    base["ok_ratio"] = round(max(0.0, min(1.0, (compliant + assumed_short) / denom)), 4)
    base["note"] = (base.get("note","") + " | RENDERED: se usó 'media_states' para confirmar reproducción y duración.").strip()
    
    if base.get("autoplay_with_sound", 0) == 0:
        base["ok_ratio"] = 1.0
    else:
        denom = base["autoplay_with_sound"]
        base["ok_ratio"] = round(max(0.0, min(1.0, (base.get("compliant_with_controls", 0) + base.get("assumed_short_leq_3s", 0)) / max(1, denom))), 4)
    
    return base

# -------------------------
# IA opcional
# -------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: propone fixes cuando hay violaciones:
      - Añadir 'controls' o botones de pausa/stop + control de volumen
      - Quitar 'autoplay' o iniciar reproducción solo tras interacción
      - Para video en portada: 'muted' + 'playsinline' si debe auto-reproducir sin audio
      - En iframes (YouTube): quitar 'autoplay=1' o asegurar controles visibles
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    if (details.get("violations", 0) or 0) == 0 and not details.get("offenders"):
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "autoplay_with_sound": details.get("autoplay_with_sound", 0),
            "violations": details.get("violations", 0),
        },
        "offenders": details.get("offenders", [])[:15],
        "html_snippet": (html_sample or "")[:2500],
    }
    prompt = (
        "Actúa como auditor WCAG 1.4.2 (Audio control). "
        "Para cada offender, sugiere cambios concretos: "
        "- <audio>/<video>: añadir atributo 'controls' o botones de pausa y control de volumen; "
        "- Quitar 'autoplay' o retrasar reproducción hasta interacción del usuario; "
        "- Si el hero video debe auto-reproducirse, añadir 'muted playsinline' y sin audio por defecto; "
        "- Iframes de YouTube/Vimeo: remover 'autoplay=1' o asegurar controles visibles. "
        "Devuelve JSON: { suggestions: [{type, reason, fix_html?, fix_js?, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------
# Orquestación
# -------------------------

def run_1_4_2(
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
        passed = False
        score0 = score_from_verdict(verdict)
        score_hint = None
    else:
        violations = details.get("violations", 0) or 0
        passed = (violations == 0)
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
        title=meta.get("title", "Control de audio"),
        source=src,
        score_hint=score_hint,
        manual_required=manual_required
    )