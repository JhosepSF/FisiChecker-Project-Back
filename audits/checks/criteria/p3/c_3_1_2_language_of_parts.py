# audits/checks/criteria/p3/c_3_1_2_language_of_parts.py
from typing import Dict, Any, List, Optional, Tuple
import re
import unicodedata

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "3.1.2"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

_BCP47_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
HEADING_TAG_RE = re.compile(r"^h[1-6]$", re.I)

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

def _is_valid_bcp47(tag: Optional[str]) -> bool:
    t = _canon_lang(tag)
    return bool(t and _BCP47_RE.match(t))

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

# Detector simple por stopwords (mismas listas que 3.1.1)
_SW = {
    "es": {"de","la","que","el","en","y","a","los","se","del","las","por","un","para","con","no","una","su","al","lo"},
    "en": {"the","of","and","to","in","a","is","that","it","for","on","as","with","was","are","by","be","or"},
    "pt": {"de","e","o","a","que","do","da","em","um","para","com","os","no","se","na","uma","dos","as"},
    "fr": {"de","la","et","le","les","des","en","un","une","du","est","pour","que","dans","qui","au","plus"},
}

def _guess_lang(text: str) -> Tuple[Optional[str], int]:
    norm = unicodedata.normalize("NFKD", text or "").encode("ascii","ignore").decode("ascii").lower()
    toks = re.findall(r"[a-z]+", norm)
    if not toks: return None, 0
    counts = {k:0 for k in _SW.keys()}
    for tk in toks:
        for lg, sws in _SW.items():
            if tk in sws: counts[lg] += 1
    lang = max(counts, key=lambda k: counts[k])
    return (lang if counts[lang] >= 5 else None), counts[lang]

def _page_lang(ctx: PageContext) -> str:
    return _canon_lang(getattr(ctx, "lang", "") or "")

def _iter_candidates(ctx: PageContext) -> List[Any]:
    """
    Candidatos a 'partes' con texto: p, span, li, a, blockquote, figcaption, td/th, headings…
    (excluimos <code>, <pre>, elementos muy cortos)
    """
    soup = getattr(ctx, "soup", None)
    out: List[Any] = []
    if soup is None:
        return out
    try:
        tags = ["p","span","li","a","blockquote","figcaption","q","cite","em","strong","td","th"]
        tags += [f"h{i}" for i in range(1,7)]
        for el in soup.find_all(tags):
            out.append(el)
    except Exception:
        pass
    return out

def _find_lang_in_ancestors(node: Any) -> Optional[str]:
    try:
        parent = getattr(node, "parent", None)
        depth = 0
        while parent is not None and depth < 5:
            v = _get_attr(parent, "lang")
            if v:
                return _canon_lang(v)
            parent = getattr(parent, "parent", None); depth += 1
    except Exception:
        pass
    return None

# ------------------------------------------------------------
# RAW (heurístico)
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    3.1.2: Cuando el idioma de un pasaje difiere del de la página, dicho pasaje debe indicarse con lang adecuado.
    RAW:
      - Detecta elementos con @lang y valida formato.
      - Heurística: identifica pasajes cuyo idioma difiere del idioma base y carecen de @lang (o ancestro con @lang).
      - No aplica si no hay evidencia de pasajes en lengua distinta.
    """
    base_lang = _page_lang(ctx)
    candidates = _iter_candidates(ctx)

    has_any_lang_attr = 0
    invalid_lang_attrs = 0
    foreign_segments = 0
    marked_segments = 0
    missing_marks = 0
    offenders: List[Dict[str, Any]] = []

    for el in candidates[:2000]:
        try:
            # validar cualquier lang presente
            lang_here = _canon_lang(_get_attr(el, "lang"))
            if lang_here:
                has_any_lang_attr += 1
                if not _is_valid_bcp47(lang_here):
                    invalid_lang_attrs += 1
                    offenders.append({
                        "selector": _s(getattr(el, "name", "")) + "#" + _s(_get_attr(el, "id")),
                        "lang": lang_here, "reason": "Valor @lang inválido."
                    })

            text = _get_text(el)
            if len(text) < 25:
                continue  # demasiado corto para inferencia
            guessed, conf = _guess_lang(text)

            if not guessed or not base_lang:
                continue

            base = base_lang.split("-")[0]
            if guessed != base:
                foreign_segments += 1
                anc_lang = lang_here or _find_lang_in_ancestors(el)
                if anc_lang:
                    marked_segments += 1
                else:
                    missing_marks += 1
                    offenders.append({
                        "selector": _s(getattr(el, "name", "")) + "#" + _s(_get_attr(el, "id")),
                        "snippet": text[:120],
                        "guessed_lang": guessed,
                        "reason": "Pasaje parece estar en otro idioma pero no está marcado con @lang."
                    })
        except Exception:
            continue

    # Aplicabilidad: si encontramos al menos un pasaje extranjero o hay @lang en partes
    applicable = 1 if (foreign_segments > 0 or has_any_lang_attr > 0) else 0
    violations = missing_marks + invalid_lang_attrs
    passed = (applicable == 0) or (violations == 0)

    ok_ratio = 1.0 if applicable == 0 else (1.0 if passed else 0.0)

    details: Dict[str, Any] = {
        "base_lang": base_lang,
        "applicable": applicable,
        "has_any_lang_attr": has_any_lang_attr,
        "invalid_lang_attrs": invalid_lang_attrs,
        "foreign_segments": foreign_segments,
        "marked_segments": marked_segments,
        "missing_marks": missing_marks,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 3.1.2 busca pasajes cuyo idioma difiera del idioma base y exige @lang. "
            "La detección de idioma es heurística (stopwords ES/EN/PT/FR) — revisar manualmente falsos positivos."
        )
    }
    return details

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede aportar:
      rctx.language_parts_test = [
        { "selector": str, "text": str, "detected_lang": str,
          "has_lang_attr": bool, "lang_attr_value": str|None, "ancestor_lang": str|None }
      ]
    Violación si detected_lang != base_lang (base) y no hay lang_attr (ni ancestro) o lang_attr inválido.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 3.1.2; no se pudo evaluar en modo renderizado."}

    tests = _as_list(getattr(rctx, "language_parts_test", []))
    if not tests:
        d = _compute_counts_raw(rctx)
        d["rendered"] = True
        d["note"] = (d.get("note","") + " | RENDERED: sin 'language_parts_test', se reusó RAW.").strip()
        return d

    base_lang = _canon_lang(getattr(rctx, "lang_runtime", "") or getattr(rctx, "lang", "") or "")
    base = base_lang.split("-")[0] if base_lang else ""

    has_any_lang_attr = 0
    invalid_lang_attrs = 0
    foreign_segments = 0
    marked_segments = 0
    missing_marks = 0
    offenders: List[Dict[str, Any]] = []

    for it in tests:
        if not isinstance(it, dict):
            continue
        det = _canon_lang(_s(it.get("detected_lang")))
        sel = _s(it.get("selector"))
        if det and base and det.split("-")[0] != base:
            foreign_segments += 1
            hv = bool(it.get("has_lang_attr"))
            av = _canon_lang(_s(it.get("lang_attr_value")))
            anc = _canon_lang(_s(it.get("ancestor_lang")))
            if hv or anc:
                marked_segments += 1
                if hv:
                    has_any_lang_attr += 1
                    if not _is_valid_bcp47(av):
                        invalid_lang_attrs += 1
                        offenders.append({"selector": sel, "lang": av, "reason": "@lang inválido (runtime)."})
            else:
                missing_marks += 1
                offenders.append({"selector": sel, "reason": "Pasaje extranjero sin @lang (runtime)."})

    applicable = 1 if (foreign_segments > 0 or has_any_lang_attr > 0) else 0
    violations = missing_marks + invalid_lang_attrs
    passed = (applicable == 0) or (violations == 0)

    ok_ratio = 1.0 if applicable == 0 else (1.0 if passed else 0.0)

    details: Dict[str, Any] = {
        "rendered": True,
        "base_lang": base_lang,
        "applicable": applicable,
        "has_any_lang_attr": has_any_lang_attr,
        "invalid_lang_attrs": invalid_lang_attrs,
        "foreign_segments": foreign_segments,
        "marked_segments": marked_segments,
        "missing_marks": missing_marks,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: verificación de partes con idioma distinto usando detección runtime."
    }
    return details

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False, "ai_message": "IA no configurada."}
    needs = (details.get("missing_marks", 0) or 0) > 0 or (details.get("invalid_lang_attrs", 0) or 0) > 0
    if not needs:
        return {"ai_used": False, "manual_required": False}

    base = _s(details.get("base_lang") or "")
    ctx_json = {
        "base_lang": base,
        "offenders": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2000],
        "examples": [
            '<span lang="en">Sign in</span>',
            '<p lang="fr">Politique de confidentialité</p>',
        ]
    }
    prompt = (
        "Eres auditor WCAG 3.1.2 (Language of Parts). "
        "Para cada offender, sugiere añadir/ajustar @lang con etiqueta BCP47 correcta. "
        "Devuelve JSON: {suggestions:[{selector?, snippet, rationale}], manual_review?:bool, summary?:string}"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_3_1_2(
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
        manual_required = bool(ai.get("manual_review", False))

    applicable = int(details.get("applicable", 0) or 0)
    violations = int(details.get("violations", 0) or 0)
    passed = (applicable == 0) or (violations == 0)

    verdict = verdict_from_counts(details, passed)
    score0 = score_from_verdict(verdict)
    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0, details=details,
        level=meta.get("level","AA"), principle=meta.get("principle","Comprensible"),
        title=meta.get("title","Idioma de las partes"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
