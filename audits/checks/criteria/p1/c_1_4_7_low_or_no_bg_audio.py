# audits/checks/criteria/p1/c_1_4_7_low_or_no_bg_audio.py
from typing import Dict, Any, List, Optional, Tuple
import math

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional 
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  # si no existe, el modo IA queda deshabilitado

CODE = "1.4.7"

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
    return str(v).lower() in ("true", "1", "yes")

def _get_attr_str(el: Any, name: str) -> str:
    """Devuelve el atributo como str ('' si no existe), tolerando Tag o dict y listas."""
    if el is None:
        return ""
    v = None
    if isinstance(el, dict):
        v = el.get(name)
    else:
        try:
            if hasattr(el, "get"):
                v = el.get(name)  # BeautifulSoup Tag
            else:
                v = getattr(el, name, None)
        except Exception:
            v = None
    if v is None:
        return ""
    if isinstance(v, (list, tuple, set)):
        return " ".join(str(x) for x in v if x is not None)
    return str(v)

def _has_attr_presence(el: Any, name: str) -> bool:
    """True si el atributo booleano está presente o si hay flags equivalentes."""
    if el is None:
        return False
    if isinstance(el, dict):
        if el.get(name) is True or el.get(f"has_{name}") is True or el.get(f"is_{name}") is True:
            return True
    try:
        if hasattr(el, "attrs") and name in getattr(el, "attrs", {}):  # type: ignore[attr-defined]
            return True
    except Exception:
        pass
    v = _get_attr_str(el, name)
    return _bool(v) if v else False

def _src_url(el: Any) -> str:
    for k in ("src", "data-src", "data-url"):
        v = _get_attr_str(el, k)
        if v:
            return v.strip()
    return ""

# -------------------------
# Heurísticas (aplicabilidad y cumplimiento)
# -------------------------

_SPEECH_HINTS = (
    "podcast","entrevista","interview","voz","voice","narracion","narración",
    "speech","charla","talk","locucion","locución","audio description","narrator"
)

def _looks_like_speech_content(el: Any) -> bool:
    """
    WCAG 1.4.7 aplica a audio pregrabado que contiene habla.
    Heurística si el extractor no provee flags:
      - filename/clase/título/aria-label con pistas de habla.
    """
    src = _src_url(el).lower()
    title = (_get_attr_str(el, "title") or "").lower()
    label = (_get_attr_str(el, "aria-label") or "").lower()
    klass = (_get_attr_str(el, "class") or "").lower()
    hay_pistas = any(h in (src + " " + title + " " + label + " " + klass) for h in _SPEECH_HINTS)
    if hay_pistas:
        return True
    # flag directo del extractor
    if isinstance(el, dict) and (_bool(el.get("has_speech")) or _bool(el.get("speech_content"))):
        return True
    return False

def _is_prerecorded(el: Any) -> bool:
    """
    Excluye audio en vivo. Acepta flags 'is_live', 'live' o pistas en URL.
    """
    if isinstance(el, dict) and (_bool(el.get("is_live")) or _bool(el.get("live"))):
        return False
    url = _src_url(el).lower()
    if any(x in url for x in ("live=", "/live/", "stream", "livestream")):
        return False
    return True

def _has_bg_toggle_off(el: Any) -> bool:
    """
    Cumple si el usuario puede desactivar el sonido de fondo (música/ambiente) dejando solo la voz.
    Flags comunes: has_bg_toggle, can_disable_bg, music_toggle, bg_track_mutable.
    """
    if not isinstance(el, dict):
        return False
    keys = ("has_bg_toggle", "can_disable_bg", "music_toggle", "bg_track_mutable", "has_music_mute", "has_bg_music_mute")
    return any(_bool(el.get(k)) for k in keys)

def _bg_20db_lower_ok(el: Any) -> Optional[bool]:
    """
    Cumple si el fondo está al menos 20 dB por debajo de la voz.
    Acepta métricas del extractor:
      - bg_to_speech_db (negativo si el fondo es menor): OK si <= -20
      - speech_to_bg_db (positivo): OK si >= +20
      - bg_to_speech_ratio (lineal, p.ej. 0.1): OK si 20*log10(ratio) <= -20 → ratio <= 0.1
    Devuelve True/False o None si no hay datos.
    """
    if not isinstance(el, dict):
        return None
    # métrica directa (fondo relativo a voz)
    v1 = el.get("bg_to_speech_db")
    if isinstance(v1, (int, float)):
        return float(v1) <= -20.0
    # métrica inversa (voz relativa a fondo)
    v2 = el.get("speech_to_bg_db")
    if isinstance(v2, (int, float)):
        return float(v2) >= 20.0
    # ratio lineal fondo/voz
    r = el.get("bg_to_speech_ratio")
    if isinstance(r, (int, float)) and r >= 0:
        try:
            db = 20.0 * math.log10(max(1e-12, float(r)))
            return db <= -20.0
        except Exception:
            return None
    return None

def _no_background_audio(el: Any) -> Optional[bool]:
    """
    Cumple si no hay audio de fondo (solo voz).
    Flags: has_background_audio / background_music / bg_present → False.
    """
    if not isinstance(el, dict):
        return None
    if "has_background_audio" in el:
        return (not _bool(el.get("has_background_audio")))
    if "background_music" in el:
        return (not _bool(el.get("background_music")))
    if "bg_present" in el:
        return (not _bool(el.get("bg_present")))
    return None

# -------------------------
# Núcleo del criterio
# -------------------------

def _collect_media(ctx: PageContext) -> List[Any]:
    """
    Reúne <audio> y <video> que probablemente contengan habla pregrabada.
    """
    audios = _as_list(getattr(ctx, "audios", []))
    videos = _as_list(getattr(ctx, "videos", []))
    return audios + videos

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW: Para cada medio aplicable (audio/video pregrabado con habla), cumple si:
      a) no hay audio de fondo, o
      b) se puede desactivar el fondo, o
      c) el fondo está ≥20 dB por debajo de la voz.
    Si no hay datos suficientes → requiere revisión (unknown_metrics).
    """
    media = _collect_media(ctx)

    examined = 0
    applicable = 0
    pass_no_bg = 0
    pass_toggle_off = 0
    pass_minus20db = 0
    unknown_metrics = 0
    violations = 0

    offenders: List[Dict[str, Any]] = []

    for el in media:
        examined += 1
        if not _is_prerecorded(el):
            continue
        if not _looks_like_speech_content(el):
            continue

        applicable += 1
        src = _src_url(el)[:180]

        # a) no background
        no_bg = _no_background_audio(el)
        if no_bg is True:
            pass_no_bg += 1
            continue

        # b) toggle para apagar fondo
        if _has_bg_toggle_off(el):
            pass_toggle_off += 1
            continue

        # c) fondo ≥20 dB por debajo
        ok_db = _bg_20db_lower_ok(el)
        if ok_db is True:
            pass_minus20db += 1
            continue

        if ok_db is None and no_bg is None and not isinstance(el, dict):
            # No tenemos métricas ni flags porque es un Tag sin anotaciones → revisión
            unknown_metrics += 1
            offenders.append({
                "type": "media_unknown",
                "src": src,
                "reason": "No hay datos sobre fondo/voz (se requiere revisión manual)."
            })
        else:
            # Hay algún indicio de fondo y no cumple
            violations += 1
            offenders.append({
                "type": "media_violation",
                "src": src,
                "has_bg_toggle": _has_bg_toggle_off(el) if isinstance(el, dict) else False,
                "db_ok": ok_db,
                "no_background": no_bg,
                "reason": "Audio con voz sin opción de apagar fondo ni atenuación ≥20 dB."
            })

    denom = max(1, applicable)
    ok_ratio = round(max(0.0, min(1.0, (pass_no_bg + pass_toggle_off + pass_minus20db) / denom)), 4) if applicable else 1.0

    details: Dict[str, Any] = {
        "media_examined": examined,
        "applicable": applicable,
        "pass_no_background": pass_no_bg,
        "pass_toggle_off_background": pass_toggle_off,
        "pass_background_minus_20db": pass_minus20db,
        "unknown_metrics": unknown_metrics,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 1.4.7 aplica a audio pregrabado con habla. Cumple si no hay fondo, si puede apagarse, "
            "o si el fondo está al menos 20 dB por debajo de la voz. Si no hay datos, se marca para revisión."
        )
    }
    
    if applicable == 0:
        details["na"] = True
        details["ok_ratio"] = None  # opcional: evita confundir con 1.0
        details["note"] = details.get("note","") + " | NA: no se detectó audio/video pregrabado con habla."
    
    return details

# -------------------------
# Rendered
# -------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, tu extractor puede aportar:
      audio_analysis = [
        {
          "src": str,
          "is_playing": bool,
          "is_live": bool,
          "has_speech": bool,
          "has_background_audio": bool,
          "speech_to_bg_db": float | None,   # +dB si voz > fondo
          "bg_to_speech_db": float | None,  # -dB si fondo < voz
          "bg_to_speech_ratio": float | None,
          "has_bg_toggle": bool, "can_disable_bg": bool, "music_toggle": bool
        }, ...
      ]
    Con esto confirmamos cumplimiento sin suposiciones.
    """
    
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.4.7; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    aa = _as_list(getattr(rctx, "audio_analysis", []))
    if not aa:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'audio_analysis'.").strip()
        # Si RAW ya marcó NA, perfecto; si no, devolvemos d tal cual
        return d

    # Reinferimos con datos más fiables
    examined = d.get("media_examined", 0)
    applicable = 0
    pass_no_bg = 0
    pass_toggle_off = 0
    pass_minus20db = 0
    unknown = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for it in aa:
        if it.get("is_live"):
            continue
        if not it.get("has_speech"):
            continue
        applicable += 1
        src = str(it.get("src") or "")[:180]

        # no background
        if it.get("has_background_audio") is False:
            pass_no_bg += 1
            continue

        # toggle
        if any(bool(it.get(k)) for k in ("has_bg_toggle","can_disable_bg","music_toggle")):
            pass_toggle_off += 1
            continue

        # >= 20 dB
        ok_db = None
        if isinstance(it.get("bg_to_speech_db"), (int, float)):
            ok_db = float(it["bg_to_speech_db"]) <= -20.0
        elif isinstance(it.get("speech_to_bg_db"), (int, float)):
            ok_db = float(it["speech_to_bg_db"]) >= 20.0
        elif isinstance(it.get("bg_to_speech_ratio"), (int, float)):
            ratio = float(it["bg_to_speech_ratio"])
            ok_db = (ratio <= 0.1)

        if ok_db is True:
            pass_minus20db += 1
        elif ok_db is None:
            unknown += 1
            offenders.append({
                "type": "media_unknown",
                "src": src,
                "reason": "Sin métrica de fondo↔voz (revisión manual)."
            })
        else:
            violations += 1
            offenders.append({
                "type": "media_violation",
                "src": src,
                "reason": "Fondo presenta atenuación < 20 dB y no hay toggle para apagarlo."
            })

    denom = max(1, applicable)
    ok_ratio = round(max(0.0, min(1.0, (pass_no_bg + pass_toggle_off + pass_minus20db) / denom)), 4) if applicable else 1.0

    d.update({
        "media_examined": examined,
        "applicable": applicable,
        "pass_no_background": pass_no_bg,
        "pass_toggle_off_background": pass_toggle_off,
        "pass_background_minus_20db": pass_minus20db,
        "unknown_metrics": unknown,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders + _as_list(d.get("offenders", [])),
        "note": (d.get("note","") + " | RENDERED: métricas de audio aplicadas.").strip()
    })
    
    if applicable == 0:
        d["na"] = True
        d["ok_ratio"] = None
        d["note"] += " | RENDERED→NA: no hay audio pregrabado con habla; 1.4.7 no aplica."
    
    return d

