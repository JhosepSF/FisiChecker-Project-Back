# audits/checks/criteria/p1/c_1_1_1_alt_text.py
from typing import Dict, Any, List, Optional

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  # si no existe, el modo AI queda deshabilitado

CODE = "1.1.1"

def _bool_attr(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")

def _is_link_wrapped(img: Dict[str, Any]) -> bool:
    """
    Intento defensivo: si el extractor añadió alguna pista de que <img> está dentro de <a>.
    No rompe si las claves no existen.
    """
    return bool(
        img.get("in_link")
        or img.get("_in_link")
        or (img.get("parent_tag") == "a")
        or (img.get("closest_a") is not None)
    )

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    imgs = list(getattr(ctx, "imgs", []) or [])
    total = len(imgs)
    with_alt = 0
    decorative = 0
    missing_alt = 0
    offenders: List[Dict[str, Any]] = []

    for img in imgs:
        alt = img.get("alt")
        role = (img.get("role") or "").lower()
        aria_hidden = _bool_attr(img.get("aria-hidden"))
        in_link = _is_link_wrapped(img)

        # Si tiene atributo alt (aunque sea vacío)
        if alt is not None:
            if alt.strip() == "":
                # alt vacío solo es decorativo si tiene marcas explícitas
                if aria_hidden or role in {"presentation", "none"}:
                    decorative += 1
                # Si está en un enlace, alt="" no es suficiente (debe describir destino)
                elif in_link:
                    missing_alt += 1
                    offenders.append({
                        "tag": "img",
                        "src": (img.get("src") or "")[:180],
                        "id": img.get("id", ""),
                        "class": img.get("class", []),
                        "aria-hidden": aria_hidden,
                        "role": role,
                        "reason": "Imagen enlazada con alt vacío (debe describir el destino)."
                    })
                else:
                    # alt="" sin marcas explícitas → missing_alt
                    missing_alt += 1
                    offenders.append({
                        "tag": "img",
                        "src": (img.get("src") or "")[:180],
                        "id": img.get("id", ""),
                        "class": img.get("class", []),
                        "aria-hidden": aria_hidden,
                        "role": role,
                        "reason": "Imagen con alt vacío (no tiene atributos de decoración explícitos)."
                    })
            else:
                with_alt += 1
        else:
            # No tiene atributo alt
            if aria_hidden or role in {"presentation", "none"}:
                decorative += 1
            else:
                missing_alt += 1
                offenders.append({
                    "tag": "img",
                    "src": (img.get("src") or "")[:180],
                    "id": img.get("id", ""),
                    "class": img.get("class", []),
                    "aria-hidden": aria_hidden,
                    "role": role,
                    "reason": "Falta atributo alt y no es decorativa."
                })

    details: Dict[str, Any] = {
        "images_total": total,
        "with_alt": with_alt,
        "decorative": decorative,
        "missing_alt": missing_alt,
        "ok_ratio": round(((with_alt + decorative) / total), 4) if total > 0 else 1.0,
        "offenders": offenders,
        "note": (
            "RAW: cuenta alt presente/ausente y decorativas (alt='' / aria-hidden / role='presentation'). "
            "Además, marca como incumplimiento las imágenes enlazadas con alt vacío."
        )
    }
    return details

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    Si tienes un contexto producido por Playwright (DOM post-render),
    úsalo aquí para extender la detección (ej. background-image).
    Si rctx es None, devolvemos un NA claro.
    """
    if rctx is None:
        return {
            "na": True,
            "note": "No se proveyó rendered_ctx para 1.1.1; no se pudo evaluar en modo renderizado."
        }
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note", "") + " | RENDERED: extensible a background-image.").strip()
    return d

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    total = details.get("images_total", 0)
    missing = details.get("missing_alt", 0)
    offenders = details.get("offenders", [])
    if total == 0 or missing == 0:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "images_total": total,
        "with_alt": details.get("with_alt", 0),
        "decorative": details.get("decorative", 0),
        "missing_alt": missing,
        "sample_offenders": offenders[:5],
        "html_snippet": (html_sample or "")[:2000],
    }
    prompt = (
        "Evalúa el criterio WCAG 1.1.1 (Contenido no textual). "
        "Si hay imágenes sin 'alt', di si alguna parece decorativa y sugiere textos alternativos breves para las otras. "
        "Devuelve JSON con: { suggestions: [{src, suggestion_alt, decorative?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

def _verdict_from_111(details: Dict[str, Any]) -> str:
    if bool(details.get("na", False)):
        return "na"
    total = int(details.get("images_total") or 0)
    missing = int(details.get("missing_alt") or 0)
    if total == 0:
        return "na"
    
    # Calcular y guardar ratio
    ok_count = total - missing
    ratio = ok_count / total
    details["ratio"] = ratio
    
    # Ultra estricto: solo PASS si 100%
    if missing == 0:
        return "pass"
    # PARTIAL si >= 80%
    if ratio >= 0.80:
        return "partial"
    # FAIL si < 70%
    return "fail"


def run_1_1_1(
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

    # 3) Veredicto ESTRICTO para 1.1.1
    verdict = _verdict_from_111(details)
    passed = (verdict == "pass")
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
        title=meta.get("title", "Contenido no textual"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )