# audits/checks/criteria/p1/c_1_2_1_time_based_alt.py
from typing import Dict, Any, List, Optional, Tuple

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "1.2.1"


def _bool_attr(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")


def _has_text_alternative(el: Dict[str, Any]) -> bool:
    label = (el.get("aria-label") or "").strip()
    labelledby = (el.get("aria-labelledby") or "").strip()
    title = (el.get("title") or "").strip()
    longdesc = (el.get("longdesc") or "").strip()
    data_transcript = (el.get("data-transcript") or "").strip()
    data_description = (el.get("data-description") or "").strip()
    nearby = bool(el.get("has_transcript") or el.get("has_nearby_transcript"))
    return any([label, labelledby, title, longdesc, data_transcript, data_description, nearby])


def _is_decorative_media(el: Dict[str, Any], tag: str) -> bool:
    role = (el.get("role") or "").lower()
    aria_hidden = _bool_attr(el.get("aria-hidden"))
    if aria_hidden or role in {"presentation", "none"}:
        return True
    if tag == "video":
        attrs = (el.get("_attrs", {}) or el)
        autoplay = "autoplay" in attrs or _bool_attr(el.get("autoplay"))
        muted    = "muted" in attrs or _bool_attr(el.get("muted"))
        loop     = "loop" in attrs or _bool_attr(el.get("loop"))
        controls = "controls" in attrs or _bool_attr(el.get("controls"))
        if autoplay and muted and loop and not controls:
            return True
    return False


def _collect_tracks_info(el: Dict[str, Any]) -> Dict[str, Any]:
    kinds = [(t.get("kind") or "").lower() for t in (el.get("tracks") or [])]
    return {
        "has_descriptions_track": ("descriptions" in kinds),
        "has_captions_track": ("captions" in kinds or "subtitles" in kinds)
    }


def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    audios: List[Dict[str, Any]] = list(getattr(ctx, "audios", []) or getattr(ctx, "audio", []) or [])
    videos: List[Dict[str, Any]] = list(getattr(ctx, "videos", []) or getattr(ctx, "video", []) or [])

    total = len(audios) + len(videos)
    with_alt = 0
    decorative = 0
    missing_alt = 0
    offenders: List[Dict[str, Any]] = []

    def _process(el: Dict[str, Any], tag: str):
        nonlocal with_alt, decorative, missing_alt, offenders
        if _is_decorative_media(el, tag):
            decorative += 1
            return
        tracks_info = _collect_tracks_info(el)
        has_alt = _has_text_alternative(el) or tracks_info["has_descriptions_track"]
        if has_alt:
            with_alt += 1
        else:
            missing_alt += 1
            offenders.append({
                "tag": tag,
                "src": (el.get("src") or el.get("data-src") or "")[:180],
                "id": el.get("id", ""),
                "class": el.get("class", []),
                "role": (el.get("role") or "").lower(),
                "aria-hidden": _bool_attr(el.get("aria-hidden")),
                "has_captions_track": tracks_info["has_captions_track"],
                "reason": "Sin alternativa textual cercana para medio pregrabado (1.2.1)."
            })

    for a in audios:
        _process(a, "audio")
    for v in videos:
        _process(v, "video")

    details: Dict[str, Any] = {
        "media_total": total,
        "audios": len(audios),
        "videos": len(videos),
        "with_alt": with_alt,
        "decorative": decorative,
        "missing_alt": missing_alt,
        # si no hay muestras, no sugerimos ratio 1.0 (confunde): lo dejamos en None
        "ok_ratio": (round(((with_alt + decorative) / total), 4) if total > 0 else None),
        "offenders": offenders,
        "note": (
            "RAW: 1.2.1 verifica que audio/video pregrabados tengan alternativa textual cercana "
            "(aria-label/labelledby/title/longdesc/data-transcript) o track 'descriptions'. "
            "Vídeos de fondo (autoplay+muted+loop sin controles) o aria-hidden/role='presentation' "
            "se consideran decorativos."
        )
    }
    # << clave para NA: si no hay medios, márcalo explícitamente
    if total == 0:
        details["na"] = True

    return details


def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    if rctx is None:
        return {
            "na": True,
            "note": "No se proveyó rendered_ctx para 1.2.1; no se pudo evaluar en modo renderizado."
        }
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note", "") + " | RENDERED: resolvible a enlaces/figcaption/aria-describedby.").strip()
    return d


def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}
    total = details.get("media_total", 0)
    missing = details.get("missing_alt", 0)
    offenders = details.get("offenders", [])
    if total == 0 or missing == 0:
        return {"ai_used": False, "manual_required": False}
    ctx_json = {
        "media_total": total,
        "missing_alt": missing,
        "sample_offenders": offenders[:5],
        "html_snippet": (html_sample or "")[:2000],
    }
    prompt = (
        "Evalúa el criterio WCAG 1.2.1 (Solo audio/solo video, pregrabado). "
        "Para cada 'offender', si es <audio>, sugiere un esquema breve de transcripción; "
        "si es <video>, sugiere una 'descripción textual equivalente' concisa. "
        "Devuelve JSON con: { suggestions: [{tag, src, suggestion_text}], "
        "manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}


def _verdict_from_121(details: Dict[str, Any]) -> Tuple[str, bool]:
    """
    Reglas para 1.2.1:
      - si 'na' explícito -> NA
      - si media_total == 0 -> NA
      - si missing_alt == 0 -> PASS
      - si missing_alt == media_total -> FAIL
      - en otro caso -> PARTIAL
    """
    if bool(details.get("na", False)):
        return "na", True

    total = int(details.get("media_total", 0) or 0)
    missing = int(details.get("missing_alt", 0) or 0)

    if total == 0:
        details["na"] = True
        return "na", True
    if missing == 0:
        return "pass", True
    if missing >= total:
        return "fail", False
    return "partial", False


def run_1_2_1(
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

    # 3) Veredicto ESTRICTO (NA si no hay medios)
    verdict, passed = _verdict_from_121(details)
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
        title=meta.get("title", "Solo audio y solo vídeo (pregrabado)"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
