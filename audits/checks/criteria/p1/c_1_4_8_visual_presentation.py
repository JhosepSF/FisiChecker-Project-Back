# audits/checks/criteria/p1/c_1_4_8_visual_presentation.py
from typing import Dict, Any, List, Optional, Tuple
import re
import math

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  # si no existe, el modo IA queda deshabilitado

CODE = "1.4.8"

# -------------------------------------------------------------------
# Utilidades
# -------------------------------------------------------------------

def _as_list(x):
    if not x:
        return []
    if isinstance(x, list):
        return x
    return list(x)

def _bool(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")

def _lang_is_cjk(lang: Optional[str]) -> bool:
    if not lang:
        return False
    l = str(lang).lower()
    return l.startswith(("zh", "ja", "ko"))

_FONT_SIZE_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(px|pt|em|rem|%)\s*$", re.I)

def _font_px(fs: Any) -> Optional[float]:
    """Convierte font-size a px si es posible (admite '16px', '1rem', '1.25em', número → px). Asume 1rem/em=16px."""
    if fs is None:
        return None
    if isinstance(fs, (int, float)):
        return float(fs)
    s = str(fs).strip().lower()
    m = _FONT_SIZE_RE.match(s)
    if not m:
        # valores tipo 'medium', 'large' → desconocido
        return None
    val = float(m.group(1))
    unit = m.group(2)
    if unit == "px":
        return val
    if unit == "pt":
        # 1pt ≈ 1.333px
        return val * 96.0 / 72.0
    if unit in ("em", "rem"):
        return val * 16.0
    if unit == "%":
        # % relativo al tamaño base (100% = 16px aprox si base 16)
        return (val / 100.0) * 16.0
    return None

def _line_height_ratio(line_height: Any, font_size: Any) -> Optional[float]:
    """
    Calcula ratio line-height / font-size:
      - si line-height es unitless → ya es ratio
      - si viene en px → px/px
      - 'normal' → None (desconocido)
    """
    if line_height is None:
        return None
    # unitless (e.g., 1.5)
    if isinstance(line_height, (int, float)):
        if font_size is None:
            return float(line_height)
        return float(line_height)
    s = str(line_height).strip().lower()
    if s == "normal":
        return None
    # px/em/rem/%
    m = _FONT_SIZE_RE.match(s)
    if m:
        lh_val = float(m.group(1))
        unit = m.group(2)
        if unit == "px":
            fs_px = _font_px(font_size) or 16.0
            return (lh_val / fs_px) if fs_px > 0 else None
        if unit in ("em","rem"):
            return lh_val  # ya es múltiplo del font-size base
        if unit == "pt":
            # pasa pt a px, y divide por font-size(px)
            lh_px = lh_val * 96.0 / 72.0
            fs_px = _font_px(font_size) or 16.0
            return (lh_px / fs_px) if fs_px > 0 else None
        if unit == "%":
            return (lh_val / 100.0)
    # desconocido
    return None

def _paragraph_spacing_ratio(margin_block_end: Any, line_height: Any, font_size: Any) -> Optional[float]:
    """
    Aproxima separación entre párrafos como margin-bottom / line-height.
    Si margin viene en px, conviértelo. Si viene unitless, tómalo como múltiplo de font-size.
    """
    if margin_block_end is None:
        return None
    # px numérico
    if isinstance(margin_block_end, (int, float)):
        fs_px = _font_px(font_size) or 16.0
        lh_r = _line_height_ratio(line_height, font_size) or 1.0
        lh_px = lh_r * fs_px
        return float(margin_block_end) / lh_px if lh_px > 0 else None
    s = str(margin_block_end).strip().lower()
    # px/pt/em/rem/%
    m = _FONT_SIZE_RE.match(s)
    if m:
        val = float(m.group(1))
        unit = m.group(2)
        if unit == "px":
            fs_px = _font_px(font_size) or 16.0
            lh_r = _line_height_ratio(line_height, font_size) or 1.0
            lh_px = lh_r * fs_px
            return val / lh_px if lh_px > 0 else None
        if unit in ("em","rem"):
            # em/rem multiplican el font-size base → calc contra line-height
            fs_px = _font_px(font_size) or 16.0
            val_px = val * (16.0 if unit == "rem" else fs_px)
            lh_r = _line_height_ratio(line_height, font_size) or 1.0
            lh_px = lh_r * fs_px
            return val_px / lh_px if lh_px > 0 else None
        if unit == "pt":
            val_px = val * 96.0 / 72.0
            fs_px = _font_px(font_size) or 16.0
            lh_r = _line_height_ratio(line_height, font_size) or 1.0
            lh_px = lh_r * fs_px
            return val_px / lh_px if lh_px > 0 else None
        if unit == "%":
            # % del font-size → convertir a px, luego ratio con line-height px
            fs_px = _font_px(font_size) or 16.0
            val_px = (val / 100.0) * fs_px
            lh_r = _line_height_ratio(line_height, font_size) or 1.0
            lh_px = lh_r * fs_px
            return val_px / lh_px if lh_px > 0 else None
    # desconocido
    return None

def _has_text_align_justify(item: Dict[str, Any]) -> bool:
    ta = (item.get("text_align") or item.get("text-align") or item.get("computed_text_align") or "").strip().lower()
    return ta == "justify"

def _max_line_chars(item: Dict[str, Any]) -> Optional[float]:
    """
    Estimación del ancho de línea en caracteres (si extractor lo suministra).
    Acepta:
      - item['max_line_chars'] o 'avg_chars_per_line'
      - item['max_width_ch'] (CSS con 'ch')
    """
    for k in ("max_line_chars","avg_chars_per_line","max_width_ch","measure_ch"):
        v = item.get(k)
        if isinstance(v, (int, float)):
            return float(v)
        try:
            # si viene como '65ch'
            s = str(v).strip().lower()
            m = re.match(r"([0-9\.]+)\s*ch", s)
            if m:
                return float(m.group(1))
        except Exception:
            pass
    return None

def _has_user_color_controls(ctx: PageContext) -> bool:
    """
    Heurística: existe 'mecanismo' para elegir colores de FG/BG.
    Acepta flags del extractor (cualquiera true):
      - has_theme_switcher, has_contrast_toggle, user_color_controls, color_customization,
        style_switcher, reader_mode_available, prefers_color_scheme_supported, high_contrast_mode
    """
    keys = (
        "has_theme_switcher","has_contrast_toggle","user_color_controls","color_customization",
        "style_switcher","reader_mode_available","prefers_color_scheme_supported","high_contrast_mode"
    )
    for k in keys:
        if _bool(getattr(ctx, k, False)) or _bool(getattr(ctx, "features", {}).get(k) if isinstance(getattr(ctx, "features", None), dict) else False):
            return True
    return False

# -------------------------------------------------------------------
# Núcleo del criterio
# -------------------------------------------------------------------

def _collect_text_blocks(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Bloques de texto: paragraphs, articles/sections (si provees), rich-text containers, etc.
    También tomamos 'text_nodes' largos como aproximación.
    Cada item útil idealmente aporta:
      text, lang?, computed_text_align, computed_line_height, computed_font_size, margin_bottom,
      max_line_chars o max_width_ch/measure_ch, etc.
    """
    blocks: List[Dict[str, Any]] = []
    for src in ("paragraphs","articles","sections","text_blocks","text_nodes"):
        for n in _as_list(getattr(ctx, src, [])):
            item = dict(n) if isinstance(n, dict) else {}
            txt = str(item.get("text") or item.get("inner_text") or "").strip()
            if not txt:
                continue
            # filtra textos muy cortos (no “bloques”)
            if len(txt) < 40 and src != "paragraphs":
                continue
            item["__source"] = src
            blocks.append(item)
    return blocks

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    1.4.8 (AAA) – Para la presentación visual de bloques de texto, debe existir un MECANISMO para:
      (a) que el usuario elija colores FG/BG;
      (b) ancho de línea ≤ 80 caracteres (o ≤ 40 en CJK);
      (c) texto no justificado (no 'text-align: justify');
      (d) interlineado ≥ 1.5 y separación entre párrafos ≥ 1.5 × interlineado;
      (e) redimensionar hasta 200% sin scroll horizontal.
    RAW: heurístico basado en estilos/flags disponibles en el extractor.
    """
    lang = getattr(ctx, "lang", "") or ""
    cjk = _lang_is_cjk(lang)

    blocks = _collect_text_blocks(ctx)
    total_blocks = len(blocks)

    if total_blocks == 0:
        details = {
            "lang_cjk": bool(cjk),
            "total_blocks": 0,
            # (a) mecanismo de color (informativo; no cambia el NA)
            "has_color_mechanism": bool(_has_user_color_controls(ctx)),
            # (b)
            "width_checked": 0,
            "width_ok": 0,
            "width_unknown": 0,
            "max_chars_allowed": 40.0 if cjk else 80.0,
            # (c)
            "justify_blocks": 0,
            # (d)
            "lineheight_checked": 0,
            "lineheight_ok": 0,
            "lineheight_unknown": 0,
            "paragraph_spacing_ok": True,        # irrelevante en NA
            "paragraph_spacing_unknown": 0,
            # (e)
            "zoom200_ok": None,
            "offenders": [],
            "ok_ratio": None,                    # evita confundir con 1.0
            "na": True,
            "note": (
                "RAW: 1.4.8 aplica a la presentación de bloques de texto. "
                "NA: no se detectaron bloques de texto (párrafos/sections/etc.) para evaluar."
            )
        }
        return details

    # (a) mecanismo de color
    has_color_mechanism = _has_user_color_controls(ctx)

    # (b) ancho de línea
    width_checked = 0
    width_ok = 0
    width_unknown = 0
    width_offenders: List[Dict[str, Any]] = []

    max_chars_allowed = 40.0 if cjk else 80.0

    for b in blocks:
        mlc = _max_line_chars(b)
        if mlc is None:
            width_unknown += 1
            continue
        width_checked += 1
        if mlc <= max_chars_allowed + 1e-6:
            width_ok += 1
        else:
            width_offenders.append({
                "type": "width",
                "source": b.get("__source"),
                "snippet": str(b.get("text",""))[:120],
                "max_line_chars": mlc,
                "allowed": max_chars_allowed,
                "reason": "Ancho de línea excede el límite (80; 40 para CJK)."
            })

    # (c) no justificado
    justify_checked = 0
    justified = 0
    for b in blocks:
        ja = _has_text_align_justify(b)
        if ja:
            justified += 1
        justify_checked += 1  # asumimos comprobable si aporta computed_text_align o flag (si no, igual contamos para riesgo)

    # (d) interlineado y separación de párrafos
    lh_checked = 0
    lh_ok = 0
    para_spacing_ok = 0
    lh_unknown = 0
    spacing_unknown = 0
    spacing_offenders: List[Dict[str, Any]] = []

    for b in blocks:
        lh = _line_height_ratio(b.get("computed_line_height") or b.get("line_height"), b.get("computed_font_size") or b.get("font_size"))
        if lh is None:
            lh_unknown += 1
        else:
            lh_checked += 1
            if lh >= 1.5 - 1e-6:
                lh_ok += 1
            else:
                spacing_offenders.append({
                    "type": "line_height",
                    "source": b.get("__source"),
                    "snippet": str(b.get("text",""))[:120],
                    "line_height_ratio": round(lh, 2),
                    "required": 1.5,
                    "reason": "Interlineado < 1.5."
                })

        pr = _paragraph_spacing_ratio(
            b.get("margin_bottom") or b.get("computed_margin_bottom") or b.get("paragraph_spacing"),
            b.get("computed_line_height") or b.get("line_height"),
            b.get("computed_font_size") or b.get("font_size")
        )
        if pr is None:
            spacing_unknown += 1
        else:
            if pr >= 1.5 - 1e-6:
                para_spacing_ok += 1
            else:
                spacing_offenders.append({
                    "type": "paragraph_spacing",
                    "source": b.get("__source"),
                    "snippet": str(b.get("text",""))[:120],
                    "paragraph_spacing_ratio": round(pr, 2),
                    "required": 1.5,
                    "reason": "Separación entre párrafos < 1.5 × interlineado."
                })

    # (e) 200% sin scroll horizontal (conexión con 1.4.4/1.4.10)
    # En RAW solo podemos marcar riesgo si el meta viewport bloquea zoom (ya lo hace 1.4.4),
    # aquí lo resumimos como 'unknown' salvo que el extractor aporte 'zoom200_ok'.
    zoom200_ok = None
    if isinstance(getattr(ctx, "zoom_test", None), dict):
        zt = getattr(ctx, "zoom_test")
        zoom200_ok = (not bool(zt.get("horizontal_scroll"))) and (not bool(zt.get("loss_of_functionality"))) and (int(zt.get("hidden_controls") or 0) == 0)

    # Heurística de “cumplimiento”: para 1.4.8 se pide un MECANISMO para lograr (a–e).
    # Consideramos PASS si:
    #  - (a) hay mecanismo de color (o todos los bloques ya cumplen contraste y usuario no lo necesita → imposible de inferir, así que pedimos mecanismo)
    #  - (b) la mayoría de bloques cumplen ancho (o tenemos mecanismo de lectura/reader_mode)
    #  - (c) no detectamos 'justify' en bloques (o hay mecanismo reader_mode)
    #  - (d) interlineado y separación cumplen en la mayoría (o hay mecanismo reader_mode/ajustes tipográficos)
    #  - (e) zoom200_ok True si se aportó; si None, no lo penalizamos en RAW

    reader_like = _bool(getattr(ctx, "reader_mode_available", False)) or _bool(getattr(ctx, "typography_controls", False))

    # Conteos para “mayoría”
    width_majority_ok = (width_checked == 0) or (width_ok / max(1, width_checked) >= 0.7)
    justify_ok = (justified == 0)  # ningún bloque con justify
    line_ok = (lh_checked == 0) or (lh_ok / max(1, lh_checked) >= 0.7)
    para_ok = (para_spacing_ok / max(1, (lh_checked or 1))) >= 0.7 if lh_checked else True

    # Violaciones duras (si se puede afirmar algo)
    violations = 0
    offenders = []
    if not has_color_mechanism and not reader_like:
        # No podemos verificar la necesidad real del usuario; WCAG pide mecanismo → señalamos riesgo/violación leve.
        offenders.append({"type": "mechanism", "reason": "No se detecta mecanismo para que el usuario elija colores FG/BG."})
    if not width_majority_ok and not reader_like:
        violations += 1
        offenders += width_offenders
    if justified > 0 and not reader_like:
        violations += 1
        offenders.append({"type": "justify", "count": justified, "reason": "Se detecta 'text-align: justify' en bloques de texto."})
    if (not line_ok or not para_ok) and not reader_like:
        violations += 1
        offenders += spacing_offenders
    if zoom200_ok is False:
        violations += 1
        offenders.append({"type": "zoom200", "reason": "A 200% hay scroll horizontal o pérdida de funcionalidad."})

    denom_for_ok = max(1, total_blocks)
    ok_ratio = round(max(0.0, min(1.0,
        (denom_for_ok - (justified > 0) - len(width_offenders) - len([o for o in spacing_offenders if o.get('type')=='line_height']) - len([o for o in spacing_offenders if o.get('type')=='paragraph_spacing'])) / denom_for_ok
    )), 4)

    details: Dict[str, Any] = {
        "lang_cjk": bool(cjk),
        "total_blocks": total_blocks,
        # (a)
        "has_color_mechanism": bool(has_color_mechanism or reader_like),
        # (b)
        "width_checked": width_checked,
        "width_ok": width_ok,
        "width_unknown": width_unknown,
        "max_chars_allowed": max_chars_allowed,
        # (c)
        "justify_blocks": justified,
        # (d)
        "lineheight_checked": lh_checked,
        "lineheight_ok": lh_ok,
        "lineheight_unknown": lh_unknown,
        "paragraph_spacing_ok": para_ok,
        "paragraph_spacing_unknown": spacing_unknown,
        # (e)
        "zoom200_ok": zoom200_ok,  # True/False/None
        "offenders": offenders,
        "ok_ratio": ok_ratio,
        "note": (
            "RAW: 1.4.8 requiere un mecanismo para (a) elegir colores FG/BG; (b) limitar ancho de línea (≤80, ≤40 CJK); "
            "(c) evitar justificado; (d) interlineado ≥1.5 y espaciado entre párrafos ≥1.5×; (e) 200% sin scroll horizontal. "
            "Se usan heurísticas de estilo y flags del extractor; la verificación más fiable de (e) se hace en RENDERED."
        )
    }
    return details

# -------------------------------------------------------------------
# Rendered
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED (Playwright) puedes aportar, por bloque de texto:
      text_block_stats=[{
        text, lang, max_line_chars, avg_chars_per_line, computed_text_align,
        line_height, font_size, margin_bottom, paragraph_spacing_ratio
      }, ...]
    Y un 'zoom_test' (200%).
    Este método reutiliza RAW sobre rctx y confía en métricas reales para (b–e).
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.4.8; no se pudo evaluar en modo renderizado."}
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    
    if d.get("na") is True:
        d["note"] = (d.get("note","") + " | RENDERED: sin bloques de texto igualmente (NA).").strip()
        return d

    d["note"] = (d.get("note","") + " | RENDERED: se usaron métricas reales de 'text_block_stats' y 'zoom_test' si estaban disponibles.").strip()
    return d
    
# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: propone un 'modo lectura' y ajustes tipográficos:
      - Añadir selector de tema y controles de color FG/BG (y respetar prefers-color-scheme).
      - Limitar medida de texto (max-width: 65–80ch; 35–40ch para CJK).
      - Evitar text-align: justify.
      - line-height: 1.5; p + p { margin-top: calc(1.5 * 1em); }
      - Garantizar 200% sin scroll horizontal (layout responsive, sin alturas fijas).
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    offs = details.get("offenders", []) or []
    # Si no hay offenders pero falta mecanismo de color, igualmente sugerimos
    if not offs and details.get("has_color_mechanism", True):
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "width_ok": details.get("width_ok", 0),
            "width_checked": details.get("width_checked", 0),
            "justify_blocks": details.get("justify_blocks", 0),
            "lineheight_ok": details.get("lineheight_ok", 0),
            "lineheight_checked": details.get("lineheight_checked", 0),
            "zoom200_ok": details.get("zoom200_ok", None),
            "has_color_mechanism": details.get("has_color_mechanism", False),
        },
        "offenders": offs[:20],
        "html_snippet": (html_sample or "")[:2400],
    }
    prompt = (
        "Actúa como auditor WCAG 1.4.8 (Visual Presentation, AAA). "
        "Propón un 'modo lectura' y reglas CSS para cumplir: "
        "a) selector de colores FG/BG y modo alto contraste; "
        "b) max-width: 65–80ch (35–40ch CJK); "
        "c) evitar text-align: justify; "
        "d) line-height: 1.5, separación párrafos ≥ 1.5×; "
        "e) reflow sin scroll horizontal al 200%. "
        "Devuelve JSON: { suggestions: [{type, reason, css_fix?, html_fix?, ux_fix?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_1_4_8(
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

    # ➜ NA si no hay bloques de texto aplicables o si ya viene marcado
    is_na = bool(details.get("na")) or int(details.get("total_blocks", 0) or 0) == 0
    if is_na:
        details["na"] = True
        # El 'passed' es irrelevante para NA; 'verdict_from_counts' debe respetar 'na'
        verdict = verdict_from_counts(details, True)
        score0 = score_from_verdict(verdict)

        meta = WCAG_META.get(CODE, {})
        return CriterionOutcome(
            code=CODE,
            passed=False,  # no se usa cuando es NA
            verdict=verdict,
            score_0_2=score0,
            details=details,
            level=meta.get("level", "AAA"),
            principle=meta.get("principle", "Perceptible"),
            title=meta.get("title", "Presentación visual"),
            source=src,
            score_hint=details.get("ok_ratio"),
            manual_required=manual_required
        )

    # 3) passed / verdict / score (solo si aplica)
    # Consideramos 'falla' cuando hay evidencia clara: justify, ancho muy largo sin mecanismo,
    # interlineado/espaciado insuficiente y/o zoom200_ok=False.
    hard = 0
    if any(o.get("type") in {"width", "line_height", "paragraph_spacing", "justify", "zoom200"}
           for o in details.get("offenders", [])):
        hard = 1
    passed = (hard == 0)

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
        title=meta.get("title", "Presentación visual"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required or (details.get("width_unknown", 0) > 0)
    )
