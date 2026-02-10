# audits/checks/criteria/p1/c_1_2_2_captions_prerecorded.py
from typing import Dict, Any, List, Optional

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional 
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  # si no existe, el modo IA queda deshabilitado

CODE = "1.2.2"


def _bool_attr(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")


def _has_controls(el: Dict[str, Any]) -> bool:
    # Acepta tanto presencia literal del atributo 'controls' como booleanos que pueda poner el extractor
    return (
        "controls" in (el.get("_attrs", {}) or el)
        or _bool_attr(el.get("controls"))
        or bool(el.get("has_controls"))
    )


def _is_decorative_video(el: Dict[str, Any]) -> bool:
    """
    Consideramos decorativo si:
      - aria-hidden="true" o role in {"presentation","none"}
      - patrón típico de vídeo de fondo: autoplay+muted+loop y sin controls
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
    Extrae pistas <track>. Para 1.2.2 nos interesa especialmente 'captions' o 'subtitles'.
    """
    tracks = el.get("tracks") or []
    kinds = []
    for t in tracks:
        kinds.append((t.get("kind") or "").lower())

    # Si hay src en pistas, útil como señal (p.ej., .vtt)
    has_vtt = any(str(t.get("src", "")).lower().endswith(".vtt") for t in tracks)

    return {
        "has_captions_track": ("captions" in kinds or "subtitles" in kinds),
        "has_descriptions_track": ("descriptions" in kinds),
        "has_vtt_src": has_vtt,
        "kinds": kinds,
    }


def _has_audio_track(el: Dict[str, Any]) -> Optional[bool]:
    """
    Determina si el vídeo tiene audio:
      - Si el extractor provee 'has_audio_track' => usarlo.
      - Si hay marcas explícitas de 'noaudio' => False.
      - En ausencia de señales explícitas, asumimos True (vídeo típico con audio).
    """
    if "has_audio_track" in el:
        return bool(el.get("has_audio_track"))
    if _bool_attr(el.get("noaudio")) or _bool_attr(el.get("data-noaudio")):
        return False
    # 'muted' no implica ausencia de pista de audio; solo que inicia silenciado.
    return None  # desconocido → lo trataremos como True por defecto


def _has_captions(el: Dict[str, Any], tracks_info: Dict[str, Any]) -> bool:
    """
    Señales aceptadas para considerar que cumple 1.2.2:
      - <track kind="captions"> o "subtitles"
      - data-captions / has_captions / has_nearby_captions (si el extractor lo marca)
      - (opcional) presencia de .vtt en una pista
    Nota: Una transcripción textual aislada NO sustituye subtítulos en 1.2.2.
    """
    data_caps = (el.get("data-captions") or "").strip()
    has_flags = bool(el.get("has_captions") or el.get("has_nearby_captions"))
    return bool(tracks_info["has_captions_track"] or tracks_info["has_vtt_src"] or data_caps or has_flags)


def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    # Defensivo: soporta varias convenciones de extracción
    videos: List[Dict[str, Any]] = list(getattr(ctx, "videos", []) or getattr(ctx, "video", []) or [])
    total = len(videos)

    with_captions = 0
    decorative = 0
    missing_captions = 0
    without_audio = 0
    requiring_captions = 0
    offenders: List[Dict[str, Any]] = []

    for v in videos:
        if _is_decorative_video(v):
            decorative += 1
            continue

        # ¿Tiene audio?
        has_audio = _has_audio_track(v)
        if has_audio is None:
            # Desconocido → asumimos que sí hay audio (caso típico)
            has_audio = True

        if not has_audio:
            without_audio += 1
            continue  # 1.2.2 aplica a audio pregrabado en medios sincronizados (vídeo con audio)

        requiring_captions += 1

        tracks_info = _collect_tracks_info(v)
        if _has_captions(v, tracks_info):
            with_captions += 1
        else:
            missing_captions += 1
            offenders.append({
                "tag": "video",
                "src": (v.get("src") or v.get("data-src") or "")[:180],
                "id": v.get("id", ""),
                "class": v.get("class", []),
                "role": (v.get("role") or "").lower(),
                "aria-hidden": _bool_attr(v.get("aria-hidden")),
                "has_controls": _has_controls(v),
                "tracks_kinds": _collect_tracks_info(v)["kinds"],
                "reason": "Vídeo pregrabado con audio sin subtítulos (1.2.2)."
            })

    ok_ratio = 1.0 if total == 0 else round(
        (with_captions + decorative + without_audio) / total, 4
    )

    details: Dict[str, Any] = {
        "videos_total": total,
        "requiring_captions": requiring_captions,
        "with_captions": with_captions,
        "missing_captions": missing_captions,
        "without_audio": without_audio,
        "decorative": decorative,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 1.2.2 exige subtítulos para TODO audio pregrabado en medios sincronizados (video con audio). "
            "Acepta <track kind='captions'/'subtitles'>, banderas data-captions/has_captions/has_nearby_captions "
            "o pistas .vtt. Vídeos sin audio o decorativos no requieren subtítulos. "
            "Una transcripción sola NO sustituye subtítulos en 1.2.2."
        )
    }
    return details


def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    Con DOM post-render (Playwright) podrías:
      - Resolver aria-labelledby/aria-describedby a nodos reales (p.ej., botón CC)
      - Detectar overlays o toggles de subtítulos provistos por el reproductor
      - Inferir 'has_audio_track' mediante Web APIs (si las expones en tu extractor)
    """
    if rctx is None:
        return {
            "na": True,
            "note": "No se proveyó rendered_ctx para 1.2.2; no se pudo evaluar en modo renderizado."
        }
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note", "") + " | RENDERED: resolvible a toggles CC, aria-describedby y Web APIs de audio.").strip()
    return d


def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    Si hay vídeos que requieren subtítulos pero no los tienen, pedimos a la IA:
      - Sugerir un esqueleto .VTT (2–3 cues) en lenguaje simple
      - Indicar si parece requerir revisión manual (p.ej., habla múltiple o contenido técnico)
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    total = details.get("videos_total", 0)
    missing = details.get("missing_captions", 0)
    offenders = details.get("offenders", [])
    if total == 0 or missing == 0:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "videos_total": total,
        "requiring_captions": details.get("requiring_captions", 0),
        "missing_captions": missing,
        "sample_offenders": offenders[:5],
        "html_snippet": (html_sample or "")[:2000],
    }
    prompt = (
        "Evalúa el criterio WCAG 1.2.2 (Subtítulos — pregrabado). "
        "Para cada 'offender', sugiere un esqueleto de archivo WebVTT breve en español "
        "(incluye 'WEBVTT' y 2–3 cues con tiempos de ejemplo y texto conciso). "
        "Devuelve JSON: { suggestions: [{src, vtt_stub}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}


def run_1_2_2(
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

    # 2) Si modo IA, agrega sugerencias
    manual_required = False
    if mode == CheckMode.AI:
        ai_info = _ai_review(details, html_sample=html_for_ai)
        details["ai_info"] = ai_info
        src = "ai"
        manual_required = ai_info.get("manual_required", False)

    # 3) passed / verdict / score
    requiring = details.get("requiring_captions", 0)
    missing = details.get("missing_captions", 0)
    
    # Ultra estricto: PASS solo si 100%, PARTIAL >= 80%, FAIL < 80%
    if requiring == 0:
        passed = True
        details["ratio"] = 1.0
    else:
        ok_count = requiring - missing
        ratio = ok_count / requiring
        details["ratio"] = ratio
        # Solo PASS si 0 violaciones
        if missing == 0:
            passed = True
        elif ratio >= 0.80:
            passed = True  # verdict_from_counts detectará partial
        else:
            passed = False

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
        title=meta.get("title", "Subtítulos (pregrabado)"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
