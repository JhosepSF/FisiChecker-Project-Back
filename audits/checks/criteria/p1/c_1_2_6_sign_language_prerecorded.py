# audits/checks/criteria/p1/c_1_2_6_sign_language_prerecorded.py
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "1.2.6"  # AAA


# -------- utilidades compartidas --------

def _bool_attr(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")


def _has_controls(el: Dict[str, Any]) -> bool:
    return (
        "controls" in (el.get("_attrs", {}) or el)
        or _bool_attr(el.get("controls"))
        or bool(el.get("has_controls"))
    )


def _is_decorative_video(el: Dict[str, Any]) -> bool:
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
    tracks = el.get("tracks") or []
    kinds = []
    labels = []
    for t in tracks:
        kinds.append((t.get("kind") or "").lower())
        labels.append((t.get("label") or "").lower())
    has_signish = any(k in {"sign", "signlanguage"} for k in kinds) or any(
        any(w in lbl for w in ("sign", "señas", "lsp", "asl", "bsl", "lsek", "lsc", "lpi"))
        for lbl in labels
    )
    return {
        "kinds": kinds,
        "labels": labels,
        "has_sign_track": has_signish,
    }


def _url_info(src: str):
    try:
        u = urlparse(src)
        return u.netloc.lower(), parse_qs(u.query)
    except Exception:
        return "", {}


def _detect_platform_live(src: str) -> bool:
    host, qs = _url_info(src)
    if any(h in host for h in ("twitch.tv", "youtube.com", "youtu.be", "facebook.com", "fb.watch", "vimeo.com")):
        return "live" in src.lower()
    if any(ext in src.lower() for ext in (".m3u8", ".mpd")):
        return True
    return False


def _is_live_media(el: Dict[str, Any]) -> bool:
    if _bool_attr(el.get("is_live")) or _bool_attr(el.get("data-live")) or _bool_attr(el.get("live")):
        return True
    src = str(el.get("src") or el.get("data-src") or el.get("href") or "")
    return _detect_platform_live(src)


def _has_audio_track(el: Dict[str, Any]) -> Optional[bool]:
    if "has_audio_track" in el:
        return bool(el.get("has_audio_track"))
    if _bool_attr(el.get("noaudio")) or _bool_attr(el.get("data-noaudio")):
        return False
    return None  # desconocido


def _has_sign_language(el: Dict[str, Any], tracks_info: Dict[str, Any]) -> bool:
    """
    Señales de cumplimiento 1.2.6 (pregrabado):
      - Pista/versión con interpretación en lengua de señas (LSP/ASL/BSL, etc.)
      - Flags del extractor: has_sign_overlay / has_sign_video / has_nearby_sign_link
      - Atributos: data-sign-language / sign_lang_code
    """
    return bool(
        tracks_info["has_sign_track"]
        or el.get("has_sign_overlay")
        or el.get("has_sign_video")
        or el.get("has_nearby_sign_link")
        or (el.get("data-sign-language") or "").strip()
        or (el.get("sign_lang_code") or "").strip()
    )


# -------- núcleo --------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    videos: List[Dict[str, Any]] = list(getattr(ctx, "videos", []) or getattr(ctx, "video", []) or [])
    total = len(videos)

    with_sign = 0
    missing_sign = 0
    decorative = 0
    without_audio = 0
    live_exempt = 0
    requiring_sign = 0

    offenders: List[Dict[str, Any]] = []

    for v in videos:
        if _is_decorative_video(v):
            decorative += 1
            continue

        # Excluir directos (1.2.6 es pregrabado)
        if _is_live_media(v):
            live_exempt += 1
            continue

        has_audio = _has_audio_track(v)
        if has_audio is None:
            has_audio = True  # asumimos típico video con audio
        if not has_audio:
            without_audio += 1
            continue  # 1.2.6 pide señas para el audio pregrabado en medios sincronizados

        requiring_sign += 1
        tracks_info = _collect_tracks_info(v)

        if _has_sign_language(v, tracks_info):
            with_sign += 1
        else:
            missing_sign += 1
            offenders.append({
                "tag": "video",
                "src": (v.get("src") or v.get("data-src") or "")[:200],
                "id": v.get("id", ""),
                "class": v.get("class", []),
                "role": (v.get("role") or "").lower(),
                "aria-hidden": _bool_attr(v.get("aria-hidden")),
                "tracks_kinds": tracks_info["kinds"],
                "tracks_labels": tracks_info["labels"],
                "reason": "Vídeo pregrabado con audio sin interpretación en lengua de señas (1.2.6)."
            })

    ok_ratio = 1.0 if total == 0 else round(
        (with_sign + decorative + without_audio + live_exempt) / total, 4
    )

    return {
        "videos_total": total,
        "requiring_sign": requiring_sign,
        "with_sign": with_sign,
        "missing_sign": missing_sign,
        "without_audio": without_audio,
        "decorative": decorative,
        "live_exempt": live_exempt,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 1.2.6 exige interpretación en lengua de señas para el audio pregrabado en medios sincronizados. "
            "Se aceptan señales: pista/versión con señas, overlay de intérprete o enlace cercano."
        )
    }


def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.2.6; no se pudo evaluar en modo renderizado."}
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note", "") + " | RENDERED: puedes detectar overlays/ventanas PIP de intérprete o links adyacentes.").strip()
    return d


def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False}
    total = details.get("videos_total", 0)
    missing = details.get("missing_sign", 0)
    offenders = details.get("offenders", [])
    if total == 0 or missing == 0:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "videos_total": total,
        "requiring_sign": details.get("requiring_sign", 0),
        "missing_sign": missing,
        "sample_offenders": offenders[:5],
        "html_snippet": (html_sample or "")[:2000],
    }
    prompt = (
        "Para 1.2.6 (Lengua de señas — pregrabado), sugiere opciones: "
        "a) añadir video overlay con intérprete; b) enlace a versión con señas; "
        "c) lineamientos de tamaño/posición recomendados. "
        "Devuelve JSON { suggestions: [{src, approach, embed_hint}], manual_review?: bool }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

def _verdict_from_126(d: Dict[str, Any]) -> tuple[str, bool]:
    """
    Reglas duras 1.2.6 (Lengua de señas — pregrabado):
      - si NO hay videos (videos_total == 0) -> NA
      - si hay videos pero NINGUNO requiere señas (requiring_sign == 0) -> NA
      - si requiere y no falta ninguno -> PASS
      - si faltan todos -> FAIL
      - si faltan algunos -> PARTIAL
    """
    total = int(d.get("videos_total") or 0)
    req   = int(d.get("requiring_sign") or 0)
    miss  = int(d.get("missing_sign") or 0)

    if total == 0 or req == 0:
        d["na"] = True
        return "na", True
    if miss == 0:
        return "pass", True
    if miss >= req:
        return "fail", False
    return "partial", False

def run_1_2_6(
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
        manual_required = ai_info.get("manual_required", False)

    requiring = details.get("requiring_sign", 0)
    missing = details.get("missing_sign", 0)
    passed = (requiring == 0) or (missing == 0)

    verdict, passed = _verdict_from_126(details)
    score0 = score_from_verdict(verdict)
    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0,
        details=details, level=meta.get("level", "AAA"), principle=meta.get("principle", "Perceptible"),
        title=meta.get("title", "Lengua de señas (pregrabado)"), source=src,
        score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