# -------------------------
# IA opcional
# -------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: recomienda soluciones para cumplir 1.4.7:
      - Exportar pista 'solo voz' sin música de fondo.
      - Añadir toggle para desactivar música/ambiente de fondo.
      - Mezclar bajando el fondo ≥ 20 dB respecto de la voz.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    offs = details.get("offenders", []) or []
    if not offs and (details.get("violations", 0) or 0) == 0:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "applicable": details.get("applicable", 0),
            "violations": details.get("violations", 0),
            "pass_no_background": details.get("pass_no_background", 0),
            "pass_toggle_off_background": details.get("pass_toggle_off_background", 0),
            "pass_background_minus_20db": details.get("pass_background_minus_20db", 0),
        },
        "offenders": offs[:15],
        "html_snippet": (html_sample or "")[:2000],
    }
    prompt = (
        "Actúa como auditor WCAG 1.4.7 (Low or No Background Audio). "
        "Propón correcciones: 1) ofrecer una versión sin fondo; 2) añadir un control para apagar música/ambiente; "
        "3) ajustar la mezcla para que el fondo esté ≥20 dB por debajo de la voz. "
        "Devuelve JSON: { suggestions: [{type, reason, authoring_fix?, player_fix?, production_fix?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------
# Orquestación
# -------------------------

def run_1_4_7(
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
        manual_required = ai_info.get("manual_review", False)

    # 3) passed / verdict / score
    violations = int(details.get("violations", 0) or 0)
    passed = (violations == 0)

    verdict = verdict_from_counts(details, passed)
    score0 = score_from_verdict(verdict)

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE,
        passed=passed,
        verdict=verdict,
        score_0_2=score0,
        details=details,
        level=meta.get("level", "AAA"),
        principle=meta.get("principle", "Perceptible"),
        title=meta.get("title", "Sonido de fondo bajo o inexistente"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required or (details.get("unknown_metrics", 0) > 0)
    )
