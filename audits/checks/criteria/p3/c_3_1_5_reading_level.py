# audits/checks/criteria/p3/c_3_1_5_reading_level.py
from typing import Dict, Any, List, Optional, Tuple
import re
import math
import unicodedata

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "3.1.5"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+(?:['’-][A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)?", re.UNICODE)
_SENT_END_RE = re.compile(r"[\.!?…]+(?:\s+|$)")
_VOWELS_ES = set("aeiouáéíóúü")
_VOWELS_EN = set("aeiouy")

def _as_list(x):
    if not x: return []
    if isinstance(x, list): return x
    return list(x)

def _s(v: Any) -> str:
    return "" if v is None else str(v)

def _canon_lang(tag: Optional[str]) -> str:
    if not tag: return ""
    t = str(tag).strip().replace("_","-")
    parts = [p for p in t.split("-") if p]
    if not parts: return ""
    out: List[str] = []
    for i,p in enumerate(parts):
        if i == 0: out.append(p.lower())
        elif len(p)==2 and p.isalpha(): out.append(p.upper())
        else: out.append(p.lower())
    return "-".join(out)

def _page_lang(ctx: PageContext) -> str:
    return _canon_lang(getattr(ctx, "lang", "") or "")

def _page_text(ctx: PageContext) -> str:
    soup = getattr(ctx, "soup", None)
    if soup is not None:
        try:
            return (soup.get_text() or "")  # type: ignore[attr-defined]
        except Exception:
            pass
    return _s(getattr(ctx, "document_text", "") or "")

def _tokenize_words(text: str) -> List[str]:
    return _WORD_RE.findall(text or "")

def _split_sentences(text: str) -> List[str]:
    if not text: return []
    # segmentación simple por signos de fin de oración
    parts = _SENT_END_RE.split(text)
    return [p.strip() for p in parts if isinstance(p, str) and p.strip()]

def _syllables_en(word: str) -> int:
    # Heurística ligera
    w = unicodedata.normalize("NFKD", word or "").encode("ascii","ignore").decode("ascii").lower()
    if not w: return 0
    w = re.sub(r"[^a-z]", "", w)
    if not w: return 0
    # quita 'e' muda final
    if w.endswith("e"):
        w2 = w[:-1]
    else:
        w2 = w
    groups = re.findall(r"[aeiouy]+", w2)
    syl = max(1, len(groups))
    return syl

def _syllables_es(word: str) -> int:
    w = unicodedata.normalize("NFKD", word or "").lower()
    w = re.sub(r"[^a-záéíóúüñ]", "", w)
    if not w: return 0
    groups = re.findall(r"[aeiouáéíóúü]+", w)
    syl = max(1, len(groups))
    return syl

def _reading_metrics(text: str, lang: str) -> Dict[str, Any]:
    """
    Devuelve:
      - words, sentences, syllables
      - index_name, index_value
      - grade_est (aprox. 'equivalente' a grado escolar)
      - flags: difficult_for_lower_secondary (bool)
    Para EN: Flesch-Kincaid Grade.
    Para ES: Szigriszt-Pazos (INFLESZ). Mapeo heurístico a dificultad.
    """
    words = _tokenize_words(text)
    sents = _split_sentences(text)
    n_w = len(words)
    n_s = max(1, len(sents))
    # cuenta sílabas
    base = lang.split("-")[0] if lang else ""
    if base == "es":
        n_sy = sum(_syllables_es(w) for w in words)
        # Szigriszt-Pazos (INFLESZ)
        # 206.84 - (62.3 * sílabas/palabra) - (palabras/oración)
        sp_index = 206.84 - (62.3 * (n_sy / max(1, n_w))) - (n_w / n_s)
        # Heurística de dificultad: <55 es “algo difícil o peor” (por debajo de secundaria).
        difficult = (sp_index < 55.0)
        grade_est = 10 if difficult else 8  # aproximación grosera
        return {
            "words": n_w, "sentences": n_s, "syllables": n_sy,
            "index_name": "Szigriszt-Pazos (INFLESZ)",
            "index_value": round(sp_index, 2),
            "grade_est": grade_est,
            "difficult_for_lower_secondary": bool(difficult),
        }
    else:
        # EN por defecto (si no, usamos esta misma para otros idiomas latinos como proxy)
        n_sy = sum(_syllables_en(w) for w in words)
        # Flesch-Kincaid Grade
        fk_grade = 0.39 * (n_w / n_s) + 11.8 * (n_sy / max(1, n_w)) - 15.59
        difficult = (fk_grade > 9.0)  # > 9º grado ~ por encima de secundaria inferior
        return {
            "words": n_w, "sentences": n_s, "syllables": n_sy,
            "index_name": "Flesch-Kincaid Grade",
            "index_value": round(fk_grade, 2),
            "grade_est": round(fk_grade, 1),
            "difficult_for_lower_secondary": bool(difficult),
        }

_EASY_LINK_RE = re.compile(
    r"(lectura\s*f[aá]cil|versi[oó]n\s*f[aá]cil|lenguaje\s*claro|lenguaje\s*simple|plain\s*language|easy\s*read|simple\s*version|resumen|summary|audio\s*versi[oó]n|read\s*aloud)",
    re.I
)

def _find_support_links(ctx: PageContext) -> List[Dict[str, str]]:
    soup = getattr(ctx, "soup", None)
    hits: List[Dict[str, str]] = []
    if soup is None:
        return hits
    try:
        for a in soup.find_all("a"):
            txt = _s(getattr(a, "get_text", lambda: "")())  # type: ignore[misc]
            if _EASY_LINK_RE.search(txt or ""):
                href = a.get("href") if hasattr(a, "get") else None  # type: ignore[attr-defined]
                hits.append({"text": txt.strip()[:120], "href": _s(href)[:180]})
    except Exception:
        pass
    return hits

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    3.1.5 (AAA): Si el texto requiere una capacidad de lectura más avanzada que la educación secundaria inferior,
    se provee contenido suplementario (resumen, versión en lenguaje claro o audio).
    RAW:
      - Estima nivel de lectura (EN: FK Grade; ES: INFLESZ Szigriszt-Pazos).
      - Busca enlaces/pistas de apoyo (resumen, 'lectura fácil', 'plain language', audio).
    """
    text = _page_text(ctx)
    base_lang = _page_lang(ctx)
    metrics = _reading_metrics(text, base_lang)

    words = int(metrics.get("words", 0) or 0)
    applicable = 1 if words >= 300 else 0  # umbral mínimo para estimar

    support_links = _find_support_links(ctx)
    has_support = bool(support_links)

    difficult = bool(metrics.get("difficult_for_lower_secondary", False))
    violations = 1 if (applicable == 1 and difficult and not has_support) else 0
    passed = (applicable == 0) or (not difficult) or has_support

    details: Dict[str, Any] = {
        "applicable": applicable,
        "lang": base_lang,
        "metrics": metrics,
        "support_links_found": support_links,
        "has_support": has_support,
        "violations": violations,
        "ok_ratio": 1.0 if passed else 0.0,
        "note": (
            "RAW: estimación de nivel de lectura (ES: INFLESZ; EN: FK Grade). "
            "Si es difícil (>secundaria inferior), se espera resumen/versión simple/audio. "
            "Heurístico; confirmar manualmente."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    rctx.reading_level_test = {
      "lang": "es-PE"|"en"|...,
      "fk_grade": float|None,            # si EN
      "szp_index": float|None,           # si ES
      "difficult_for_lower_secondary": bool,
      "has_support": bool,               # resumen/versión simple/audio medidos en runtime
      "notes": str|None
    }
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 3.1.5; no se pudo evaluar en modo renderizado."}

    data = getattr(rctx, "reading_level_test", None)
    if not isinstance(data, dict):
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = (d.get("note","") + " | RENDERED: sin 'reading_level_test', se reusó RAW.").strip()
        return d

    diff = bool(data.get("difficult_for_lower_secondary"))
    support = bool(data.get("has_support"))

    violations = 1 if (diff and not support) else 0
    passed = (not diff) or support

    details: Dict[str, Any] = {
        "rendered": True,
        "lang": _s(data.get("lang")),
        "fk_grade": data.get("fk_grade"),
        "szp_index": data.get("szp_index"),
        "difficult_for_lower_secondary": diff,
        "has_support": support,
        "violations": violations,
        "ok_ratio": 1.0 if passed else 0.0,
        "note": "RENDERED: métricas y soportes evaluados a nivel de runtime."
    }
    return details

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False, "ai_message": "IA no configurada."}
    need = bool(details.get("violations", 0))
    if not need:
        return {"ai_used": False, "manual_required": False}
    metrics = details.get("metrics", {})
    ctx_json = {
        "metrics": metrics,
        "support_links": details.get("support_links_found", [])[:10],
        "html_snippet": (html_sample or "")[:2200],
        "recipes": [
            "Añade un resumen al inicio (3-5 frases) y un enlace 'Versión en lenguaje claro'.",
            "Provee un botón 'Escuchar' que lea el contenido o enlace a versión en audio.",
            "Divide oraciones largas (>25 palabras) y reduce palabras >14 caracteres."
        ]
    }
    prompt = (
        "Eres auditor WCAG 3.1.5 (Reading Level, AAA). "
        "Si el nivel es alto, propone resumen/versión simple/audio con snippets breves. "
        "Devuelve JSON: { suggestions:[{type: 'summary|plain|audio', snippet, rationale}], manual_review?:bool, summary?:string }"
    )
    try:
        ai = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_3_1_5(
    ctx: PageContext,
    mode: CheckMode = CheckMode.RAW,
    rendered_ctx: Optional[PageContext] = None,
    html_for_ai: Optional[str] = None
) -> CriterionOutcome:

    # 1) detalles
    if mode == CheckMode.RENDERED:
        if rendered_ctx is None:
            details = _compute_counts_raw(ctx); details["warning"] = "Se pidió RENDERED sin rendered_ctx; fallback a RAW."; src = "raw"
        else:
            details = _compute_counts_rendered(rendered_ctx); src = "rendered"
    else:
        details = _compute_counts_raw(ctx); src = "raw"

    # 2) IA opcional
    manual_required = False
    if mode == CheckMode.AI:
        ai = _ai_review(details, html_sample=html_for_ai); details["ai_info"] = ai; src = "ai"
        manual_required = bool(ai.get("manual_required", False))

    # 3) passed/verdict
    violations = int(details.get("violations", 0) or 0)
    passed = (violations == 0)

    verdict = verdict_from_counts(details, passed)
    score0 = score_from_verdict(verdict)
    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0, details=details,
        level=meta.get("level","AAA"), principle=meta.get("principle","Comprensible"),
        title=meta.get("title","Nivel de lectura"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
