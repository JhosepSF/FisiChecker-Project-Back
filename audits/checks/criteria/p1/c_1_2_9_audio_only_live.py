# audits/checks/criteria/p1/c_1_2_9_audio_only_live.py
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "1.2.9"  # AAA


# -------- utilidades --------

def _bool_attr(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")


def _url_info(src: str) -> Tuple[str, Dict[str, List[str]]]:
    try:
        u = urlparse(src)
        return u.netloc.lower(), parse_qs(u.query)
    except Exception:
        return "", {}


def _is_live_media(el: Dict[str, Any]) -> bool:
    if _bool_attr(el.get("is_live")) or _bool_attr(el.get("data-live")) or _bool_attr(el.get("live")):
        return True
    src = str(el.get("src") or el.get("data-src") or el.get("href") or "")
    host, _ = _url_info(src)
    if any(ext in src.lower() for ext in (".m3u8", ".mpd")):
        return True
    # pistas por plataforma (genérico)
    if any(h in host for h in ("twitch.tv", "youtube.com", "youtu.be", "facebook.com", "radio", "tunein", "shoutcast")):
        return "live" in src.lower() or "stream" in src.lower()
    return False


def _has_live_text_alt(el: Dict[str, Any]) -> bool:
    """
    Señales de alternativa para audio EN DIRECTO:
      - has_live_transcript / has_nearby_live_transcript
      - data-live-transcript / data-rtc / aria-live region asociada
      - 'cc' no aplica estrictamente a audio-only, pero aceptamos 'has_live_captions' como indicio fuerte
    """
    return bool(
        el.get("has_live_transcript")
        or el.get("has_nearby_live_transcript")
        or _bool_attr(el.get("data-live-transcript"))
        or el.get("has_live_captions")
        or el.get("has_nearby_captions_region")
    )


# -------- núcleo --------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    audios: List[Dict[str, Any]] = list(getattr(ctx, "audios", []) or getattr(ctx, "audio", []) or [])
    total = len(audios)

    live_audio = []
    for a in audios:
        if _is_live_media(a):
            live_audio.append(a)

    total_live_audio = len(live_audio)

    with_alt = 0
    missing_alt = 0
    decorative = 0  # poco común en audio, pero mantenemos campo
    offenders: List[Dict[str, Any]] = []

    for a in live_audio:
        role = (a.get("role") or "").lower()
        if _bool_attr(a.get("aria-hidden")) or role in {"presentation", "none"}:
            decorative += 1
            continue

        if _has_live_text_alt(a):
            with_alt += 1
        else:
            missing_alt += 1
            offenders.append({
                "tag": "audio",
                "src": (a.get("src") or a.get("data-src") or a.get("href") or "")[:220],
                "id": a.get("id", ""),
                "class": a.get("class", []),
                "reason": "Audio en directo sin alternativa textual en vivo (1.2.9)."
            })

    ok_ratio = 1.0 if total_live_audio == 0 else round((with_alt + decorative) / total_live_audio, 4)

    return {
        "audios_total": total,
        "live_audio_total": total_live_audio,
        "with_live_text_alt": with_alt,
        "missing_live_text_alt": missing_alt,
        "decorative": decorative,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 1.2.9 exige alternativa textual para audio EN DIRECTO (p.ej., transcripción en tiempo real). "
            "Se aceptan señales: has_live_transcript / data-live-transcript / regiones cercanas en vivo."
        )
    }


def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.2.9; no se pudo evaluar en modo renderizado."}
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note", "") + " | RENDERED: detecta zonas aria-live/log con texto en tiempo real junto al player.").strip()
    return d


def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False}
    total = details.get("live_audio_total", 0)
    missing = details.get("missing_live_text_alt", 0)
    offenders = details.get("offenders", [])
    if total == 0 or missing == 0:
        return {"ai_used": False, "manual_required": False}
    ctx_json = {
        "live_audio_total": total,
        "missing_live_text_alt": missing,
        "sample_offenders": offenders[:5],
        "html_snippet": (html_sample or "")[:2000],
    }
    prompt = (
        "Para 1.2.9 (Audio en directo — alternativa textual), propone un plan de transcripción en vivo: "
        "CART/ASR, aviso de latencia y enlace visible al panel de texto. "
        "JSON { suggestions:[{src, live_transcription_plan}], manual_review?:bool }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}


def _verdict_from_129(d: Dict[str, Any]) -> Tuple[str, bool]:
    """
    1.2.9 (AAA) — Solo audio (en directo) — alternativa
      - N/A si no hay audio en directo (live_audio_total==0)
      - PASS si no faltan alternativas
      - FAIL si faltan todas
      - PARTIAL en caso mixto
    """
    req  = int(d.get("live_audio_total") or 0)          # lo que requiere alternativa
    miss = int(d.get("missing_live_text_alt") or 0)

    if req == 0:
        d["na"] = True
        return "na", True
    if miss == 0:
        return "pass", True
    if miss >= req:
        return "fail", False
    return "partial", False

def run_1_2_9(
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

    # ⬇️ Veredicto ESTRICTO (N/A cuando no hay audio en directo)
    verdict, passed = _verdict_from_129(details)
    score0 = score_from_verdict(verdict)

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0,
        details=details, level=meta.get("level", "AAA"),
        principle=meta.get("principle", "Perceptible"),
        title=meta.get("title", "Solo audio (en directo) — alternativa"),
        source=src, score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
