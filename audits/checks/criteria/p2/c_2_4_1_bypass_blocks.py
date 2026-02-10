# audits/checks/criteria/p2/c_2_4_1_bypass_blocks.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.4.1"

# -------------------------------------------------------------------
# Utilidades
# -------------------------------------------------------------------

_SKIP_TEXT_HINTS = (
    "skip to content","skip content","skip navigation","skip nav","jump to content",
    "omitir navegacion","omitir navegación","omitir menu","omitir menú",
    "saltar a contenido","ir al contenido","ir directamente al contenido",
    "ir al contenido principal","contenido principal","saltar contenido",
    "ir al inicio del contenido","saltarse navegación",
)
_SKIP_CLASS_HINTS = ("skip-link","skiplink","skip-nav","visually-hidden-focusable","sr-only-focusable")

_MAIN_ID_HINTS = ("main","contenido","content","primary","principal","main-content","contenido-principal","contenido_principal")
_TOC_HINTS = ("table of contents", "contenido", "índice", "indice", "sumario", "contents")

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

def _get_attr(node: Any, name: str) -> Optional[str]:
    """
    Lectura segura de atributos desde dict o Tag de BeautifulSoup.
    """
    try:
        if isinstance(node, dict):
            val = node.get(name)
            return _s(val) if (val is not None) else None
        if hasattr(node, "get"):
            val = node.get(name)  # type: ignore[attr-defined]
            return _s(val) if (val is not None) else None
    except Exception:
        pass
    return None

def _get_text(node: Any) -> str:
    try:
        if isinstance(node, dict):
            # algunos extractores ponen 'text'/'label'
            for k in ("text","label","aria-label","title"):
                v = node.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            return ""
        # Tag bs4
        if hasattr(node, "get_text"):
            t = node.get_text()  # type: ignore[attr-defined]
            if isinstance(t, str):
                return t.strip()
        # fallback: aria-label/title
        for k in ("aria-label","title"):
            v = _get_attr(node, k)
            if v:
                return v.strip()
    except Exception:
        pass
    return ""

def _href_is_fragment(href: Optional[str]) -> bool:
    if not href:
        return False
    h = href.strip()
    return h.startswith("#") and len(h) > 1

def _fragment_target_exists(ctx: PageContext, frag: str) -> bool:
    """
    Verifica si existe algún elemento con id/name que coincida con el fragmento.
    Heurística ligera para Tag o dict.
    """
    target = frag.lstrip("#").strip()
    if not target:
        return False
    soup = getattr(ctx, "soup", None)
    if soup is not None:
        try:
            # id o name
            if soup.find(id=target) or soup.find(attrs={"name": target}):
                return True
        except Exception:
            pass
    # Busca también en hints de main
    return target.lower() in _MAIN_ID_HINTS

def _looks_skip_link(a: Any, ctx: PageContext) -> Tuple[bool, Optional[str]]:
    """
    Decide si <a> parece un skip link válido. Devuelve (es_skip, href).
    """
    txt = _lower(_get_text(a))
    cls = _lower(_get_attr(a, "class"))
    href = _get_attr(a, "href")
    rel = _lower(_get_attr(a, "rel"))
    aria = _lower(_get_attr(a, "aria-label"))
    title = _lower(_get_attr(a, "title"))

    # Debe ser fragmento interno
    if not _href_is_fragment(href):
        return (False, None)

    # Texto/clase/aria/title con pistas
    has_hint = any(h in txt for h in _SKIP_TEXT_HINTS) or any(h in cls for h in _SKIP_CLASS_HINTS) \
               or any(h in aria for h in _SKIP_TEXT_HINTS) or any(h in title for h in _SKIP_TEXT_HINTS) \
               or ("noopener" in rel and any(h in txt for h in ("skip","omitir","saltar","ir al contenido")))

    if not has_hint:
        return (False, None)

    # El objetivo debe existir (o ser un id típico de 'main')
    if not _fragment_target_exists(ctx, _s(href)):
        return (False, None)

    return (True, href)

def _has_main_landmark(ctx: PageContext) -> bool:
    """
    Consideramos que la presencia de un landmark 'main' correctamente marcado ayuda a bypass,
    especialmente junto a skip-link (pero aquí lo contamos como mecanismo válido también).
    """
    lm = getattr(ctx, "landmarks", {}) or {}
    if bool(lm.get("main")):
        return True
    # busquemos hints de main en el DOM
    soup = getattr(ctx, "soup", None)
    if soup is not None:
        try:
            if soup.find("main") or soup.find(attrs={"role": "main"}):
                return True
            # ids típicos
            for hint in _MAIN_ID_HINTS:
                if soup.find(id=re.compile(rf"^{re.escape(hint)}$", re.I)):
                    return True
        except Exception:
            pass
    return False

