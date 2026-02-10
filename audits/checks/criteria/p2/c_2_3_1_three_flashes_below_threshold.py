# audits/checks/criteria/p2/c_2_3_1_three_flashes_below_threshold.py
from typing import Dict, Any, List, Optional, Tuple
import re
import math

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict
from ..applicability import ensure_na_if_no_applicable, normalize_pass_for_applicable

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.3.1"

# -------------------------------------------------------------------
# Utilidades
# -------------------------------------------------------------------

def _as_list(x):
    if not x:
        return []
    if isinstance(x, list):
        return x
    return list(x)

def _s(v: Any) -> str:
    return "" if v is None else str(v)

def _lower(v: Any) -> str:
    return _s(v).strip().lower()

def _bool(v: Any) -> bool:
    sv = _lower(v)
    return sv in ("true", "1", "yes")

def _to_seconds(v: Any) -> Optional[float]:
    """
    Convierte duraciones a segundos (acepta: num, '500ms','0.2s','1.5m','2h')
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    sv = _lower(v)
    if sv == "":
        return None
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(ms|s|m|h)?\s*$", sv)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2) or "s"
    if unit == "ms": return num / 1000.0
    if unit == "s":  return num
    if unit == "m":  return num * 60.0
    if unit == "h":  return num * 3600.0
    return None

# Umbrales simplificados
MAX_FLASHES_PER_SEC = 3.0  # “no más de tres destellos en cualquier período de un segundo”
# Nota: El “General Flash and Red Flash Threshold” involucra área y luminancia (no se calcula aquí).
# Este check marca “riesgo” si hay indicios de rojo dominante, pero no intenta medir área/contraste.

# Pistas por nombre/clase que suelen indicar “flash/strobe”
FLASHY_CLASS_HINTS = (
    "strobe","strobing","flash","flashing","blink","blinking","rapid","danger-flash",
    "warning-flash","pulse-fast","pulse-rapid"
)

# -------------------------------------------------------------------
# Heurísticas de candidatos
# -------------------------------------------------------------------

def _looks_flashy_animation(a: Dict[str, Any]) -> Tuple[bool, Optional[float]]:
    """
    Heurística básica para animaciones CSS/JS:
      - Duración muy corta (<= 0.5s) + alternancias de visibilidad/opacidad/alto contraste → sospecha de flashing.
      - Si hay 'iteration_count' alto o infinito, inferimos flashes/seg ~ (1/duración)*alternancias.
    Devuelve (is_flashy_candidate, approx_flashes_per_sec | None)
    """
    dur = _to_seconds(a.get("duration_s") or a.get("animation_duration") or a.get("duration"))
    if dur is None or dur <= 0:
        # Algunos extractores exponen period/frequency directamente
        freq = a.get("frequency_hz")
        if isinstance(freq, (int, float)) and freq > 0:
            return (freq > MAX_FLASHES_PER_SEC, float(freq))
        return (False, None)

    # Propiedades que suelen producir “flash”: opacity 0<->1, visibility toggle, color/bg-color muy contrastante
    props = _lower(a.get("properties") or a.get("animation_name") or a.get("keyframes") or "")
    toggles_opacity = ("opacity" in props) or ("visibility" in props)
    toggles_color   = ("background" in props) or ("color" in props) or ("filter" in props)

    # Alternancias por ciclo (muy simplificado)
    alternations = 0
    if toggles_opacity: alternations += 1
    if toggles_color:   alternations += 1
    if alternations == 0 and "blink" in props:
        alternations = 1

    if alternations == 0:
        return (False, None)

    # Aprox de flashes por segundo (cada alternancia ~1 flash por ciclo)
    fps = (alternations / max(dur, 1e-6))
    is_flashy = fps > MAX_FLASHES_PER_SEC or dur <= 0.25  # muy corto → sospechoso
    return (is_flashy, fps)

def _looks_flashy_gif(meta: Dict[str, Any]) -> Tuple[bool, Optional[float]]:
    """
    Si el extractor aporta metadatos de GIF (frame_delay_ms, loop, etc.), estimamos flashes/seg.
    Si no, marcamos como desconocido.
    """
    fd_ms = meta.get("frame_delay_ms")
    if isinstance(fd_ms, (int, float)) and fd_ms > 0:
        fps = 1000.0 / float(fd_ms)
        # Un “flash” típico alterna frames claros/oscuros → conservador: 0.5 * fps
        flashes = 0.5 * fps
        return (flashes > MAX_FLASHES_PER_SEC, flashes)
    return (False, None)

def _candidate_from_class_hints(n: Dict[str, Any]) -> bool:
    cls = _lower(n.get("class"))
    return any(h in cls for h in FLASHY_CLASS_HINTS)

def _red_risk(n: Dict[str, Any]) -> bool:
    """
    Señaliza si la animación/medio podría incluir “red flash”.
    Depende de flags opcionales del extractor: has_red_flash, red_dominant, hue_range, etc.
    """
    if _bool(n.get("has_red_flash")) or _bool(n.get("red_dominant")):
        return True
    hue = n.get("hue_range")  # e.g. (0..30) or “red”
    if isinstance(hue, str) and "red" in _lower(hue):
        return True
    return False

# -------------------------------------------------------------------
# Recolección de candidatos (RAW)
# -------------------------------------------------------------------

def _collect_candidates(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Agrupa posibles fuentes de “flashing”:
      - ctx.animations
      - ctx.videos (metadata: strobe_warning?, strobe_segments?)
      - imágenes GIF animadas (si el extractor expone meta)
      - hints por clases/nombres en widgets/componentes
    """
    out: List[Dict[str, Any]] = []

    for a in _as_list(getattr(ctx, "animations", [])):
        if not isinstance(a, dict):
            continue
        flashy, fps = _looks_flashy_animation(a)
        red = _red_risk(a)
        out.append({
            "kind": "animation",
            "selector": _s(a.get("selector") or a.get("id")),
            "label": _s(a.get("label") or a.get("aria-label")),
            "flashy": flashy,
            "est_flashes_per_sec": fps,
            "has_red_risk": red,
            "infinite": _lower(a.get("iteration_count")) in ("infinite","inf","-1") or False,
            "source": "animations"
        })

    for v in _as_list(getattr(ctx, "videos", [])):
        if not isinstance(v, dict):
            continue
        # Si el extractor marca “strobe_warning”, lo tratamos como aplicable de riesgo
        flashy = _bool(v.get("strobe_warning")) or _bool(v.get("has_strobe"))
        fps = None
        # Si aporta eventos detectados (timestamps de flashes), estima máximo por ventana de 1s
        evs = _as_list(v.get("flash_events"))
        if evs:
            try:
                # evs: lista de tiempos (s) donde se detectó flash
                evs_sorted = sorted([float(x) for x in evs if isinstance(x, (int, float, str))])
                # Ventana deslizante de 1s para hallar el máximo
                i = 0
                max_in_window = 0
                for j in range(len(evs_sorted)):
                    while evs_sorted[j] - evs_sorted[i] > 1.0:
                        i += 1
                    max_in_window = max(max_in_window, j - i + 1)
                fps = float(max_in_window)  # flashes/seg (máximo en alguna ventana)
                flashy = flashy or (fps > MAX_FLASHES_PER_SEC)
            except Exception:
                pass
        out.append({
            "kind": "video",
            "selector": _s(v.get("selector") or v.get("id") or v.get("src")),
            "label": _s(v.get("label") or v.get("aria-label") or v.get("title")),
            "flashy": flashy,
            "est_flashes_per_sec": fps,
            "has_red_risk": _red_risk(v) or _bool(v.get("red_flash_warning")),
            "source": "videos"
        })

    # GIFs animados (si el extractor provee listas/flags)
    for im in _as_list(getattr(ctx, "imgs", [])):
        if not isinstance(im, dict):
            # si el extractor dejó objetos soup, intenta leer atributos mínimos
            try:
                src = _lower(im.get("src")) if hasattr(im, "get") else ""
            except Exception:
                src = ""
            is_gif = src.endswith(".gif")
            meta = {}
        else:
            src = _lower(_s(im.get("src")))
            is_gif = src.endswith(".gif") or _bool(im.get("is_gif"))
            meta = im.get("gif_meta") or {}
        if is_gif:
            flashy, fps = _looks_flashy_gif(meta if isinstance(meta, dict) else {})
            out.append({
                "kind": "gif",
                "selector": src[:120],
                "label": _s(im.get("alt") if isinstance(im, dict) else ""),
                "flashy": flashy,                      # si no tenemos meta suficiente → False aquí; se puede elevar por hints
                "est_flashes_per_sec": fps,
                "has_red_risk": _red_risk(im if isinstance(im, dict) else {}),
                "source": "imgs"
            })

    # Hints por clases en widgets/componentes
    for coll in ("widgets","custom_components","banners","headers","sections","cards","panels"):
        for n in _as_list(getattr(ctx, coll, [])):
            if not isinstance(n, dict):
                continue
            if _candidate_from_class_hints(n):
                out.append({
                    "kind": "hint",
                    "selector": _s(n.get("selector") or n.get("id")),
                    "label": _s(n.get("label") or n.get("aria-label") or n.get("heading") or n.get("text")),
                    "flashy": True,          # heurístico por hint
                    "est_flashes_per_sec": None,
                    "has_red_risk": _red_risk(n),
                    "source": f"class_hint:{coll}"
                })

    return out

