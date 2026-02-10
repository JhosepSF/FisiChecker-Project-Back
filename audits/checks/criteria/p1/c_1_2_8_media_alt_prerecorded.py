# audits/checks/criteria/p1/c_1_2_8_media_alt_prerecorded.py
from typing import Dict, Any, List, Optional, Tuple

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "1.2.8"  # AAA


def _bool_attr(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")


def _is_decorative_video(el: Dict[str, Any]) -> bool:
    role = (el.get("role") or "").lower()
    aria_hidden = _bool_attr(el.get("aria-hidden"))
    if aria_hidden or role in {"presentation", "none"}:
        return True
    return False


def _is_live_media(el: Dict[str, Any]) -> bool:
    return _bool_attr(el.get("is_live")) or _bool_attr(el.get("data-live")) or _bool_attr(el.get("live"))


def _has_audio_track(el: Dict[str, Any]) -> Optional[bool]:
    if "has_audio_track" in el:
        return bool(el.get("has_audio_track"))
    if _bool_attr(el.get("noaudio")) or _bool_attr(el.get("data-noaudio")):
        return False
    return None


def _has_media_alternative(el: Dict[str, Any]) -> bool:
    """
    Alternativa para medios temporales (texto con toda la info de audio+video o de video-only):
      - data-transcript / data-media-alt / longdesc
      - flags: has_media_alt / has_transcript / has_nearby_transcript / has_nearby_media_alt
      - enlace cercano identificado por el extractor
    """
    return bool(
        (el.get("data-media-alt") or "").strip()
        or (el.get("data-transcript") or "").strip()
        or (el.get("longdesc") or "").strip()
        or el.get("has_media_alt")
        or el.get("has_transcript")
        or el.get("has_nearby_transcript")
        or el.get("has_nearby_media_alt")
    )


def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    videos: List[Dict[str, Any]] = list(getattr(ctx, "videos", []) or getattr(ctx, "video", []) or [])
    total = len(videos)

    requiring_alt = 0
    with_alt = 0
    missing_alt = 0
    decorative = 0
    live_exempt = 0

    offenders: List[Dict[str, Any]] = []

    for v in videos:
        if _is_decorative_video(v):
            decorative += 1
            continue

        if _is_live_media(v):
            live_exempt += 1  # 1.2.8 aplica a pregrabado
            continue

        # 1.2.8 aplica a sincronizados (con audio) y a video-only, ambos pregrabados
        has_audio = _has_audio_track(v)
        if has_audio is None:
            has_audio = True  # asumimos con audio si no sabemos
        # tanto si hay audio como si es video-only: requiere alternativa textual
        requiring_alt += 1

        if _has_media_alternative(v):
            with_alt += 1
        else:
            missing_alt += 1
            offenders.append({
                "tag": "video",
                "src": (v.get("src") or v.get("data-src") or "")[:200],
                "id": v.get("id", ""),
                "class": v.get("class", []),
                "has_audio_track": has_audio,
                "reason": "Pregrabado sin alternativa para medios temporales (1.2.8)."
            })

    ok_ratio = 1.0 if total == 0 else round(
        (with_alt + decorative + live_exempt) / total, 4
    )

    return {
        "videos_total": total,
        "requiring_alt": requiring_alt,
        "with_alt": with_alt,
        "missing_alt": missing_alt,
        "decorative": decorative,
        "live_exempt": live_exempt,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 1.2.8 exige alternativa textual completa para medios temporales pregrabados "
            "(vídeo sincronizado con audio o vídeo-solo)."
        )
    }


def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.2.8; no se pudo evaluar en modo renderizado."}
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note", "") + " | RENDERED: resolvible con detección de enlaces/zonas de 'Transcripción' o 'Alternativa'.").strip()
    return d


def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False}
    total = details.get("videos_total", 0)
    missing = details.get("missing_alt", 0)
    offenders = details.get("offenders", [])
    if total == 0 or missing == 0:
        return {"ai_used": False, "manual_required": False}
    ctx_json = {
        "videos_total": total,
        "requiring_alt": details.get("requiring_alt", 0),
        "missing_alt": missing,
        "sample_offenders": offenders[:5],
        "html_snippet": (html_sample or "")[:2000],
    }
    prompt = (
        "Para 1.2.8 (Alternativa para medios — pregrabado), genera un bosquejo de alternativa textual: "
        "secciones con tiempos, acciones visuales y diálogos clave. "
        "JSON { suggestions:[{src, media_alt_outline}], manual_review?:bool }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}


def _verdict_from_128(d: Dict[str, Any]) -> Tuple[str, bool]:
    """
    1.2.8 (AAA) — Alternativa para medios (pregrabado)
      - N/A si no hay videos (videos_total==0) o si nadie requiere alternativa (requiring_alt==0)
      - PASS si no faltan alternativas
      - FAIL si faltan todas
      - PARTIAL en caso mixto
    """
    total = int(d.get("videos_total") or 0)
    req   = int(d.get("requiring_alt") or 0)
    miss  = int(d.get("missing_alt") or 0)

    if total == 0 or req == 0:
        d["na"] = True
        return "na", True
    if miss == 0:
        return "pass", True
    if miss >= req:
        return "fail", False
    return "partial", False

def run_1_2_8(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None
) -> CriterionOutcome:
    if mode == CheckMode.RENDERED:
        if rendered_ctx is None:
            details = _compute_counts_raw(ctx); src = "raw"; details["warning"] = "Se pidió RENDERED sin rendered_ctx; fallback a RAW."
        else:
            details = _compute_counts_rendered(rendered_ctx); src = "rendered"
    else:
        details = _compute_counts_raw(ctx); src = "raw"

    manual_required = False
    if mode == CheckMode.AI:
        ai_info = _ai_review(details, html_sample=html_for_ai)
        details["ai_info"] = ai_info; src = "ai"
        manual_required = bool(ai_info.get("manual_required", False))

    # ⬇️ Veredicto ESTRICTO (evita PASS cuando en realidad no aplica)
    verdict, passed = _verdict_from_128(details)
    score0 = score_from_verdict(verdict)

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0,
        details=details, level=meta.get("level", "AAA"),
        principle=meta.get("principle", "Perceptible"),
        title=meta.get("title", "Alternativa para medios (pregrabado)"),
        source=src, score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )