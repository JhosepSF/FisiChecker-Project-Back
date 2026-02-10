# audits/checks/criteria/p1/c_1_2_7_extended_ad_prerecorded.py
from typing import Dict, Any, List, Optional, Tuple

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "1.2.7"  # AAA


def _bool_attr(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")


def _is_decorative_video(el: Dict[str, Any]) -> bool:
    role = (el.get("role") or "").lower()
    return _bool_attr(el.get("aria-hidden")) or role in {"presentation", "none"}


def _has_audio_track(el: Dict[str, Any]) -> Optional[bool]:
    if "has_audio_track" in el:
        return bool(el.get("has_audio_track"))
    if _bool_attr(el.get("noaudio")) or _bool_attr(el.get("data-noaudio")):
        return False
    return None


def _needs_extended_ad(el: Dict[str, Any]) -> bool:
    """
    No es inferible automáticamente. Usamos flags del extractor:
      - needs_extended_ad / dense_audio / no_dialogue_pauses / high_speech_density
    """
    return bool(
        el.get("needs_extended_ad")
        or el.get("dense_audio")
        or el.get("no_dialogue_pauses")
        or el.get("high_speech_density")
    )


def _has_extended_ad(el: Dict[str, Any]) -> bool:
    """
    Señales de cumplimiento:
      - has_extended_ad / has_extended_ad_version / data-extended-ad
      - link cercano a 'versión con audiodescripción ampliada'
    """
    return bool(
        el.get("has_extended_ad")
        or el.get("has_extended_ad_version")
        or _bool_attr(el.get("data-extended-ad"))
        or el.get("has_nearby_extended_ad_link")
    )


def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    videos: List[Dict[str, Any]] = list(getattr(ctx, "videos", []) or getattr(ctx, "video", []) or [])
    total = len(videos)

    requiring_ext_ad = 0
    with_ext_ad = 0
    missing_ext_ad = 0
    decorative = 0
    without_audio = 0

    offenders: List[Dict[str, Any]] = []

    for v in videos:
        if _is_decorative_video(v):
            decorative += 1
            continue

        has_audio = _has_audio_track(v)
        if has_audio is None:
            has_audio = True
        if not has_audio:
            without_audio += 1
            continue

        if not _needs_extended_ad(v):
            # Sin señal de necesidad → NA (no contaría como requerimiento)
            continue

        requiring_ext_ad += 1
        if _has_extended_ad(v):
            with_ext_ad += 1
        else:
            missing_ext_ad += 1
            offenders.append({
                "tag": "video",
                "src": (v.get("src") or v.get("data-src") or "")[:200],
                "id": v.get("id", ""),
                "class": v.get("class", []),
                "reason": "Marcado como que requiere AD ampliada pero no se detecta versión/flag (1.2.7)."
            })

    ok_ratio = 1.0 if total == 0 else round(
        (with_ext_ad + decorative + without_audio + (total - requiring_ext_ad - decorative - without_audio)) / total, 4
    )

    return {
        "videos_total": total,
        "requiring_extended_ad": requiring_ext_ad,
        "with_extended_ad": with_ext_ad,
        "missing_extended_ad": missing_ext_ad,
        "decorative": decorative,
        "without_audio": without_audio,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 1.2.7 aplica SOLO si se determina que el vídeo necesita AD ampliada "
            "(p.ej., sin pausas para insertar AD). Esto se basa en flags del extractor; "
            "si no hay flags, el criterio se marca como NA implícito."
        )
    }


def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.2.7; no se pudo evaluar en modo renderizado."}
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note", "") + " | RENDERED: puedes detectar toggles/UI de 'AD ampliada' o enlaces cercanos.").strip()
    return d


def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False}
    total = details.get("videos_total", 0)
    missing = details.get("missing_extended_ad", 0)
    offenders = details.get("offenders", [])
    if total == 0 or missing == 0:
        return {"ai_used": False, "manual_required": False}
    ctx_json = {
        "videos_total": total,
        "requiring_extended_ad": details.get("requiring_extended_ad", 0),
        "missing_extended_ad": missing,
        "sample_offenders": offenders[:5],
        "html_snippet": (html_sample or "")[:2000],
    }
    prompt = (
        "Para 1.2.7 (AD ampliada — pregrabado), sugiere un plan: inserciones con pausas extendidas, "
        "edición con relleno silencioso, y guía de publicación. JSON { suggestions:[{src, plan}], manual_review?:bool }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}


def _verdict_from_127(d: Dict[str, Any]) -> Tuple[str, bool]:
    """
    Reglas duras 1.2.7 (AD extendida — pregrabado):
      - si NO hay videos (videos_total == 0) -> NA
      - si hay videos pero NINGUNO requiere AD extendida (requiring_extended_ad == 0) -> NA
      - si requiere y no falta ninguno -> PASS
      - si faltan todos -> FAIL
      - si faltan algunos -> PARTIAL
    """
    total = int(d.get("videos_total") or 0)
    req   = int(d.get("requiring_extended_ad") or 0)
    miss  = int(d.get("missing_extended_ad") or 0)

    if total == 0 or req == 0:
        d["na"] = True
        return "na", True
    if miss == 0:
        return "pass", True
    if miss >= req:
        return "fail", False
    return "partial", False

def run_1_2_7(
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

    # ⬇️ Veredicto ESTRICTO para 1.2.7 (evita "PASA" cuando no aplica)
    verdict, passed = _verdict_from_127(details)
    score0 = score_from_verdict(verdict)

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0,
        details=details, level=meta.get("level", "AAA"),
        principle=meta.get("principle", "Perceptible"),
        title=meta.get("title", "Audiodescripción extendida (pregrabado)"),
        source=src, score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )