# audits/checks/criteria/p1/c_1_4_6_contrast_enhanced.py
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

CODE = "1.4.6"

# -------------------------
# Utilidades de color/contraste
# -------------------------

def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)

def _hex_to_rgb(value: str) -> Optional[Tuple[int, int, int]]:
    try:
        v = value.strip()
        if not v.startswith("#"):
            return None
        if len(v) == 4:  # #RGB
            r = int(v[1] * 2, 16)
            g = int(v[2] * 2, 16)
            b = int(v[3] * 2, 16)
            return (r, g, b)
        if len(v) == 7:  # #RRGGBB
            r = int(v[1:3], 16)
            g = int(v[3:5], 16)
            b = int(v[5:7], 16)
            return (r, g, b)
        # Soporte opcional #RGBA / #RRGGBBAA → ignoramos alpha
        if len(v) == 5:  # #RGBA
            r = int(v[1] * 2, 16)
            g = int(v[2] * 2, 16)
            b = int(v[3] * 2, 16)
            return (r, g, b)
        if len(v) == 9:  # #RRGGBBAA
            r = int(v[1:3], 16)
            g = int(v[3:5], 16)
            b = int(v[5:7], 16)
            return (r, g, b)
    except Exception:
        pass
    return None

_RGB_RE = re.compile(r"rgba?\(\s*([0-9\.%]+)\s*,\s*([0-9\.%]+)\s*,\s*([0-9\.%]+)\s*(?:,\s*([0-9\.]+)\s*)?\)", re.I)
_HSL_RE = re.compile(r"hsla?\(\s*([0-9\.]+)\s*,\s*([0-9\.%]+)\s*,\s*([0-9\.%]+)\s*(?:,\s*([0-9\.]+)\s*)?\)", re.I)

def _parse_rgb_num(tok: str) -> int:
    tok = tok.strip()
    if tok.endswith("%"):
        val = float(tok[:-1])
        return int(round(_clamp01(val / 100.0) * 255))
    return int(float(tok))

def _hsl_to_rgb(h: float, s: float, l: float) -> Tuple[int, int, int]:
    # h: 0–360, s/l: 0–1
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = l - c / 2
    rp = gp = bp = 0.0
    if   0 <= h < 60:   rp, gp, bp = c, x, 0
    elif 60 <= h < 120: rp, gp, bp = x, c, 0
    elif 120 <= h < 180:rp, gp, bp = 0, c, x
    elif 180 <= h < 240:rp, gp, bp = 0, x, c
    elif 240 <= h < 300:rp, gp, bp = x, 0, c
    else:               rp, gp, bp = c, 0, x
    r = int(round((rp + m) * 255))
    g = int(round((gp + m) * 255))
    b = int(round((bp + m) * 255))
    return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))

def _parse_css_color(s: Optional[str]) -> Optional[Tuple[int, int, int, float]]:
    """
    Devuelve RGBA (0-255, 0-1 alpha). Si no se puede parsear, None.
    """
    if not s:
        return None
    v = s.strip().lower()
    if v == "transparent":
        return (0, 0, 0, 0.0)
    rgb = _hex_to_rgb(v)
    if rgb:
        return (rgb[0], rgb[1], rgb[2], 1.0)
    m = _RGB_RE.match(v)
    if m:
        r = _parse_rgb_num(m.group(1))
        g = _parse_rgb_num(m.group(2))
        b = _parse_rgb_num(m.group(3))
        a = float(m.group(4)) if m.group(4) is not None else 1.0
        return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)), _clamp01(a))
    m2 = _HSL_RE.match(v)
    if m2:
        h_str = m2.group(1) or "0"
        s_str = m2.group(2) or "0%"
        l_str = m2.group(3) or "0%"
        a_str = m2.group(4)
        h = float(h_str) % 360.0
        sat = float(s_str.strip("%")) / 100.0
        lum = float(l_str.strip("%")) / 100.0
        alpha = float(a_str) if a_str is not None else 1.0
        r, g, b = _hsl_to_rgb(h, sat, lum)
        return (r, g, b, _clamp01(alpha))
    return None

