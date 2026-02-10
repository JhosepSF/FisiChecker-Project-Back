# audits/checks/criteria/p3/c_3_1_1_language_of_page.py
from typing import Dict, Any, List, Optional, Tuple
import re
import unicodedata

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "3.1.1"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

# BCP 47 (simplificada, permisiva pero útil). Acepta subtags alfanum (2-8), separados por '-'.
_BCP47_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")

# Normaliza 'es_PE' -> 'es-pe', mayúsculas/lower.
def _canon_lang(tag: Optional[str]) -> str:
    if not tag:
        return ""
    t = str(tag).strip().replace("_", "-")
    # subtag 0 minúsculas, región en mayúsculas si parece 2 letras, resto minúsculas
    parts = [p for p in t.split("-") if p]
    if not parts:
        return ""
    out: List[str] = []
    for i, p in enumerate(parts):
        if i == 0:
            out.append(p.lower())
        elif len(p) == 2 and p.isalpha():
            out.append(p.upper())
        else:
            out.append(p.lower())
    return "-".join(out)

def _is_valid_bcp47(tag: Optional[str]) -> bool:
    t = _canon_lang(tag)
    if not t:
        return False
    return bool(_BCP47_RE.match(t))

def _as_list(x):
    if not x: return []
    if isinstance(x, list): return x
    return list(x)

def _s(v: Any) -> str:
    return "" if v is None else str(v)

def _get_attr(node: Any, name: str) -> Optional[str]:
    try:
        if isinstance(node, dict):
            val = node.get(name); return _s(val) if val is not None else None
        if hasattr(node, "get"):
            val = node.get(name)  # type: ignore[attr-defined]
            return _s(val) if val is not None else None
    except Exception:
        pass
    return None

def _page_text(ctx: PageContext) -> str:
    soup = getattr(ctx, "soup", None)
    if soup is not None:
        try:
            return (soup.get_text() or "")[:50000]  # type: ignore[attr-defined]
        except Exception:
            pass
    return _s(getattr(ctx, "document_text", "") or "")[:50000]

# Detector muy simple por stopwords (ES/EN/PT/FR); suficiente para avisos heurísticos
_SW = {
    "es": {"de","la","que","el","en","y","a","los","se","del","las","por","un","para","con","no","una","su","al","lo"},
    "en": {"the","of","and","to","in","a","is","that","it","for","on","as","with","was","are","by","be","or"},
    "pt": {"de","e","o","a","que","do","da","em","um","para","com","os","no","se","na","uma","dos","as"},
    "fr": {"de","la","et","le","les","des","en","un","une","du","est","pour","que","dans","qui","au","plus"},
}