# -------------------------------------------------------------------
# Evaluación (RAW)
# -------------------------------------------------------------------

def _is_applicable(item: Dict[str, Any]) -> bool:
    """
    Aplica si hay indicios de flashing (flashy=True) o si se estiman >0 flashes/seg.
    """
    if item.get("flashy"):
        return True
    fps = item.get("est_flashes_per_sec")
    return isinstance(fps, (int, float)) and fps > 0.0

def _violates_threshold(item: Dict[str, Any]) -> bool:
    """
    Violación si:
      - est_flashes_per_sec > 3 en cualquier ventana de 1s (si tenemos dato), o
      - hay indicios claros de “strobe/flash” sin evidencia de estar ≤ 3/s (heurístico conservador), o
      - hay “red flash” marcado por el extractor (riesgo), aunque no midamos área (señalizamos violación/alto riesgo).
    """
    fps = item.get("est_flashes_per_sec")
    if isinstance(fps, (int, float)) and fps > MAX_FLASHES_PER_SEC:
        return True
    if item.get("has_red_risk"):
        return True
    # Si es “flashy” pero sin medición, marcamos como violación conservadora (puedes atenuar a “manual_required” si prefieres)
    return bool(item.get("flashy"))

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW: identifica candidatos de contenido que parpadea/destella. Marca violación si
    supera 3 destellos/seg (estimado) o si hay señales de “red flash” o “strobe”.
    """
    items = _collect_candidates(ctx)

    examined = len(items)
    applicable = 0
    violations = 0
    compliant = 0
    unknown = 0
    offenders: List[Dict[str, Any]] = []

    for it in items:
        if not _is_applicable(it):
            continue
        applicable += 1

        if _violates_threshold(it):
            violations += 1
            offenders.append({
                "kind": it.get("kind"),
                "selector": it.get("selector"),
                "label": it.get("label"),
                "est_flashes_per_sec": it.get("est_flashes_per_sec"),
                "has_red_risk": bool(it.get("has_red_risk")),
                "reason": "Sospecha/medición de >3 destellos/s y/o riesgo de 'red flash'."
            })
        else:
            compliant += 1

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, compliant / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "items_examined": examined,
        "applicable": applicable,
        "compliant": compliant,
        "violations": violations,
        "unknown": unknown,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 2.3.1 prohíbe más de 3 destellos en cualquier segundo y el 'red flash' por encima del umbral. "
            "Este check estima flashes/seg con metadatos disponibles y usa heurísticas (clases 'strobe/flash', duración muy corta, "
            "propiedades que alternan visibilidad/color). Si no hay medición, se marca conservadoramente como riesgo."
        )
    }
    return details

# -------------------------------------------------------------------
# RENDERED (prueba/medición en ejecución)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede aportar mediciones reales:
      rctx.flash_test = [
        {
          "selector": str,
          "max_flashes_per_1s": number,    # máximo contado en una ventana de 1s
          "has_red_flash": bool,           # si se detectó componente roja con flashes
          "area_over_threshold": bool,     # si el área de flash superó umbral (si se calcula)
          "notes": str
        }, ...
      ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.3.1; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    tests = _as_list(getattr(rctx, "flash_test", []))
    if not tests:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'flash_test'.").strip()
        return d

    applicable = 0
    compliant = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for t in tests:
        if not isinstance(t, dict):
            continue
        mps = t.get("max_flashes_per_1s")
        red = bool(t.get("has_red_flash"))
        area_over = bool(t.get("area_over_threshold"))

        # Aplica si hay flashes medidos (>0) o red flash reportado
        is_app = (isinstance(mps, (int, float)) and mps > 0.0) or red
        if not is_app:
            continue

        applicable += 1

        # Violación si >3/s o si se detectó red flash (y opcionalmente área>umbral)
        if (isinstance(mps, (int, float)) and float(mps) > MAX_FLASHES_PER_SEC) or red or area_over:
            violations += 1
            offenders.append({
                "selector": _s(t.get("selector")),
                "max_flashes_per_1s": float(mps) if isinstance(mps, (int, float)) else None,
                "has_red_flash": red,
                "area_over_threshold": area_over,
                "reason": "En ejecución: se detectó >3 destellos/s y/o 'red flash' por encima del umbral."
            })
        else:
            compliant += 1

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, compliant / max(1, applicable))), 4)

    d.update({
        "applicable": applicable,
        "compliant": compliant,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders + _as_list(d.get("offenders", [])),
        "note": (d.get("note","") + " | RENDERED: medición directa de destellos/seg y red flash.").strip()
    })
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: propone mitigaciones para reducir/eliminar flashing:
      - Reducir frecuencia (≤3/s) o aumentar duración de ciclo.
      - Sustituir destellos por transiciones suaves (fade/transform).
      - Evitar rojo dominante en flashes; bajar luminancia/contraste.
      - Ocultar animación no esencial por defecto; control de pausa.
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
        },
        "offenders": offs[:20],
        "html_snippet": (html_sample or "")[:2200],
    }
    prompt = (
        "Actúa como auditor WCAG 2.3.1 (Three Flashes or Below Threshold, A). "
        "Para cada offender, sugiere cómo reducir o eliminar los destellos: "
        "- Mantener ≤3 destellos por segundo; "
        "- Usar transiciones suaves en lugar de flashing; "
        "- Evitar 'red flash' (bajar luminancia/contraste o cambiar color); "
        "- Añadir controles para pausar/ocultar si no es esencial. "
        "Devuelve JSON: { suggestions: [{selector?, reason, css_fix?, js_fix?, design_alt?, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_2_3_1(
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

    # 3) Aplicabilidad / NA
    ensure_na_if_no_applicable(details, applicable_keys=("applicable",),
                               note_suffix="no se detectaron eventos de destello evaluables")

    # 4) passed / verdict / score
    passed = normalize_pass_for_applicable(details, violations_key="violations", applicable_keys=("applicable",))

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
        principle=meta.get("principle", "Operable"),
        title=meta.get("title", "Tres destellos o por debajo del umbral"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
