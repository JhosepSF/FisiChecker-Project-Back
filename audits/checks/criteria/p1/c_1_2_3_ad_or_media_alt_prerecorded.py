# audits/checks/criteria/p1/c_1_2_3_ad_or_media_alt_prerecorded.py
from typing import Dict, Any, List, Optional

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional 
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  # si no existe, el modo IA queda deshabilitado

CODE = "1.2.3"


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
    Consideramos decorativo si:
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

    # Vídeo de fondo silencioso, no interactivo
    if autoplay and muted and loop and not controls:
        return True
    return False


def _collect_tracks_info(el: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extrae info de <track>. Para 1.2.3 nos interesa especialmente 'descriptions'.
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
    ¿El vídeo tiene audio? Si no hay señal, asumimos True (caso típico).
    """
    if "has_audio_track" in el:
        return bool(el.get("has_audio_track"))
    if _bool_attr(el.get("noaudio")) or _bool_attr(el.get("data-noaudio")):
        return False
    return None  # desconocido → tratamos como True por defecto


def _has_media_alternative(el: Dict[str, Any]) -> bool:
    """
    Señales de 'alternativa para medios temporales' (texto que describe escena a escena):
      - data-transcript / data-media-alt
      - flags del extractor: has_transcript / has_media_alt / has_nearby_transcript
      - longdesc (legacy) o referencia explícita
    NOTA: 'captions' NO es suficiente para 1.2.3 (eso cubre 1.2.2).
    """
    data_transcript = (el.get("data-transcript") or "").strip()
    data_media_alt = (el.get("data-media-alt") or "").strip()
    longdesc = (el.get("longdesc") or "").strip()
    flags = bool(
        el.get("has_transcript")
        or el.get("has_media_alt")
        or el.get("has_nearby_transcript")
    )
    return any([data_transcript, data_media_alt, longdesc, flags])


def _is_media_alt_for_text(el: Dict[str, Any]) -> bool:
    """
    Excepción de 1.2.3: cuando el medio es una alternativa a texto y está claramente etiquetado.
    Permite que el extractor marque el caso.
    """
    return bool(el.get("is_media_alt_for_text") or _bool_attr(el.get("data-media-alt-for-text")))


def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    videos: List[Dict[str, Any]] = list(getattr(ctx, "videos", []) or getattr(ctx, "video", []) or [])
    total = len(videos)

    with_ad_or_alt = 0
    missing_ad_or_alt = 0
    decorative = 0
    without_audio = 0
    exempt_media_alt_for_text = 0
    requiring_ad_or_alt = 0

    offenders: List[Dict[str, Any]] = []

    for v in videos:
        if _is_decorative_video(v):
            decorative += 1
            continue

        # ¿Tiene audio? (1.2.3 aplica a medios sincronizados con audio)
        has_audio = _has_audio_track(v)
        if has_audio is None:
            has_audio = True
        if not has_audio:
            without_audio += 1
            continue

        # ¿Está explícitamente marcado como "media alt for text"? (excepción)
        if _is_media_alt_for_text(v):
            exempt_media_alt_for_text += 1
            continue

        requiring_ad_or_alt += 1

        tracks_info = _collect_tracks_info(v)
        has_descriptions = bool(tracks_info["has_descriptions_track"])
        has_media_alt = _has_media_alternative(v)

        if has_descriptions or has_media_alt:
            with_ad_or_alt += 1
        else:
            missing_ad_or_alt += 1
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
                "reason": "Vídeo pregrabado con audio sin audiodescripción ni alternativa textual (1.2.3)."
            })

    ok_ratio = 1.0 if total == 0 else round(
        (with_ad_or_alt + decorative + without_audio + exempt_media_alt_for_text) / total, 4
    )

    details: Dict[str, Any] = {
        "videos_total": total,
        "requiring_ad_or_alt": requiring_ad_or_alt,
        "with_ad_or_alt": with_ad_or_alt,
        "missing_ad_or_alt": missing_ad_or_alt,
        "without_audio": without_audio,
        "decorative": decorative,
        "exempt_media_alt_for_text": exempt_media_alt_for_text,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 1.2.3 exige audiodescripción (track 'descriptions') O una alternativa textual para medios "
            "(transcripción escena a escena) en vídeos pregrabados con audio. "
            "Vídeos decorativos o sin audio no requieren; si el vídeo es una alternativa al texto y está "
            "claramente etiquetado, queda exento. 'Captions' solos NO cumplen 1.2.3."
        )
    }
    return details


def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    Con DOM post-render (Playwright) podrías:
      - Resolver aria-labelledby/aria-describedby a nodos de transcript/descripcion
      - Detectar enlaces cercanos 'Transcripción', 'Descripción del vídeo', 'Audio descripción'
      - Inferir presence de 'descriptions' vía UI del player o Web APIs
    """
    if rctx is None:
        return {
            "na": True,
            "note": "No se proveyó rendered_ctx para 1.2.3; no se pudo evaluar en modo renderizado."
        }
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note", "") + " | RENDERED: resolvible a enlaces cercanos y toggles de AD del reproductor.").strip()
    return d


def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    Si faltan AD o alternativa textual, pedimos a la IA:
      - Un esquema de 'alternativa para medios temporales' (lista de escenas con tiempos)
      - (Opcional) un stub WebVTT de 'descriptions' con 2–3 cues
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    total = details.get("videos_total", 0)
    missing = details.get("missing_ad_or_alt", 0)
    offenders = details.get("offenders", [])
    if total == 0 or missing == 0:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "videos_total": total,
        "requiring_ad_or_alt": details.get("requiring_ad_or_alt", 0),
        "missing_ad_or_alt": missing,
        "sample_offenders": offenders[:5],
        "html_snippet": (html_sample or "")[:2000],
    }
    prompt = (
        "Evalúa el criterio WCAG 1.2.3 (Audiodescripción o alternativa para medios — pregrabado). "
        "Para cada 'offender', sugiere: "
        "1) Un esquema breve de 'alternativa para medios temporales' (escenas con tiempos y descripciones); y "
        "2) Un stub WebVTT de audiodescripción con 2–3 cues. "
        "Devuelve JSON: { suggestions: [{src, media_alt_outline, vtt_descriptions_stub}], "
        "manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}


def run_1_2_3(
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

    # 2) Si modo IA, añade sugerencias
    manual_required = False
    if mode == CheckMode.AI:
        ai_info = _ai_review(details, html_sample=html_for_ai)
        details["ai_info"] = ai_info
        src = "ai"
        manual_required = ai_info.get("manual_review", False)

    # 3) passed / verdict / score
    requiring = details.get("requiring_ad_or_alt", 0)
    missing = details.get("missing_ad_or_alt", 0)
    passed = (requiring == 0) or (missing == 0)

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
        principle=meta.get("principle", "Perceptible"),
        title=meta.get("title", "Audiodescripción o alternativa para medios (pregrabado)"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