def _alpha_composite_over(bg_rgb: Tuple[int, int, int], fg_rgba: Tuple[int, int, int, float]) -> Tuple[int, int, int]:
    """
    Compone FG (con alpha) sobre BG (opaco). Devuelve RGB opaco resultante.
    """
    fr, fg, fb, fa = fg_rgba
    if fa >= 1.0:
        return (fr, fg, fb)
    br, bgc, bb = bg_rgb
    r = int(round(fr * fa + br * (1 - fa)))
    g = int(round(fg * fa + bgc * (1 - fa)))
    b = int(round(fb * fa + bb * (1 - fa)))
    return (r, g, b)

def _srgb_to_linear(c: float) -> float:
    # c llega 0–255 → normalizamos a 0–1 y aplicamos curva sRGB correcta
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def _rel_luminance(rgb: Tuple[int, int, int]) -> float:
    r, g, b = rgb
    rl = 0.2126 * _srgb_to_linear(r) + 0.7152 * _srgb_to_linear(g) + 0.0722 * _srgb_to_linear(b)
    return rl

def _contrast_ratio(rgb1: Tuple[int, int, int], rgb2: Tuple[int, int, int]) -> float:
    l1 = _rel_luminance(rgb1)
    l2 = _rel_luminance(rgb2)
    L1, L2 = (max(l1, l2), min(l1, l2))
    return (L1 + 0.05) / (L2 + 0.05)

# -------------------------
# Utilidades de extracción
# -------------------------

def _as_list(x):
    if not x:
        return []
    if isinstance(x, list):
        return x
    return list(x)