def _has_toc_near_top(ctx: PageContext) -> bool:
    """
    Heurística: ¿hay un índice de contenidos (TOC) detectable por texto/aria en un nav/list?
    """
    soup = getattr(ctx, "soup", None)
    if soup is None:
        return False
    try:
        # Busca nav/aside/section con aria-label o encabezado que sugiera TOC
        candidates = soup.find_all(["nav","aside","section"])
        for n in candidates[:6]:  # cerca del comienzo
            label = (_get_attr(n, "aria-label") or "").strip().lower()  # type: ignore[arg-type]
            if any(k in label for k in _TOC_HINTS):
                return True
            # Encabezado interno
            h = n.find(re.compile(r"^h[1-6]$", re.I))
            htxt = (h.get_text() or "").strip().lower() if h else ""
            if any(k in htxt for k in _TOC_HINTS):
                return True
        return False
    except Exception:
        return False

def _nav_like_present(ctx: PageContext) -> bool:
    """
    ¿Hay señales de bloques repetidos? (nav/banner/search)
    Si hay navegación/banner, consideramos el criterio aplicable.
    """
    lm = getattr(ctx, "landmarks", {}) or {}
    if any(bool(lm.get(k)) for k in ("nav","banner","search","contentinfo","complementary")):
        return True
    # fallback por DOM
    soup = getattr(ctx, "soup", None)
    if soup is not None:
        try:
            if soup.find("nav") or soup.find(attrs={"role": "navigation"}):
                return True
        except Exception:
            pass
    return False

# -------------------------------------------------------------------
# Recolección (RAW)
# -------------------------------------------------------------------

def _collect_skip_links(ctx: PageContext) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for a in _as_list(getattr(ctx, "anchors", [])):
        try:
            ok, href = _looks_skip_link(a, ctx)
            if ok:
                out.append({
                    "text": _get_text(a)[:140],
                    "href": href,
                    "class": _get_attr(a, "class"),
                })
        except Exception:
            continue
    # fallback: buscar <a class="skip-link"> aunque no esté en ctx.anchors
    if not out:
        soup = getattr(ctx, "soup", None)
        if soup is not None:
            try:
                for a in soup.find_all("a", class_=re.compile(r"(skip\-?link|skip\-?nav|sr\-only\-focusable)", re.I)):
                    ok, href = _looks_skip_link(a, ctx)
                    if ok:
                        out.append({
                            "text": (a.get_text() or "")[:140],
                            "href": href,
                            "class": a.get("class")
                        })
            except Exception:
                pass
    return out

# -------------------------------------------------------------------
# Evaluación (RAW)
# -------------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.4.1 (A): Proveer mecanismo para saltar bloques repetidos (p. ej., 'skip to content',
    landmarks 'main', índices de contenido al inicio, etc.). Consideramos el criterio
    aplicable si hay señales de navegación/banner típicas.
    Cumple si existe al menos uno: skip-link válido, landmark 'main', o TOC al inicio.
    """
    applicable = 1 if _nav_like_present(ctx) else 0

    skip_links = _collect_skip_links(ctx)
    has_main = _has_main_landmark(ctx)
    has_toc = _has_toc_near_top(ctx)

    mechanisms = {
        "skip_links": len(skip_links),
        "has_main_landmark": bool(has_main),
        "has_toc_near_top": bool(has_toc),
    }
    has_any_mechanism = (len(skip_links) > 0) or has_main or has_toc

    offenders: List[Dict[str, Any]] = []
    if applicable and not has_any_mechanism:
        offenders.append({
            "reason": "Se detectan bloques de navegación/banner pero no hay 'skip link', landmark 'main' ni índice cercano al inicio.",
            "hints": {
                "landmarks": getattr(ctx, "landmarks", {}),
                "anchors_examined": len(_as_list(getattr(ctx, "anchors", [])))
            }
        })

    ok_ratio = 1.0 if applicable == 0 else (1.0 if has_any_mechanism else 0.0)

    details: Dict[str, Any] = {
        "applicable": applicable,
        "mechanisms": mechanisms,
        "skip_links_found": skip_links,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 2.4.1 requiere un mecanismo para saltar bloques repetidos. "
            "Se acepta 'skip link' a contenido principal, landmark 'main' o un índice (TOC) al inicio."
        )
    }
    return details

# -------------------------------------------------------------------
# RENDERED (verificación en ejecución)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede exponer:
      rctx.bypass_blocks_test = [
        {
          "mechanism": "skip_link|main_landmark|toc",
          "activated": bool,               # se pudo activar (e.g., Tab + Enter)
          "moved_focus_or_scroll": bool,   # foco/scroll llegó al contenido principal
          "target_focusable": bool,        # el destino tiene tabindex/role/heading alcanzable
          "notes": str
        }, ...
      ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.4.1; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    tests = _as_list(getattr(rctx, "bypass_blocks_test", []))
    if not tests:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'bypass_blocks_test'.").strip()
        return d

    applicable = int(d.get("applicable", 0) or 0)
    compliant = 0
    offenders: List[Dict[str, Any]] = []

    for t in tests:
        if not isinstance(t, dict):
            continue
        mech = _lower(t.get("mechanism") or "")
        activated = bool(t.get("activated"))
        moved = bool(t.get("moved_focus_or_scroll"))
        focusable = bool(t.get("target_focusable"))

        ok = activated and (moved or focusable)
        if ok:
            compliant += 1
        else:
            offenders.append({
                "mechanism": mech or "unknown",
                "reason": "El mecanismo no movió el foco/scroll al contenido principal o el destino no fue alcanzable.",
                "observed": {
                    "activated": activated,
                    "moved_focus_or_scroll": moved,
                    "target_focusable": focusable,
                }
            })

    # Si hay al menos un mecanismo efectivo, aprobamos (cuando es aplicable)
    has_effective = compliant > 0
    ok_ratio = 1.0 if applicable == 0 else (1.0 if has_effective else 0.0)

    d.update({
        "compliant_mechanisms": compliant,
        "ok_ratio": ok_ratio,
        "offenders": (_as_list(d.get("offenders")) + offenders),
        "note": (d.get("note","") + " | RENDERED: validación de activación real y llegada al contenido principal.").strip()
    })
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: sugiere añadir 'skip link' y/o landmark 'main', o un TOC al inicio.
    - Ejemplo de skip link: <a class="skip-link" href="#main">Saltar al contenido principal</a>
    - Asegurar destino: <main id="main">...</main> (o role="main")
    - Hacer visible al foco: utilidades 'visually-hidden' que se muestran al recibir :focus
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    needs = (details.get("applicable", 0) == 1) and (not details.get("mechanisms", {}).get("has_main_landmark")) \
            and (details.get("mechanisms", {}).get("skip_links", 0) == 0) \
            and (not details.get("mechanisms", {}).get("has_toc_near_top"))

    if not needs:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "missing": {
            "skip_links": details.get("mechanisms", {}).get("skip_links", 0) == 0,
            "main_landmark": not details.get("mechanisms", {}).get("has_main_landmark", False),
            "toc": not details.get("mechanisms", {}).get("has_toc_near_top", False),
        },
        "html_snippet": (html_sample or "")[:2000],
        "examples": {
            "skip_link": '<a class="skip-link" href="#main">Saltar al contenido principal</a>',
            "main": '<main id="main" tabindex="-1">...</main>',
            "css_focusable": ".skip-link{position:absolute;left:-9999px}.skip-link:focus{left:0;}",
        }
    }
    prompt = (
        "Eres auditor WCAG 2.4.1 (Bypass Blocks). "
        "Propón cambios mínimos para añadir un mecanismo de bypass: skip link + destino main y/o TOC inicial. "
        "Incluye HTML/CSS sugerido y breve racional. "
        "Devuelve JSON: { suggestions: [{snippet, rationale}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_2_4_1(
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
        manual_required = bool(ai_info.get("manual_required", False))

    # 3) passed / verdict / score
    applicable = int(details.get("applicable", 0) or 0)
    mechanisms = details.get("mechanisms", {}) or {}
    has_any = bool(mechanisms.get("has_main_landmark")) or (int(mechanisms.get("skip_links", 0) or 0) > 0) or bool(mechanisms.get("has_toc_near_top"))

    passed = (applicable == 0) or has_any

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
        title=meta.get("title", "Evitar bloques"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
