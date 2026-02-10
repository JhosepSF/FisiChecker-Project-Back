# audits/checks/criteria/p1/c_1_2_4_captions_live.py
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional 
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  # si no existe, el modo IA queda deshabilitado

CODE = "1.2.4"


# -------------------------
# Utilidades y heurísticas
# -------------------------

def _bool_attr(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")


def _has_controls(el: Dict[str, Any]) -> bool:
    # Aplica tanto a <video> como a reproductores embebidos que expongan esta marca
    return (
        "controls" in (el.get("_attrs", {}) or el)
        or _bool_attr(el.get("controls"))
        or bool(el.get("has_controls"))
    )


def _is_decorative_video(el: Dict[str, Any]) -> bool:
    """
    Decorativo si:
      - aria-hidden="true" o role in {"presentation","none"}
      - patrón de video de fondo: autoplay+muted+loop y sin controls
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
    Extrae pistas <track>. Para 1.2.4 nos interesan 'captions'/'subtitles' (aunque en directos
    a veces vengan desde la plataforma y no como <track> nativo).
    """
    tracks = el.get("tracks") or []
    kinds = []
    has_vtt = False
    for t in tracks:
        k = (t.get("kind") or "").lower()
        kinds.append(k)
        if str(t.get("src", "")).lower().endswith(".vtt"):
            has_vtt = True
    return {
        "kinds": kinds,
        "has_captions_track": ("captions" in kinds or "subtitles" in kinds),
        "has_vtt_src": has_vtt,
    }


def _has_audio_track(el: Dict[str, Any]) -> Optional[bool]:
    """
    ¿El medio tiene audio? Para directos, si no hay señal explícita, asumimos True.
    """
    if "has_audio_track" in el:
        return bool(el.get("has_audio_track"))
    if _bool_attr(el.get("noaudio")) or _bool_attr(el.get("data-noaudio")):
        return False
    return None  # desconocido


def _url_info(src: str) -> Tuple[str, Dict[str, List[str]]]:
    try:
        u = urlparse(src)
        return u.netloc.lower(), parse_qs(u.query)
    except Exception:
        return "", {}


def _detect_platform_info(src: str) -> Dict[str, Any]:
    """
    Heurístico de plataforma para iframes/reproductores embebidos.
    No implica cumplimiento, solo capacidad/indicio de CC.
    """
    host, qs = _url_info(src)
    platform = None
    supports_cc = False
    live_hint = False

    if "youtube.com" in host or "youtu.be" in host:
        platform = "youtube"
        supports_cc = True
        # cc_load_policy=1 preactiva CC; 'live' en ruta/qs es indicio
        live_hint = ("live" in src.lower()) or ("cc_load_policy" in qs)
    elif "vimeo.com" in host:
        platform = "vimeo"
        supports_cc = True
        live_hint = "live" in src.lower()
    elif "twitch.tv" in host:
        platform = "twitch"
        supports_cc = True
        live_hint = True
    elif "facebook.com" in host or "fb.watch" in host:
        platform = "facebook"
        supports_cc = True
        live_hint = "live" in src.lower()
    else:
        # Detectores de streaming HLS/DASH como indicio de directo
        if any(ext in src.lower() for ext in (".m3u8", ".mpd")):
            platform = "generic_stream"
            supports_cc = False
            live_hint = True

    return {"platform": platform, "platform_supports_cc": supports_cc, "platform_live_hint": live_hint}


def _is_live_media(el: Dict[str, Any]) -> bool:
    """
    Señales para marcar un medio como 'en directo':
      - flags: is_live / data-live / live / aria-live (polite/assertive)
      - fuente HLS/DASH (.m3u8 / .mpd)
      - plataformas típicas de live (YouTube Live, Twitch, etc.)
    """
    if _bool_attr(el.get("is_live")) or _bool_attr(el.get("data-live")) or _bool_attr(el.get("live")):
        return True

    # aria-live está pensado para regiones; lo usamos como pista débil
    aria_live = (el.get("aria-live") or "").lower()
    if aria_live in {"polite", "assertive"}:
        # Solo si además es un <video> o embed
        if (el.get("tag") or "").lower() in {"video", "iframe", "embed"}:
            return True

    src = (el.get("src") or el.get("data-src") or el.get("href") or "")
    if any(ext in str(src).lower() for ext in (".m3u8", ".mpd")):
        return True

    # pista por plataforma
    p = _detect_platform_info(str(src))
    if p["platform_live_hint"]:
        return True

    # fallback: si el extractor marcó 'streaming' o similar
    if _bool_attr(el.get("streaming")) or _bool_attr(el.get("data-stream")):
        return True

    return False


def _has_live_captions(el: Dict[str, Any], tracks_info: Optional[Dict[str, Any]] = None) -> bool:
    """
    Señales para considerar que HAY subtítulos en directo:
      - <track kind="captions"|"subtitles"> en el <video>
      - flags del extractor: has_live_captions / has_captions / has_nearby_captions
      - parámetros del player que activen CC (p.ej., cc_load_policy=1 en YouTube)
      - marca explícita data-cc-enabled / cc_enabled
    OJO: Capacidad de la plataforma ≠ cumplimiento, pero si además hay toggle CC visible en modo render, cuenta.
    """
    # pistas nativas
    if tracks_info and (tracks_info.get("has_captions_track") or tracks_info.get("has_vtt_src")):
        return True

    # flags del extractor
    if el.get("has_live_captions") or el.get("has_captions") or el.get("has_nearby_captions"):
        return True

    # parámetros del player
    src = str(el.get("src") or el.get("data-src") or el.get("href") or "")
    host, qs = _url_info(src)
    if "cc_load_policy" in qs:
        return True

    # banderas genéricas
    if _bool_attr(el.get("data-cc-enabled")) or _bool_attr(el.get("cc_enabled")):
        return True

    # modo renderizado podrá detectar el botón CC
    return False


# -------------------------
# Núcleo del criterio
# -------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    Evaluamos directos en:
      - <video> con streaming o marcado como live
      - <iframe>/<embed> de plataformas conocidas con indicio de live
    1.2.4 requiere subtítulos SOLO para contenido de audio EN DIRECTO en medios sincronizados.
    Por tanto: vídeo EN DIRECTO con audio → requiere CC. Audio-only live no entra en 1.2.4 (eso es 1.2.9 AAA).
    """
    videos: List[Dict[str, Any]] = list(getattr(ctx, "videos", []) or getattr(ctx, "video", []) or [])
    iframes: List[Dict[str, Any]] = list(getattr(ctx, "iframes", []) or getattr(ctx, "iframe", []) or [])

    candidates: List[Dict[str, Any]] = []

    # Normalizamos etiqueta para reportes
    for v in videos:
        v.setdefault("tag", "video")
        if _is_live_media(v):
            candidates.append(v)

    for f in iframes:
        f.setdefault("tag", "iframe")
        # Solo consideramos iframes que apunten a players/plataformas
        src = str(f.get("src") or f.get("data-src") or "")
        if not src:
            continue
        if _is_live_media(f):
            # adjuntamos meta de plataforma para reporting
            f["_platform_info"] = _detect_platform_info(src)
            candidates.append(f)

    total_live = len(candidates)

    with_captions = 0
    missing_captions = 0
    decorative = 0
    without_audio = 0
    requiring_captions = 0
    offenders: List[Dict[str, Any]] = []

    for el in candidates:
        tag = (el.get("tag") or "").lower()

        # Consideramos decorativo para <video> si patrón de fondo
        # Para <iframe>, solo si aria-hidden/role presentation (no solemos tener loop/muted info real)
        if tag == "video":
            if _is_decorative_video(el):
                decorative += 1
                continue
        else:
            role = (el.get("role") or "").lower()
            if _bool_attr(el.get("aria-hidden")) or role in {"presentation", "none"}:
                decorative += 1
                continue

        # ¿Tiene audio? Si desconocido, asumimos que SÍ (es lo común en directos)
        has_audio = _has_audio_track(el)
        if has_audio is None:
            has_audio = True
        if not has_audio:
            without_audio += 1
            continue  # Un directo sin audio no requiere subtítulos en 1.2.4

        requiring_captions += 1

        tracks_info = _collect_tracks_info(el) if tag == "video" else None
        has_cc = _has_live_captions(el, tracks_info)

        if has_cc:
            with_captions += 1
        else:
            missing_captions += 1
            offenders.append({
                "tag": tag,
                "src": (el.get("src") or el.get("data-src") or el.get("href") or "")[:220],
                "id": el.get("id", ""),
                "class": el.get("class", []),
                "role": (el.get("role") or "").lower(),
                "aria-hidden": _bool_attr(el.get("aria-hidden")),
                "has_controls": _has_controls(el),
                "tracks_kinds": (tracks_info or {}).get("kinds") if tracks_info else None,
                "platform_info": el.get("_platform_info"),
                "reason": "Directo con audio sin subtítulos en vivo (1.2.4)."
            })

    ok_ratio = 1.0 if total_live == 0 else round(
        (with_captions + decorative + without_audio) / total_live, 4
    )

    details: Dict[str, Any] = {
        "live_media_total": total_live,
        "requiring_captions": requiring_captions,
        "with_captions": with_captions,
        "missing_captions": missing_captions,
        "without_audio": without_audio,
        "decorative": decorative,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 1.2.4 exige subtítulos para contenido de audio EN DIRECTO en medios sincronizados. "
            "Detectamos 'live' en <video> o embeds (<iframe>) por flags (is_live/data-live), fuentes HLS/DASH (.m3u8/.mpd) "
            "y hints de plataforma (YouTube/Twitch/Vimeo/Facebook). Vídeos de fondo o sin audio no requieren."
        )
    }
    return details


def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En DOM post-render, puedes:
      - Detectar botón CC visible (role=button, aria-label~='CC'/'Subtítulos', data-title='Subtítulos')
      - Leer aria-pressed del botón CC (si está activo)
      - Confirmar 'has_audio_track' con Web APIs si tu extractor lo habilita
      - Marcar has_nearby_captions si hay un control/leyenda 'Subtítulos' visible cerca del player
    """
    if rctx is None:
        return {
            "na": True,
            "note": "No se proveyó rendered_ctx para 1.2.4; no se pudo evaluar en modo renderizado."
        }
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note", "") + " | RENDERED: resolvible a botón CC visible/activo y APIs de audio del player.").strip()
    return d


# -------------------------
# Modo IA (opcional)
# -------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    Si hay directos sin subtítulos, la IA sugiere:
      - Pasos de activación para subtítulos en vivo (genéricos)
      - Un stub de pauta operativa (roles: operador CC, latencia, pruebas previas)
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    total = details.get("live_media_total", 0)
    missing = details.get("missing_captions", 0)
    offenders = details.get("offenders", [])
    if total == 0 or missing == 0:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "live_media_total": total,
        "requiring_captions": details.get("requiring_captions", 0),
        "missing_captions": missing,
        "sample_offenders": offenders[:5],
        "html_snippet": (html_sample or "")[:2000],
    }
    prompt = (
        "Evalúa el criterio WCAG 1.2.4 (Subtítulos — en directo). "
        "Para cada 'offender', propone pasos para habilitar subtítulos en vivo en el player/plataforma "
        "(instrucciones genéricas, sin marcas) y un checklist operativo (latencia, prueba técnica, "
        "responsable de CC). Devuelve JSON: { suggestions: [{src, enable_steps, ops_checklist}], "
        "manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

def _verdict_from_124(d: Dict[str, Any]) -> tuple[str, bool]:
    """
    Reglas duras 1.2.4 (Subtítulos en directo):
      - si NO hay medios live (live_media_total == 0) -> NA
      - si hay live pero NINGUNO requiere CC (requiring_captions == 0, p.ej. todos sin audio/decorativos) -> NA
      - si requiere y no falta ninguno -> PASS
      - si faltan todos -> FAIL
      - si faltan algunos -> PARTIAL
    """
    total = int(d.get("live_media_total") or 0)
    req   = int(d.get("requiring_captions") or 0)
    miss  = int(d.get("missing_captions") or 0)

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

def run_1_2_4(
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
    requiring = details.get("requiring_captions", 0)
    missing = details.get("missing_captions", 0)
    passed = (requiring == 0) or (missing == 0)

    verdict, passed = _verdict_from_124(details)
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
        title=meta.get("title", "Subtítulos (en directo)"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
