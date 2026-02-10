# audits/checks/criteria/p1/c_1_4_9_images_of_text_no_exception.py
from typing import Dict, Any, List, Optional
import re
import os

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  # si no existe, el modo IA queda deshabilitado

CODE = "1.4.9"

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

def _classes_str(el: Any) -> str:
    v = None
    if isinstance(el, dict):
        v = el.get("class")
    else:
        try:
            v = el.get("class") if hasattr(el, "get") else getattr(el, "get_attribute", lambda *_: None)("class")
        except Exception:
            v = None
    if v is None:
        return ""
    if isinstance(v, (list, tuple, set)):
        return " ".join(str(x) for x in v if x is not None).lower()
    return str(v).lower()

def _filename(path: str) -> str:
    try:
        return os.path.basename(path.split("?")[0].split("#")[0])
    except Exception:
        return path

# Heurísticos livianos para “parece imagen de texto”
_FILENAME_TEXT_HINTS = re.compile(r"(btn|button|cta|banner|headline|title|heading|texto|text|copy|promo)", re.I)
_CLASS_TEXT_HINTS = re.compile(r"(btn|button|cta|headline|title|heading|tagline|banner|promo|sprite)", re.I)

def _looks_like_image_of_text(el: Any) -> bool:
    """
    Señales heurísticas, solo marcan RIESGO si el extractor no trae flags:
      - nombre de archivo sugiere botón/banner/título
      - clases con hints de botón/título/banner
      - 'alt' corto repetido y el archivo parece decorativo de texto
    """
    src = _get_attr_str(el, "src") or _get_attr_str(el, "data-src") or _get_attr_str(el, "data-url")
    cls = _classes_str(el)
    alt = (_get_attr_str(el, "alt") or "").strip()
    fn = _filename(src).lower()

    if _FILENAME_TEXT_HINTS.search(fn):
        return True
    if _CLASS_TEXT_HINTS.search(cls):
        return True
    if alt and len(alt.split()) <= 3 and ("text" in fn or "title" in fn or "btn" in fn):
        return True
    return False

def _is_logo_like(el: Any) -> bool:
    """
    ÚNICA excepción en 1.4.9: logotipos.
    Acepta flags del extractor o hints (clases/alt/src).
    """
    if isinstance(el, dict) and (_bool(el.get("is_logo")) or _bool(el.get("logo"))):
        return True
    alt = (_get_attr_str(el, "alt") or "").lower()
    cls = _classes_str(el)
    src = (_get_attr_str(el, "src") or "").lower()
    return any(w in (alt + " " + cls + " " + src) for w in ("logo", "logotipo", "brand", "marca"))

# -------------------------
# Núcleo del criterio
# -------------------------

