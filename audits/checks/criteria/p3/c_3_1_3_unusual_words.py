# audits/checks/criteria/p3/c_3_1_3_unusual_words.py
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

CODE = "3.1.3"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

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

def _get_attr(node: Any, name: str) -> Optional[str]:
    try:
        if isinstance(node, dict):
            val = node.get(name)
            return _s(val) if val is not None else None
        if hasattr(node, "get"):
            val = node.get(name)  # type: ignore[attr-defined]
            return _s(val) if val is not None else None
    except Exception:
        pass
    return None

def _get_text(node: Any) -> str:
    if isinstance(node, dict):
        for k in ("text","label","inner_text","aria-label","title"):
            v = node.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""
    try:
        if hasattr(node, "get_text"):
            t = node.get_text()  # type: ignore[attr-defined]
            if isinstance(t, str) and t.strip():
                return t.strip()
    except Exception:
        pass
    return ""

_SW = {
    "es": {"de","la","que","el","en","y","a","los","se","del","las","por","un","para","con","no","una","su","al","lo","como","más","o"},
    "en": {"the","of","and","to","in","a","is","that","it","for","on","as","with","was","are","by","be","or","from","at"},
    "pt": {"de","e","o","a","que","do","da","em","um","para","com","os","no","se","na","uma","dos","as"},
    "fr": {"de","la","et","le","les","des","en","un","une","du","est","pour","que","dans","qui","au","plus"},
}

TOKEN_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}", re.UNICODE)

def _canon_lang(tag: Optional[str]) -> str:
    if not tag: return ""
    t = str(tag).strip().replace("_","-")
    parts = [p for p in t.split("-") if p]
    if not parts: return ""
    out: List[str] = []
    for i,p in enumerate(parts):
        if i == 0: out.append(p.lower())
        elif len(p) == 2 and p.isalpha(): out.append(p.upper())
        else: out.append(p.lower())
    return "-".join(out)

def _page_text(ctx: PageContext) -> str:
    soup = getattr(ctx, "soup", None)
    if soup is not None:
        try:
            return (soup.get_text() or "")  # type: ignore[attr-defined]
        except Exception:
            pass
    return _s(getattr(ctx, "document_text", "") or "")

def _tokens(text: str) -> List[str]:
    return TOKEN_RE.findall(unicodedata.normalize("NFKD", text or ""))

def _is_common(token: str, base_lang: str) -> bool:
    base = base_lang.split("-")[0] if base_lang else ""
    sw = _SW.get(base, set())
    t = _lower(unicodedata.normalize("NFKD", token))
    return t in sw or len(t) <= 3

def _collect_unusual_candidates(text: str, base_lang: str) -> Dict[str, int]:
    """
    Heurística: palabras de >=6 caracteres, repetidas >=2 veces, y no 'comunes'.
    """
    counts: Dict[str, int] = {}
    for tok in _tokens(text):
        if len(tok) < 6:
            continue
        if _is_common(tok, base_lang):
            continue
        k = tok.lower()
        counts[k] = counts.get(k, 0) + 1
    # filtra a las que aparecen al menos 2 veces
    return {k: v for k, v in counts.items() if v >= 2}

def _has_global_glossary(soup) -> bool:
    if soup is None:
        return False
    try:
        # link o sección “Glosario/Glossary/Términos”
        link = soup.find("a", string=re.compile(r"\b(glosario|glossary|t[eé]rminos|terminolog[ií]a)\b", re.I))
        if link:
            return True
        sec = soup.find(id=re.compile(r"glossary|glosario|terminos", re.I)) or soup.find(class_=re.compile(r"glossary|glosario|terminos", re.I))
        return bool(sec)
    except Exception:
        return False

def _defined_terms_from_markup(soup) -> Set[str]:
    """
    Terminos “explicados” localmente:
      - <dfn>texto</dfn>
      - <abbr title="...">PALABRA</abbr>
      - elementos con data-tooltip/data-definition/title
      - <ruby><rt> (pronunciación)
    """
    out: Set[str] = set()
    if soup is None:
        return out
    try:
        for d in soup.find_all("dfn"):
            txt = _get_text(d)
            if txt: out.add(txt.strip().lower())
    except Exception:
        pass
    try:
        for ab in soup.find_all("abbr"):
            t = _get_attr(ab, "title")
            txt = _get_text(ab)
            if t and txt:
                out.add(txt.strip().lower())
    except Exception:
        pass
    try:
        for el in soup.find_all(True, attrs={"title": True}):
            txt = _get_text(el)
            if txt:
                out.add(txt.strip().lower())
    except Exception:
        pass
    try:
        for rb in soup.find_all("ruby"):
            txt = _get_text(rb)
            if txt:
                out.add(txt.strip().lower())
    except Exception:
        pass
    return out

def _has_pronunciation_for_term(soup, term: str) -> bool:
    if soup is None or not term:
        return False
    try:
        # ruby o elementos con clase “ipa/pronounce”
        if soup.find("ruby", string=re.compile(re.escape(term), re.I)):
            return True
        if soup.find(class_=re.compile(r"\b(ipa|pronounce|pronunciaci[oó]n)\b", re.I), string=re.compile(re.escape(term), re.I)):
            return True
    except Exception:
        pass
    return False

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    3.1.3 (AAA): Proveer mecanismo para identificar definiciones de palabras inusuales, jerga o usos poco comunes,
    y/o un mecanismo para pronunciación de palabras con pronunciación inusual.
    Heurística:
      - Detecta candidatos “inusuales” por frecuencia y longitud.
      - Considera cubiertos si hay glosario global o marcado local (<dfn>, <abbr title>, title/tooltip, <ruby>).
    """
    soup = getattr(ctx, "soup", None)
    base_lang = _canon_lang(getattr(ctx, "lang", "") or "")
    text = _page_text(ctx)

    candidates = _collect_unusual_candidates(text, base_lang)
    defined_local = _defined_terms_from_markup(soup)
    has_glossary = _has_global_glossary(soup)

    applicable = 1 if len(candidates) > 0 else (1 if has_glossary else 0)

    covered = 0
    covered_pron = 0
    missing = 0
    offenders: List[Dict[str, Any]] = []

    for term, n in sorted(candidates.items(), key=lambda kv: (-kv[1], kv[0]))[:80]:
        has_def = has_glossary or (term in defined_local)
        has_pro = _has_pronunciation_for_term(soup, term)
        if has_def:
            covered += 1
        else:
            missing += 1
            offenders.append({"term": term, "occurrences": n, "reason": "Candidato inusual sin glosario/definición cercana."})
        if has_pro:
            covered_pron += 1

    violations = 0 if (applicable == 0 or has_glossary or missing == 0) else missing
    ok_ratio = 1.0 if applicable == 0 else (1.0 if violations == 0 else max(0.0, min(1.0, covered / max(1, len(candidates)))))

    details: Dict[str, Any] = {
        "base_lang": base_lang,
        "applicable": applicable,
        "candidates_total": len(candidates),
        "covered_definitions": covered,
        "covered_pronunciations": covered_pron,
        "missing": missing,
        "has_global_glossary": has_glossary,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: heurística de palabras inusuales por frecuencia/longitud. "
            "Se considera mecanismo válido un glosario o marcado local (<dfn>, <abbr title>, title/tooltip). "
            "Pronunciación: <ruby>/<rt> o clases 'ipa/pronounce'."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede aportar:
      rctx.unusual_words_test = [
        { "term": str, "occurrences": int, "has_definition": bool,
          "has_pronunciation": bool, "notes": str|None }
      ]
      y rctx.has_global_glossary: bool
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 3.1.3; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "unusual_words_test", []))
    has_glossary = bool(getattr(rctx, "has_global_glossary", False))

    if not data:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = (d.get("note","") + " | RENDERED: sin 'unusual_words_test', se reusó RAW.").strip()
        return d

    applicable = 1
    total = 0
    covered = 0
    covered_pron = 0
    missing = 0
    offenders: List[Dict[str, Any]] = []

    for it in data:
        if not isinstance(it, dict):
            continue
        total += 1
        has_def = bool(it.get("has_definition")) or has_glossary
        has_pro = bool(it.get("has_pronunciation"))
        if has_def:
            covered += 1
        else:
            missing += 1
            offenders.append({"term": _s(it.get("term")), "occurrences": int(it.get("occurrences") or 1),
                              "reason": "Sin mecanismo de definición (runtime)."})
        if has_pro:
            covered_pron += 1

    violations = 0 if (has_glossary or missing == 0) else missing
    ok_ratio = 1.0 if total == 0 else (1.0 if violations == 0 else max(0.0, min(1.0, covered / max(1, total))))

    details: Dict[str, Any] = {
        "rendered": True,
        "applicable": applicable,
        "candidates_total": total,
        "covered_definitions": covered,
        "covered_pronunciations": covered_pron,
        "missing": missing,
        "has_global_glossary": has_glossary,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: verificación explícita de definiciones/pronunciaciones y glosario global."
    }
    return details

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False, "ai_message": "IA no configurada."}
    need = (details.get("missing", 0) or 0) > 0 or (not details.get("has_global_glossary", False))
    if not need:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "missing_terms": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2200],
        "recipes": [
            "<dfn>término</dfn> con explicación adyacente.",
            "<abbr title='definición breve'>JERGA</abbr>",
            "<ruby>palabra<rt>pronunciación IPA</rt></ruby>",
            "Enlace a página de Glosario con anclas por término."
        ]
    }
    prompt = (
        "Eres auditor WCAG 3.1.3 (Unusual Words, AAA). "
        "Propón glosario o marcado local para definir términos y, cuando aplique, añadir pronunciación. "
        "Devuelve JSON: { suggestions: [{term, snippet, rationale}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_3_1_3(
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

    # Pasamos si: no hay candidatos o hay glosario o todos los candidatos tienen definición.
    total = int(details.get("candidates_total", 0) or 0)
    has_glossary = bool(details.get("has_global_glossary", False))
    missing = int(details.get("missing", 0) or 0)
    passed = (total == 0) or has_glossary or (missing == 0)

    verdict = verdict_from_counts(details, passed)
    score0 = score_from_verdict(verdict)
    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0, details=details,
        level=meta.get("level","AAA"), principle=meta.get("principle","Comprensible"),
        title=meta.get("title","Palabras inusuales"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
