# audits/checks/criteria/p1/c_1_2_5_audio_description_prerecorded.py
from typing import Dict, Any, List, Optional

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional 
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  # si no existe, el modo IA queda deshabilitado

CODE = "1.2.5"


# -------------------------
# Utilidades
# -------------------------

def _bool_attr(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")


def _has_controls(el: Dict[str, Any]) -> bool:
    return (
        "controls" in (el.get("_attrs", {}) or el)
        or _bool_attr(el.get("controls"))
        or bool(el.get("has_controls"))
    )


def _is_decorative_video(el: Dict[str, Any]) -> bool:
    """
    Decorativo si:
      - aria-hidden="true" o role in {"presentation","none"}
      - patrón típico de fondo: autoplay+muted+loop y sin controls
    """
    role = (el.get("role") or "").lower()
    aria_hidden = _bool_attr(el.get("aria-hidden"))
    if aria_hidden or role in {"presentation", "none"}:
        return True

    autoplay = "autoplay" in (el.get("_attrs", {}) or el) or _bool_attr(el.get("autoplay"))
    muted = "muted" in (el.get("_attrs", {}) or el) or _bool_attr(el.get("muted"))
    loop = "loop" in (el.get("_attrs", {}) or el) or _bool_attr(el.get("loop"))
    controls = _has_controls(el)

    if autoplay and muted and loop and not controls:
        return True
    return False


def _collect_tracks_info(el: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pistas <track>. Para 1.2.5 nos interesa especialmente 'descriptions' (audiodescripción).
    """
    tracks = el.get("tracks") or []
    kinds = []
    has_vtt_descriptions = False
    for t in tracks:
        k = (t.get("kind") or "").lower()
        kinds.append(k)
        if k == "descriptions" and str(t.get("src", "")).lower().endswith(".vtt"):
            has_vtt_descriptions = True
    return {
        "kinds": kinds,
        "has_descriptions_track": ("descriptions" in kinds),
        "has_vtt_descriptions": has_vtt_descriptions,
        "has_captions_track": ("captions" in kinds or "subtitles" in kinds),
    }


def _has_audio_track(el: Dict[str, Any]) -> Optional[bool]:
    """
    ¿El vídeo tiene audio? Si no hay señal explícita, asumimos True (caso típico).
    """
    if "has_audio_track" in el:
        return bool(el.get("has_audio_track"))
    if _bool_attr(el.get("noaudio")) or _bool_attr(el.get("data-noaudio")):
        return False
    return None  # desconocido → se tratará como True por defecto


def _is_media_alt_for_text(el: Dict[str, Any]) -> bool:
    """
    Si el vídeo es una alternativa a contenido textual y está claramente marcado.
    (Exención típica; el extractor puede marcarlo.)
    """
    return bool(el.get("is_media_alt_for_text") or _bool_attr(el.get("data-media-alt-for-text")))


def _has_ad_variant(el: Dict[str, Any]) -> bool:
    """
    Señales de que existe una versión con audiodescripción (AD):
      - data-audio-described / data-ad-src / has_ad_version
      - enlaces cercanos marcados por el extractor
    """
    return bool(
        _bool_attr(el.get("data-audio-described"))
        or (el.get("data-ad-src") or "").strip()
        or el.get("has_ad_version")
        or el.get("has_nearby_ad_link")
    )


def _has_audio_description(el: Dict[str, Any], tracks_info: Dict[str, Any]) -> bool:
    """
    Cumplimiento estricto de 1.2.5: debe haber audiodescripción.
      - <track kind="descriptions"> (preferible, incluso mejor si .vtt)
      - o versión alternativa con AD (flag/URL)
    *OJO*: Subtítulos ('captions') NO cumplen 1.2.5.
    """
    return bool(tracks_info["has_descriptions_track"] or tracks_info["has_vtt_descriptions"] or _has_ad_variant(el))


# -------------------------
# Núcleo del criterio
# -------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    videos: List[Dict[str, Any]] = list(getattr(ctx, "videos", []) or getattr(ctx, "video", []) or [])
    total = len(videos)

    with_ad = 0
    missing_ad = 0
    decorative = 0
    without_audio = 0
    exempt_media_alt_for_text = 0
    requiring_ad = 0

    offenders: List[Dict[str, Any]] = []

    for v in videos:
        if _is_decorative_video(v):
            decorative += 1
            continue

        # ¿Tiene audio? (1.2.5 solo aplica a video con audio pregrabado)
        has_audio = _has_audio_track(v)
        if has_audio is None:
            has_audio = True
        if not has_audio:
            without_audio += 1
            continue

        # Exento si es media-alt-for-text explícito
        if _is_media_alt_for_text(v):
            exempt_media_alt_for_text += 1
            continue

        requiring_ad += 1

        tracks_info = _collect_tracks_info(v)
        if _has_audio_description(v, tracks_info):
            with_ad += 1
        else:
            missing_ad += 1
            offenders.append({
                "tag": "video",
                "src": (v.get("src") or v.get("data-src") or "")[:180],
                "id": v.get("id", ""),
                "class": v.get("class", []),
                "role": (v.get("role") or "").lower(),
                "aria-hidden": _bool_attr(v.get("aria-hidden")),
                "has_controls": _has_controls(v),
                "tracks_kinds": tracks_info["kinds"],
                "has_captions_track": tracks_info["has_captions_track"],  # útil para depurar confusiones con 1.2.2
                "has_ad_variant": _has_ad_variant(v),
                "reason": "Vídeo pregrabado con audio sin audiodescripción (1.2.5)."
            })

    ok_ratio = 1.0 if total == 0 else round(
        (with_ad + decorative + without_audio + exempt_media_alt_for_text) / total, 4
    )

    details: Dict[str, Any] = {
        "videos_total": total,
        "requiring_ad": requiring_ad,
        "with_ad": with_ad,
        "missing_ad": missing_ad,
        "without_audio": without_audio,
        "decorative": decorative,
        "exempt_media_alt_for_text": exempt_media_alt_for_text,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 1.2.5 exige audiodescripción para todo vídeo pregrabado con audio en medios sincronizados. "
            "Se acepta <track kind='descriptions'> o una versión alternativa con AD. "
            "Vídeos decorativos o sin audio no requieren. Subtítulos ('captions') no sustituyen la AD."
        )
    }
    return details


def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En DOM post-render, puedes:
      - Detectar botón/alternador de 'Audiodescripción' en el reproductor (role=button, aria-label~='Audio descripción')
      - Identificar enlaces cercanos 'Versión con audiodescripción'
      - Confirmar 'has_audio_track' vía Web APIs (si tu extractor lo habilita)
    """
    if rctx is None:
        return {
            "na": True,
            "note": "No se proveyó rendered_ctx para 1.2.5; no se pudo evaluar en modo renderizado."
        }
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note", "") + " | RENDERED: resolvible a botón AD visible/activo y enlaces a versión AD.").strip()
    return d


# -------------------------
# Modo IA (opcional)
# -------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    Si faltan AD, pedimos a la IA:
      - Un guion breve de audiodescripción (3–5 escenas con tiempos aproximados)
      - Un stub WebVTT de 'descriptions' con 2–3 cues
      - Checklist de producción (grabación/mezcla) para implementar AD
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    total = details.get("videos_total", 0)
    missing = details.get("missing_ad", 0)
    offenders = details.get("offenders", [])
    if total == 0 or missing == 0:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "videos_total": total,
        "requiring_ad": details.get("requiring_ad", 0),
        "missing_ad": missing,
        "sample_offenders": offenders[:5],
        "html_snippet": (html_sample or "")[:2000],
    }
    prompt = (
        "Evalúa el criterio WCAG 1.2.5 (Audiodescripción — pregrabado). "
        "Para cada 'offender', sugiere: "
        "1) Un guion de audiodescripción (3–5 escenas con tiempos aproximados y texto breve); "
        "2) Un stub WebVTT de 'descriptions' con 2–3 cues; "
        "3) Un checklist mínimo para producción (grabación/mezcla/publicación). "
        "Devuelve JSON: { suggestions: [{src, ad_script_outline, vtt_descriptions_stub, production_checklist}], "
        "manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

def _verdict_from_125(d: Dict[str, Any]) -> tuple[str, bool]:
    """
    Reglas duras 1.2.5 (Audiodescripción — pregrabado):
      - si NO hay vídeos (videos_total == 0) -> NA
      - si hay vídeos pero NINGUNO requiere AD (requiring_ad == 0) -> NA
      - si requiere y no falta ninguno -> PASS
      - si faltan todos -> FAIL
      - si faltan algunos -> PARTIAL
    """
    total = int(d.get("videos_total") or 0)
    req   = int(d.get("requiring_ad") or 0)
    miss  = int(d.get("missing_ad") or 0)

    if total == 0 or req == 0:
        d["na"] = True
        return "na", True
    if miss == 0:
        return "pass", True
    if miss >= req:
        return "fail", False
    return "partial", False

# -------------------------
# Orquestación
# -------------------------

def run_1_2_5(
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
    requiring = details.get("requiring_ad", 0)
    missing = details.get("missing_ad", 0)
    passed = (requiring == 0) or (missing == 0)

    verdict, passed = _verdict_from_125(details)
    score0 = score_from_verdict(verdict)

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE,
        passed=passed,
        verdict=verdict,
        score_0_2=score0,
        details=details,
        level=meta.get("level", "AA"),
        principle=meta.get("principle", "Perceptible"),
        title=meta.get("title", "Audiodescripción (pregrabado)"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