def _collect_img_candidates(ctx: PageContext) -> List[Any]:
    """
    Candidatos primarios: <img>. Secundarios (opcional si el extractor los provee):
      - bg_images: CSS background-image con flags ({url, is_image_of_text, ...})
      - canvas_nodes: <canvas> con drawText detectado (canvas_has_text)
      - svgs: inline <svg> (si trae <text> no es imagen de texto)
    """
    return _as_list(getattr(ctx, "imgs", []))

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    1.4.9 (AAA): No usar IMÁGENES DE TEXTO. Única excepción: logotipos.
    RAW:
      - usa flags del extractor: is_image_of_text / ocr_text_present / detected_text_area_ratio
      - heurísticos suaves (filename/clases/alt) para marcar RIESGOS (revisión manual)
      - considera bg_images/canvas_nodes si están en el contexto
    """
    imgs = _collect_img_candidates(ctx)
    bg_images = _as_list(getattr(ctx, "bg_images", []))          # opcional
    canvas_nodes = _as_list(getattr(ctx, "canvas_nodes", []))    # opcional
    svgs = _as_list(getattr(ctx, "svgs", []))                    # opcional

    total = 0
    flagged_image_of_text = 0
    violations = 0
    exempt_logos = 0
    risky_heuristics = 0
    svg_text_ok = 0

    offenders: List[Dict[str, Any]] = []

    # --- <img>
    for el in imgs:
        total += 1

        if _is_logo_like(el):
            exempt_logos += 1
            continue

        # flags fuertes del extractor
        is_iot = False
        if isinstance(el, dict):
            is_iot = _bool(el.get("is_image_of_text")) or _bool(el.get("image_of_text"))
            # OCR y área de texto detectada
            ocr_text = str(el.get("ocr_text") or "").strip()
            text_area = float(el.get("detected_text_area_ratio") or 0.0)
            if (ocr_text and len(ocr_text) >= 2) or text_area >= 0.4:
                is_iot = True

        # heurística
        if not is_iot and _looks_like_image_of_text(el):
            risky_heuristics += 1
            offenders.append({
                "type": "img_risky",
                "src": _get_attr_str(el, "src")[:180],
                "alt": _get_attr_str(el, "alt")[:120],
                "class": _classes_str(el),
                "reason": "Heurística: archivo/clases/alt sugieren imagen de TEXTO (revisión manual)."
            })
            continue

        if not is_iot:
            continue

        flagged_image_of_text += 1
        # AAA: NO se permiten excepciones de “customizable” ni “esencial”
        violations += 1
        offenders.append({
            "type": "img",
            "src": _get_attr_str(el, "src")[:180],
            "alt": _get_attr_str(el, "alt")[:120],
            "reason": "Imagen de TEXTO detectada (AAA no admite excepción salvo logotipo)."
        })

    # --- background-image (opcional)
    for bg in bg_images:
        url = str(bg.get("url") or bg.get("image") or "")
        if _bool(bg.get("is_logo")):
            exempt_logos += 1
            continue
        is_iot = _bool(bg.get("is_image_of_text")) or _bool(bg.get("image_of_text"))
        if not is_iot and _looks_like_image_of_text({"src": url, "class": bg.get("class", [])}):
            risky_heuristics += 1
            offenders.append({
                "type": "bg_risky",
                "url": url[:180],
                "reason": "Heurística: background-image parece contener texto (revisión manual)."
            })
            continue
        if not is_iot:
            continue
        violations += 1
        flagged_image_of_text += 1
        offenders.append({
            "type": "bg_image",
            "url": url[:180],
            "reason": "Imagen de TEXTO en background (AAA no admite excepción salvo logotipo)."
        })

    # --- canvas con texto (opcional)
    for cn in canvas_nodes:
        has_text = _bool(cn.get("canvas_has_text")) or _bool(cn.get("uses_fillText")) or _bool(cn.get("uses_strokeText"))
        if not has_text:
            continue
        if _bool(cn.get("is_logo")):
            exempt_logos += 1
            continue
        violations += 1
        flagged_image_of_text += 1
        offenders.append({
            "type": "canvas",
            "id": cn.get("id",""),
            "reason": "Texto rasterizado en <canvas> (AAA no admite excepción salvo logotipo)."
        })

    # --- SVG (opcional): si tiene <text> → es TEXTO válido, no imagen de texto
    for s in svgs:
        has_text_nodes = _bool(s.get("has_text_nodes")) or _bool(s.get("contains_text_element"))
        if has_text_nodes:
            svg_text_ok += 1

    denom = max(1, flagged_image_of_text)
    ok_ratio = round(max(0.0, min(1.0, (flagged_image_of_text - violations) / denom)), 4) if flagged_image_of_text else 1.0

    details: Dict[str, Any] = {
        "img_total": total,
        "flagged_image_of_text": flagged_image_of_text,
        "violations": violations,
        "exempt_logos": exempt_logos,
        "risky_heuristics": risky_heuristics,
        "svg_text_ok": svg_text_ok,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 1.4.9 (AAA) prohíbe IMÁGENES DE TEXTO. Única excepción: logotipos. "
            "Se usan flags (is_image_of_text/ocr/area) y heurísticas de archivo/clases para marcar riesgos."
        )
    }
    return details

# -------------------------
# Rendered
# -------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED (Playwright) puedes aportar:
      - ocr_items=[{src|url, text, confidence, bbox_area_ratio}]
      - bg_images resueltas tras estilo computado
      - canvas_nodes con detección de fillText/strokeText
    Ajustamos violaciones con OCR/área real.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.4.9; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    ocr_items = _as_list(getattr(rctx, "ocr_items", []))
    if not ocr_items:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'ocr_items'.").strip()
        return d

    extra_viol = 0
    for it in ocr_items:
        text = str(it.get("text") or "").strip()
        conf = float(it.get("confidence") or 0.0)
        area = float(it.get("bbox_area_ratio") or 0.0)
        if len(text) >= 2 and conf >= 0.6 and area >= 0.3:
            url = str(it.get("src") or it.get("url") or "")
            fake_el = {"src": url, "alt": it.get("alt",""), "class": it.get("class", [])}
            if _is_logo_like(fake_el):
                continue
            extra_viol += 1
            d.setdefault("offenders", []).append({
                "type": "img_ocr",
                "url": url[:180],
                "text": (text[:100] + "…") if len(text) > 100 else text,
                "confidence": conf,
                "area_ratio": area,
                "reason": "OCR en render detecta texto prominente en imagen (AAA no admite excepción)."
            })

    if extra_viol:
        d["violations"] = int(d.get("violations", 0)) + extra_viol
        flagged = int(d.get("flagged_image_of_text", 0))
        denom = max(1, flagged + extra_viol)
        d["ok_ratio"] = round(max(0.0, min(1.0, ((flagged + extra_viol) - d["violations"]) / denom)), 4)

    d["note"] = (d.get("note","") + " | RENDERED: OCR aplicado a imágenes visibles.").strip()
    return d

# -------------------------
# IA opcional
# -------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: propone reemplazar imágenes de texto por HTML/CSS (sin excepciones salvo logo).
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    if (details.get("violations", 0) or 0) == 0 and not details.get("offenders"):
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "flagged_image_of_text": details.get("flagged_image_of_text", 0),
            "violations": details.get("violations", 0),
            "exempt_logos": details.get("exempt_logos", 0),
            "risky_heuristics": details.get("risky_heuristics", 0),
        },
        "offenders": details.get("offenders", [])[:20],
        "html_snippet": (html_sample or "")[:2500],
    }
    prompt = (
        "Actúa como auditor WCAG 1.4.9 (Images of Text, No Exception – AAA). "
        "Para cada offender, sugiere cómo reemplazar por texto real: "
        "HTML semántico + CSS (webfonts, text-shadow, gradients, outline). "
        "No aceptes 'customizable' ni 'esencial' como excepción; solo logotipos se permiten. "
        "Devuelve JSON: { suggestions: [{type, reason, html_fix?, css_fix?, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------
# Orquestación
# -------------------------

def run_1_4_9(
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
        title=meta.get("title", "Imágenes de texto (sin excepción)"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required or (details.get("risky_heuristics", 0) > 0)
    )