def _bool(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")

def _font_is_bold(item: Dict[str, Any]) -> bool:
    if _bool(item.get("is_bold")):
        return True
    fw = item.get("font_weight") or item.get("font-weight") or item.get("computed_font_weight")
    try:
        if isinstance(fw, str) and fw.strip().isdigit():
            return int(fw.strip()) >= 600
        if isinstance(fw, (int, float)):
            return int(fw) >= 600
        if isinstance(fw, str):
            return fw.strip().lower() in {"bold", "bolder", "semibold", "600", "700", "800", "900"}
    except Exception:
        pass
    return False

def _is_large_text(item: Dict[str, Any]) -> bool:
    """
    WCAG 'large scale':
      - >= 24px normal, o
      - >= 18.66px (≈14pt) si es bold
    """
    fs = item.get("font_size") or item.get("font-size") or item.get("computed_font_size")
    size_px = None
    if isinstance(fs, (int, float)):
        size_px = float(fs)
    elif isinstance(fs, str):
        m = re.match(r"([0-9\.]+)\s*px", fs.strip(), re.I)
        if m:
            size_px = float(m.group(1))
        else:
            m2 = re.match(r"([0-9\.]+)\s*(rem|em)", fs.strip(), re.I)
            if m2:
                size_px = float(m2.group(1)) * 16.0
    if size_px is None:
        return False
    if size_px >= 24.0:
        return True
    if size_px >= 18.66 and _font_is_bold(item):
        return True
    return False

def _is_exempt_text(item: Dict[str, Any]) -> bool:
    """
    Excepciones 1.4.6 (iguales que 1.4.3):
      - inactivo/disabled
      - decorativo/incidental
      - logotipos (is_logo)
    """
    if _bool(item.get("disabled")) or _bool(item.get("aria-disabled")) or _bool(item.get("is_disabled")):
        return True
    if _bool(item.get("is_decorative")) or _bool(item.get("decorative")) or _bool(item.get("incidental")):
        return True
    if _bool(item.get("is_logo")) or _bool(item.get("logo")):
        return True
    col = _parse_css_color(item.get("color") or item.get("computed_color") or item.get("fg_color"))
    if col and col[3] == 0.0:
        return True
    return False

def _extract_colors(item: Dict[str, Any]) -> Tuple[Optional[Tuple[int,int,int]], Optional[Tuple[int,int,int]], Dict[str, Any]]:
    """
    Devuelve (text_rgb, bg_rgb, meta). Si falta alguno, será None.
    """
    meta: Dict[str, Any] = {}
    col_rgba = (
        _parse_css_color(item.get("computed_color"))
        or _parse_css_color(item.get("color"))
        or _parse_css_color(item.get("style_color"))
        or _parse_css_color(item.get("fg_color"))
    )
    bg_rgba = (
        _parse_css_color(item.get("computed_background_color"))
        or _parse_css_color(item.get("background_color"))
        or _parse_css_color(item.get("style_background_color"))
        or _parse_css_color(item.get("bg_color"))
    )
    eff_bg = _parse_css_color(item.get("effective_bg_color"))
    if eff_bg:
        bg_rgba = eff_bg

    text_rgb: Optional[Tuple[int,int,int]] = None
    bg_rgb: Optional[Tuple[int,int,int]] = None

    if col_rgba:
        if col_rgba[3] < 1.0 and bg_rgba:
            text_rgb = _alpha_composite_over((bg_rgba[0], bg_rgba[1], bg_rgba[2]), col_rgba)
            meta["alpha_composited"] = True
        else:
            text_rgb = (col_rgba[0], col_rgba[1], col_rgba[2])

    if bg_rgba:
        bg_rgb = (bg_rgba[0], bg_rgba[1], bg_rgba[2])

    meta["raw_fg"] = item.get("computed_color") or item.get("color") or item.get("style_color") or item.get("fg_color")
    meta["raw_bg"] = item.get("computed_background_color") or item.get("background_color") or item.get("style_background_color") or item.get("bg_color") or item.get("effective_bg_color")
    return text_rgb, bg_rgb, meta

def _collect_text_candidates(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Candidatos con texto visible:
      text_nodes, headings, paragraphs, buttons, links, labels, form_controls
    """
    out: List[Dict[str, Any]] = []
    for src in ("text_nodes","headings","paragraphs","buttons","links","labels","form_controls"):
        for n in _as_list(getattr(ctx, src, [])):
            item = dict(n) if isinstance(n, dict) else {}
            item["__source"] = src
            if not item.get("text"):
                for k in ("inner_text","label_text","value","aria-label","title","placeholder"):
                    v = item.get(k)
                    if v:
                        item["text"] = v
                        break
            txt = (str(item.get("text") or "")).strip()
            if not txt:
                continue
            out.append(item)
    return out

# -------------------------
# Núcleo del criterio
# -------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW: mide contraste para texto e imágenes de texto (si se marcan).
    Requisitos 1.4.6 (AAA):
      - Texto normal: ≥ 7:1
      - Texto grande (o bold ≥14pt≈18.66px): ≥ 4.5:1
    Excepciones: inactivo, decorativo/incidental, logotipos.
    """
    items = _collect_text_candidates(ctx)
    imgs = _as_list(getattr(ctx, "imgs", []))

    total_text = 0
    checked = 0
    large_checked = 0
    fails_small = 0
    fails_large = 0
    unknown_colors = 0
    exemptions = 0

    offenders: List[Dict[str, Any]] = []

    # Texto en elementos
    for it in items:
        txt = (str(it.get("text") or "")).strip()
        if not txt:
            continue
        total_text += 1

        if _is_exempt_text(it):
            exemptions += 1
            continue

        fg, bg, meta = _extract_colors(it)
        if not fg or not bg:
            unknown_colors += 1
            offenders.append({
                "type": "text",
                "source": it.get("__source"),
                "snippet": txt[:120],
                "reason": "Colores desconocidos (no se pudo medir contraste).",
                "meta": meta
            })
            continue

        ratio = _contrast_ratio(fg, bg)
        is_large = _is_large_text(it)
        # AAA thresholds
        req = 4.5 if is_large else 7.0

        checked += 1
        if is_large:
            large_checked += 1

        if ratio + 1e-9 < req:
            if is_large:
                fails_large += 1
            else:
                fails_small += 1
            offenders.append({
                "type": "text",
                "source": it.get("__source"),
                "snippet": txt[:120],
                "ratio": round(ratio, 2),
                "required": req,
                "fg": fg, "bg": bg,
                "meta": meta,
                "font_size": it.get("font_size") or it.get("computed_font_size"),
                "font_weight": it.get("font_weight") or it.get("computed_font_weight"),
                "reason": "Contraste insuficiente (AAA)."
            })

    # Imágenes de texto señaladas (sin medición automática a menos que aportes colores)
    image_text_flags = 0
    for im in imgs:
        flag = None
        if isinstance(im, dict):
            flag = im.get("is_image_of_text") or im.get("image_of_text")
        else:
            flag = None
        if not flag:
            continue
        image_text_flags += 1
        offenders.append({
            "type": "image_of_text",
            "src": str((im.get("src") if isinstance(im, dict) else ""))[:180],
            "reason": "Imagen de texto detectada (1.4.6 aplica AAA). Requiere contraste ≥7:1 (o 4.5:1 si grande)."
        })

    violations = fails_small + fails_large
    denom = max(1, checked)
    ok_ratio = round(max(0.0, min(1.0, (checked - violations) / denom)), 4)

    details: Dict[str, Any] = {
        "text_nodes_total": total_text,
        "checked": checked,
        "large_checked": large_checked,
        "fails_small_text": fails_small,
        "fails_large_text": fails_large,
        "unknown_colors": unknown_colors,
        "exemptions": exemptions,
        "image_of_text_flags": image_text_flags,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 1.4.6 (AAA) exige ≥7:1 para texto normal y ≥4.5:1 para texto grande/bold (≥14pt≈18.66px). "
            "Se excluyen componentes inactivos, decorativos/incidental y logotipos. "
            "Las imágenes de texto, si existen, deben cumplir los mismos umbrales."
        )
    }
    return details

# -------------------------
# Rendered
# -------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    Con DOM post-render (Playwright) puedes aportar:
      - computed_color / effective_bg_color reales
      - font-size/weight reales
      - bounding boxes/visibilidad
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.4.6; no se pudo evaluar en modo renderizado."}
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note","") + " | RENDERED: estilos computados usados para medir contraste real (AAA).").strip()
    return d

# -------------------------
# IA opcional
# -------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: propone ajustes de color para alcanzar 7:1 (o 4.5:1 si large).
    Sugerencias:
      - Oscurecer texto o aclarar fondo (o viceversa).
      - Tokens/variables de tema con paletas AAA.
      - Overlays si hay imagen/gradiente bajo el texto.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    offs = [o for o in details.get("offenders", []) if o.get("reason") == "Contraste insuficiente (AAA)."]
    if not offs:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "offenders": offs[:20],
        "summary": {
            "fails_small_text": details.get("fails_small_text", 0),
            "fails_large_text": details.get("fails_large_text", 0),
        },
        "html_snippet": (html_sample or "")[:2500]
    }
    prompt = (
        "Actúa como auditor WCAG 1.4.6 (Contrast enhanced, AAA). "
        "Para cada offender con 'fg' y 'bg', sugiere cambios (CSS) para cumplir AAA (7:1 / 4.5:1 si large). "
        "Devuelve JSON: { suggestions: [{snippet, ratio, required, css_fix?, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------
# Orquestación
# -------------------------

def run_1_4_6(
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
    violations = (details.get("fails_small_text", 0) or 0) + (details.get("fails_large_text", 0) or 0)
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
        title=meta.get("title", "Contraste (mejorado)"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required or (details.get("unknown_colors", 0) > 0)
    )