def _guess_lang(text: str) -> Tuple[Optional[str], Dict[str, int]]:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()
    tokens = re.findall(r"[a-z]+", text)
    counts: Dict[str, int] = {k: 0 for k in _SW.keys()}
    for tok in tokens:
        for lang, sws in _SW.items():
            if tok in sws:
                counts[lang] += 1
    if not tokens:
        return None, counts
    lang = max(counts, key=lambda k: counts[k])
    if counts[lang] < 8:  # umbral de confianza mínimo
        return None, counts
    return lang, counts

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    3.1.1: El idioma predeterminado del documento debe estar programáticamente determinado
    (p.ej., <html lang="es-PE">) y ser correcto.
    RAW:
      - Busca lang en ctx.lang o <html>, Content-Language (meta http-equiv) y og:locale como respaldo.
      - Valida formato BCP47 (simplificado).
      - Compara con idioma heurístico del texto (si hay confianza suficiente).
    """
    soup = getattr(ctx, "soup", None)

    # 1) obtener lang declarado
    declared = _canon_lang(getattr(ctx, "lang", "") or "")
    if not declared and soup is not None:
        try:
            html_tag = soup.find("html")
            if html_tag:
                declared = _canon_lang(_get_attr(html_tag, "lang"))
        except Exception:
            pass

    # 2) respaldos no normativos
    meta_lang = ""
    og_locale = ""
    if soup is not None:
        try:
            cl = soup.find("meta", attrs={"http-equiv": re.compile(r"content-language", re.I)})
            if cl:
                meta_lang = _canon_lang(_get_attr(cl, "content"))
            og = soup.find("meta", attrs={"property": re.compile(r"^og:locale$", re.I)})
            if og:
                og_locale = _canon_lang(_get_attr(og, "content"))
        except Exception:
            pass

    declared_source = "html@lang" if declared else ("meta@content-language" if meta_lang else ("og:locale" if og_locale else "unset"))
    effective = declared or meta_lang or og_locale or ""

    # 3) validar formato
    has_lang = bool(effective)
    is_valid = _is_valid_bcp47(effective)

    # 4) heurística de contenido
    body_text = _page_text(ctx)
    guessed, counts = _guess_lang(body_text)

    # 5) decisión: mismatch si hay guessed con confianza y difiere del declarado
    mismatch = False
    if guessed and has_lang:
        # comparar sólo por subtag base (es vs es-PE)
        base_eff = effective.split("-")[0] if effective else ""
        mismatch = (guessed != base_eff)

    offenders: List[Dict[str, Any]] = []
    if not has_lang:
        offenders.append({"reason": "Falta idioma principal del documento (<html lang=\"...\")."})
    elif not is_valid:
        offenders.append({"reason": f"Valor de idioma no válido según BCP47: '{effective}'."})
    elif mismatch:
        offenders.append({"reason": f"El idioma declarado ('{effective}') parece no coincidir con el del contenido (heurística='{guessed}')."})

    applicable = 1
    passed = has_lang and is_valid and (not mismatch)

    ok_ratio = 1.0 if passed else 0.0
    details: Dict[str, Any] = {
        "applicable": applicable,
        "declared": effective,
        "declared_source": declared_source,
        "is_valid_bcp47": is_valid,
        "guessed_lang": guessed,
        "guess_counts": counts,
        "mismatch": mismatch,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 3.1.1 requiere <html lang> válido y correcto. Se valida formato BCP47 (simplificado) y se contrasta con "
            "una heurística básica por stopwords de ES/EN/PT/FR (solo para alertas, no definitivo)."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, preferir:
      - rctx.lang_runtime (document.documentElement.lang tras JS)
      - rctx.meta_locale_runtime (p. ej. i18n SPA)
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 3.1.1; no se pudo evaluar en modo renderizado."}

    effective = _canon_lang(getattr(rctx, "lang_runtime", "") or getattr(rctx, "lang", "") or "")
    if not effective:
        # caer a RAW en el DOM renderizado
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = (d.get("note","") + " | RENDERED: sin 'lang_runtime', se reusó RAW.").strip()
        return d

    is_valid = _is_valid_bcp47(effective)
    body_text = _page_text(rctx)
    guessed, counts = _guess_lang(body_text)
    mismatch = False
    if guessed:
        base_eff = effective.split("-")[0]
        mismatch = (guessed != base_eff)

    offenders: List[Dict[str, Any]] = []
    if not is_valid:
        offenders.append({"reason": f"Valor de idioma no válido según BCP47 (runtime): '{effective}'."})
    elif mismatch:
        offenders.append({"reason": f"El idioma declarado (runtime='{effective}') no coincide con el contenido (heurística='{guessed}')."})

    passed = is_valid and (not mismatch)
    details: Dict[str, Any] = {
        "rendered": True,
        "declared": effective,
        "is_valid_bcp47": is_valid,
        "guessed_lang": guessed,
        "guess_counts": counts,
        "mismatch": mismatch,
        "ok_ratio": 1.0 if passed else 0.0,
        "offenders": offenders,
        "note": "RENDERED: validación usando document.documentElement.lang y heurística de contenido."
    }
    return details

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False, "ai_message": "IA no configurada."}
    need = (not details.get("declared")) or (not details.get("is_valid_bcp47")) or bool(details.get("mismatch"))
    if not need:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "declared": details.get("declared"),
        "guess": details.get("guessed_lang"),
        "sample": (html_sample or "")[:2000],
        "examples": [
            '<html lang="es-PE"> ... </html>',
            '<html lang="en"> ... </html>',
            '<html lang="pt-BR"> ... </html>',
        ]
    }
    prompt = (
        "Eres auditor WCAG 3.1.1 (Language of Page). "
        "Si falta o es inválido el <html lang>, sugiere el valor BCP47 correcto y un snippet mínimo. "
        "Si hay desajuste con el contenido, explica el ajuste sugerido. "
        "Devuelve JSON: {suggestions:[{lang, snippet, rationale}], manual_review?:bool, summary?:string}"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_3_1_1(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None
) -> CriterionOutcome:

    if mode == CheckMode.RENDERED:
        if rendered_ctx is None:
            details = _compute_counts_raw(ctx); details["warning"] = "Se pidió RENDERED sin rendered_ctx; fallback a RAW."; src = "raw"
        else:
            details = _compute_counts_rendered(rendered_ctx); src = "rendered"
    else:
        details = _compute_counts_raw(ctx); src = "raw"

    manual_required = False
    if mode == CheckMode.AI:
        ai = _ai_review(details, html_sample=html_for_ai); details["ai_info"] = ai; src = "ai"
        manual_required = bool(ai.get("manual_required", False))

    passed = bool(details.get("declared")) and bool(details.get("is_valid_bcp47")) and (not bool(details.get("mismatch")))
    verdict = verdict_from_counts(details, passed)
    score0 = score_from_verdict(verdict)

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0, details=details,
        level=meta.get("level","A"), principle=meta.get("principle","Comprensible"),
        title=meta.get("title","Idioma de la página"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
