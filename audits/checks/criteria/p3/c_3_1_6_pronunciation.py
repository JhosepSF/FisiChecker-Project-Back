# audits/checks/criteria/p3/c_3_1_6_pronunciation.py
from typing import Dict, Any, List, Optional, Tuple, Set
import re
import unicodedata

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "3.1.6"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

# Pequeña lista de heterónimos EN (ambigua pronunciación) para demo heurística
_EN_HETERONYMS = {
    "lead","read","wind","tear","row","bass","bow","live","close","minute","record","object","present","project","content","produce"
}

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

def _tokens(text: str) -> List[str]:
    return re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}", text or "")

def _has_pronunciation_markup(soup) -> bool:
    if soup is None: return False
    try:
        # <ruby>, <rt>, elementos con clase "ipa"/"pronounce", data-pronounce, title="pronunciación ..."
        if soup.find("ruby") or soup.find("rt"): return True
        if soup.find(class_=re.compile(r"\b(ipa|pronounce|pronunciaci[oó]n)\b", re.I)): return True
        if soup.find(attrs={"data-pronounce": True}): return True
        if soup.find(True, attrs={"title": re.compile(r"(pronunciation|pronunciaci[oó]n)", re.I)}): return True
    except Exception:
        pass
    return False

def _find_ambiguous_terms_en(text: str) -> Set[str]:
    toks = _tokens(text)
    out: Set[str] = set()
    for t in toks:
        lt = unicodedata.normalize("NFKD", t).encode("ascii","ignore").decode("ascii").lower()
        if lt in _EN_HETERONYMS:
            out.add(lt)
    return out

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    3.1.6 (AAA): Se proporciona un mecanismo para identificar la pronunciación específica de palabras
    cuando su significado depende de la pronunciación.
    RAW (heurístico):
      - Si la página está en inglés y aparecen heterónimos comunes, se espera una ayuda de pronunciación
        (<ruby>, clase 'ipa', data-pronounce, títulos, etc.) en la página.
      - En otros idiomas, el check queda NA a menos que el extractor reporte candidatos explícitos.
    """
    soup = getattr(ctx, "soup", None)
    base_lang = _page_lang(ctx)
    text = _page_text(ctx)
    base = base_lang.split("-")[0] if base_lang else ""

    applicable = 0
    candidates: List[str] = []
    has_markup = _has_pronunciation_markup(soup)

    if base == "en":
        amb = sorted(list(_find_ambiguous_terms_en(text)))
        candidates = amb
        applicable = 1 if len(amb) > 0 else 0

    # Permite que el extractor agregue candidatos manuales para cualquier idioma:
    extra = _as_list(getattr(ctx, "pronunciation_candidates", []))
    for it in extra:
        if isinstance(it, str) and it.strip():
            if it not in candidates:
                candidates.append(it)
    if extra:
        applicable = 1

    missing = 0
    offenders: List[Dict[str, Any]] = []
    if applicable == 1 and not has_markup:
        # No se encontró ninguna marca global de pronunciación
        missing = len(candidates)
        for term in candidates[:50]:
            offenders.append({"term": term, "reason": "Candidato ambiguo sin marca de pronunciación detectada (heurístico)."})

    violations = missing  # AAA: exige mecanismo si aplica
    passed = (applicable == 0) or (violations == 0)

    details: Dict[str, Any] = {
        "applicable": applicable,
        "lang": base_lang,
        "candidates": candidates,
        "has_pronunciation_markup": has_markup,
        "missing": missing,
        "violations": violations,
        "ok_ratio": 1.0 if passed else 0.0,
        "offenders": offenders,
        "note": (
            "RAW: heurística basada en heterónimos EN y/o candidatos del extractor. "
            "Se considera mecanismo válido <ruby>/<rt>, clases 'ipa/pronounce', data-pronounce o títulos con 'pronunciación'."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    rctx.pronunciation_test = [
      { "term": str, "is_ambiguous": bool, "has_pronunciation": bool, "notes": str|None }
    ]
    Violación si existe término ambiguo sin marca de pronunciación.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 3.1.6; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "pronunciation_test", []))
    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = (d.get("note","") + " | RENDERED: sin 'pronunciation_test', se reusó RAW.").strip()
        return d

    applicable = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for it in data:
        if not isinstance(it, dict):
            continue
        if not bool(it.get("is_ambiguous")):
            continue
        applicable += 1
        if not bool(it.get("has_pronunciation")):
            violations += 1
            offenders.append({
                "term": _s(it.get("term")),
                "reason": "Término ambiguo sin marca de pronunciación (runtime).",
                "notes": _s(it.get("notes"))
            })

    passed = (applicable == 0) or (violations == 0)

    details: Dict[str, Any] = {
        "rendered": True,
        "applicable": applicable,
        "violations": violations,
        "ok_ratio": 1.0 if passed else 0.0,
        "offenders": offenders,
        "note": "RENDERED: verificación explícita de candidatos y presencia de pronunciación."
    }
    return details

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False, "ai_message": "IA no configurada."}
    needs = (details.get("violations", 0) or 0) > 0
    if not needs:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "offenders": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2000],
        "recipes": [
            "<ruby>record<rt>/ˈrɛk.ɔːrd/ (noun)</rt></ruby> vs <ruby>record<rt>/rɪˈkɔːrd/ (verb)</rt></ruby>",
            "<span class='ipa'>/wiːnd/</span> para 'wind (v.)' y <span class='ipa'>/wɪnd/</span> para 'wind (n.)'",
            "<span data-pronounce='/liːd/'>lead</span>"
        ]
    }
    prompt = (
        "Eres auditor WCAG 3.1.6 (Pronunciation, AAA). "
        "Para cada término ambiguo, sugiere marcado (<ruby>/<rt>, clase 'ipa', data-pronounce) con breve justificación. "
        "Devuelve JSON: { suggestions:[{term, snippet, rationale}], manual_review?:bool, summary?:string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_3_1_6(
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

    # 3) passed / verdict
    violations = int(details.get("violations", 0) or 0)
    passed = (violations == 0)

    verdict = verdict_from_counts(details, passed)
    score0 = score_from_verdict(verdict)
    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0, details=details,
        level=meta.get("level","AAA"), principle=meta.get("principle","Comprensible"),
        title=meta.get("title","Pronunciación"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
