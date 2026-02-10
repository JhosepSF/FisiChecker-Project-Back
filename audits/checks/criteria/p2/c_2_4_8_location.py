# audits/checks/criteria/p2/c_2_4_8_location.py
from typing import Dict, Any, List, Optional, Tuple
import re
from urllib.parse import urlparse

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.4.8"

# -------------------------------------------------------------
# Utilidades
# -------------------------------------------------------------

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
    """Lectura segura de atributos desde dict o Tag (BeautifulSoup)."""
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
    """Texto visible aproximado."""
    if isinstance(node, dict):
        for k in ("text","label","aria-label","title","accessible_name","inner_text"):
            v = node.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""
    try:
        if hasattr(node, "get_text"):
            t = node.get_text()  # type: ignore[attr-defined]
            if isinstance(t, str) and t.strip():
                return t.strip()
        for k in ("aria-label","title"):
            v = _get_attr(node, k)
            if v:
                return v.strip()
    except Exception:
        pass
    return ""

def _collect_links(ctx: PageContext) -> List[Any]:
    links = _as_list(getattr(ctx, "anchors", []))
    if links:
        return links
    soup = getattr(ctx, "soup", None)
    if soup is not None:
        try:
            return list(soup.find_all("a"))
        except Exception:
            pass
    return []

# -------------------------------------------------------------
# Detección de mecanismos que proporcionan “ubicación”
# -------------------------------------------------------------

# Migas de pan (breadcrumbs)
def _has_breadcrumbs(ctx: PageContext) -> Tuple[bool, Dict[str, Any]]:
    soup = getattr(ctx, "soup", None)
    meta = {"aria_breadcrumb": False, "class_breadcrumb": False, "schema_breadcrumb": False, "examples": []}
    found = False
    if soup is not None:
        try:
            nav_bc = soup.find("nav", attrs={"aria-label": re.compile(r"breadcrumb|migas", re.I)})
            if nav_bc:
                meta["aria_breadcrumb"] = True; found = True
                # extrae un ejemplo
                ex = " / ".join([_get_text(a) for a in nav_bc.find_all("a")[:4]])  # type: ignore[attr-defined]
                if ex.strip(): meta["examples"].append(ex[:160])

            cls_bc = soup.find(attrs={"class": re.compile(r"\bbreadcrumb(s)?\b", re.I)})
            if cls_bc:
                meta["class_breadcrumb"] = True; found = True
                ex = " / ".join([_get_text(a) for a in cls_bc.find_all("a")[:4]])  # type: ignore[attr-defined]
                if ex.strip(): meta["examples"].append(ex[:160])

            schema_bc = soup.find(attrs={"itemtype": re.compile(r"BreadcrumbList", re.I)})
            if schema_bc:
                meta["schema_breadcrumb"] = True; found = True
        except Exception:
            pass
    return found, meta

# “Ubicación actual” indicada en navegación (aria-current / estado activo)
def _has_nav_current(ctx: PageContext) -> Tuple[bool, Dict[str, Any]]:
    soup = getattr(ctx, "soup", None)
    meta = {"aria_current_page": 0, "active_class": 0, "examples": []}
    found = False
    if soup is not None:
        try:
            # aria-current="page" o "true"
            cur = soup.find_all(attrs={"aria-current": re.compile(r"^(page|true)$", re.I)})
            meta["aria_current_page"] = len(cur)
            if cur:
                found = True
                for el in cur[:3]:
                    txt = _get_text(el)
                    href = _get_attr(el, "href") or ""
                    meta["examples"].append((txt or href)[:160])

            # clases “active/selected/current” en ítems de nav
            active = soup.find_all(attrs={"class": re.compile(r"\b(active|current|selected)\b", re.I)})
            meta["active_class"] = len(active)
            if active:
                found = True
        except Exception:
            pass
    return found, meta

# Título con jerarquía / ubicación (“Sección — Página — Sitio”)
_SEPARATORS = (" — ", " – ", " | ", " · ", " :: ", " - ")

def _title_has_location(ctx: PageContext) -> Tuple[bool, Dict[str, Any]]:
    title = _s(getattr(ctx, "document_title", "") or getattr(ctx, "title_text", ""))
    site = ""
    soup = getattr(ctx, "soup", None)
    if soup is not None:
        try:
            og_site = soup.find("meta", attrs={"property": re.compile(r"^og:site_name$", re.I)})
            if og_site:
                site = _s(og_site.get("content"))
            if not site:
                app = soup.find("meta", attrs={"name": re.compile(r"^application\-name$", re.I)})
                if app:
                    site = _s(app.get("content"))
        except Exception:
            pass
    parts = [title]
    for sep in _SEPARATORS:
        if sep in title:
            parts = [p.strip() for p in title.split(sep) if p.strip()]
            break
    # Señal: 2+ partes y/o incluye el nombre del sitio o sección previa
    includes_site = bool(site) and any(site.lower() in p.lower() for p in parts)
    looks_hier = len(parts) >= 2
    return (looks_hier or includes_site), {"title": title, "parts": parts, "includes_site": includes_site}

# URL con “migajas” comprensibles (informativo; no suficiente por sí solo)
def _url_hints(ctx: PageContext) -> Tuple[bool, Dict[str, Any]]:
    url = _s(getattr(ctx, "current_url", ""))
    if not url:
        # algunos extractores dejan en soup.base/og:url
        soup = getattr(ctx, "soup", None)
        if soup is not None:
            try:
                og = soup.find("meta", attrs={"property": re.compile(r"^og:url$", re.I)})
                if og:
                    url = _s(og.get("content"))
            except Exception:
                pass
    if not url:
        return False, {"url": None}

    try:
        p = urlparse(url)
        segs = [s for s in p.path.split("/") if s]
        humanish = 0
        for s in segs:
            # evitamos puramente numéricos o IDs
            if re.match(r"^[a-z0-9\-_.]{3,}$", s, re.I) and not re.match(r"^\d+$", s):
                humanish += 1
        return (len(segs) >= 2 and humanish >= 1), {"url": url, "segments": segs, "humanish": humanish}
    except Exception:
        return False, {"url": url, "error": "parse-failed"}

# ¿Aplica el criterio? (parte de un conjunto de páginas)
def _is_part_of_set(ctx: PageContext) -> bool:
    # Se asume aplicable si hay navegación global/breadcrumbs o si la URL sugiere estructura
    soup = getattr(ctx, "soup", None)
    lm = getattr(ctx, "landmarks", {}) or {}
    has_nav = bool(lm.get("nav"))
    has_bc, _ = _has_breadcrumbs(ctx)
    url_ok, _ = _url_hints(ctx)
    # también si hay <nav> en DOM
    if not has_nav and soup is not None:
        try:
            has_nav = bool(soup.find("nav") or soup.find(attrs={"role": re.compile(r"^navigation$", re.I)}))
        except Exception:
            pass
    return has_nav or has_bc or url_ok

# -------------------------------------------------------------
# RAW
# -------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    2.4.8 (AAA): La información sobre la ubicación del usuario dentro de un conjunto de páginas está disponible.
    Suficientes (heurísticas):
      - Migas de pan (breadcrumbs).
      - Indicación de ubicación actual en la navegación (p. ej., aria-current="page", item activo/seleccionado).
      - Título que refleje jerarquía (p. ej., “Artículo — Sección — Sitio”).
      - (Informativo) URL con segmentos legibles que indiquen jerarquía.
    Pasa si existe AL MENOS UNO de los mecanismos principales (breadcrumbs / nav actual / título jerárquico).
    """
    applicable = 1 if _is_part_of_set(ctx) else 0

    bc, meta_bc = _has_breadcrumbs(ctx)
    navc, meta_nav = _has_nav_current(ctx)
    tit, meta_title = _title_has_location(ctx)
    urlh, meta_url = _url_hints(ctx)

    mechanisms = []
    if bc: mechanisms.append("breadcrumbs")
    if navc: mechanisms.append("nav_current")
    if tit: mechanisms.append("title_hierarchy")
    # url_hints lo reportamos como apoyo, no lo contamos para “pasa” por sí solo

    offenders: List[Dict[str, Any]] = []
    passed = (applicable == 0) or (len(mechanisms) >= 1)
    if applicable == 1 and not passed:
        offenders.append({
            "reason": "No se detectó ningún mecanismo claro de ubicación (breadcrumbs, nav actual o título jerárquico).",
            "hints": {"url_hints": meta_url}
        })

    ok_ratio = 1.0 if applicable == 0 else (1.0 if passed else 0.0)

    details: Dict[str, Any] = {
        "applicable": applicable,
        "mechanisms_found": mechanisms,
        "meta": {
            "breadcrumbs": meta_bc,
            "nav_current": meta_nav,
            "title_hierarchy": meta_title,
            "url_hints": meta_url
        },
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: 2.4.8 verifica la disponibilidad de información de ubicación (breadcrumbs, estado actual en navegación, "
            "título con jerarquía). La URL legible se reporta como apoyo informativo."
        )
    }
    return details

# -------------------------------------------------------------
# RENDERED
# -------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede aportar señales runtime:
      rctx.location_test = {
        "breadcrumbs_runtime": bool,
        "nav_current_runtime": bool,     # encontró aria-current='page' tras montaje JS
        "title_hierarchy_runtime": bool  # document.title con jerarquía tras SPA routing
      }
    Si no se provee, se reusa RAW en el contexto renderizado.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.4.8; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    lt = getattr(rctx, "location_test", None)
    if not isinstance(lt, dict):
        d["note"] = (d.get("note","") + " | RENDERED: sin 'location_test', se reusó RAW.").strip()
        return d

    runtime_mechs = []
    if bool(lt.get("breadcrumbs_runtime")): runtime_mechs.append("breadcrumbs")
    if bool(lt.get("nav_current_runtime")): runtime_mechs.append("nav_current")
    if bool(lt.get("title_hierarchy_runtime")): runtime_mechs.append("title_hierarchy")

    merged = sorted(set(_as_list(d.get("mechanisms_found"))) | set(runtime_mechs))
    d["mechanisms_found"] = merged

    applicable = int(d.get("applicable", 0) or 0)
    passed = (applicable == 0) or (len(merged) >= 1)
    d["ok_ratio"] = 1.0 if applicable == 0 else (1.0 if passed else 0.0)

    if applicable == 1 and not passed:
        d["offenders"] = _as_list(d.get("offenders")) + [{
            "reason": "En ejecución tampoco se detectó mecanismo claro de ubicación."
        }]

    d["note"] = (d.get("note","") + " | RENDERED: señales de ubicación tras carga JS / routing.").strip()
    return d

# -------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: sugiere añadir breadcrumbs, marcar el ítem actual en la navegación con aria-current,
    o reflejar jerarquía en <title>. Proporciona snippets mínimos.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    applicable = int(details.get("applicable", 0) or 0)
    has_mech = len(_as_list(details.get("mechanisms_found"))) >= 1
    if applicable == 0 or has_mech:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "meta": details.get("meta", {}),
        "html_snippet": (html_sample or "")[:2200],
        "snippets": {
            "breadcrumbs": (
                "<nav aria-label=\"breadcrumb\">\n"
                "  <ol class=\"breadcrumb\">\n"
                "    <li><a href=\"/\">Inicio</a></li>\n"
                "    <li><a href=\"/seccion/\">Sección</a></li>\n"
                "    <li aria-current=\"page\">Página actual</li>\n"
                "  </ol>\n"
                "</nav>"
            ),
            "nav_current": "<a href=\"/ruta/actual\" aria-current=\"page\">Página actual</a>",
            "title_hierarchy": "<!-- Actualiza el <title> -->\n<title>Página — Sección — Sitio</title>"
        }
    }
    prompt = (
        "Eres auditor WCAG 2.4.8 (Location, AAA). "
        "Propón cómo añadir breadcrumbs, marcar el ítem actual en la navegación con aria-current='page' y/o "
        "reflejar jerarquía en <title>. Devuelve JSON: { suggestions: [{mechanism, snippet, rationale}], "
        "manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------

def run_2_4_8(
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
        manual_required = bool(ai_info.get("manual_review", False))

    # 3) passed / verdict / score
    applicable = int(details.get("applicable", 0) or 0)
    has_mechanism = len(_as_list(details.get("mechanisms_found"))) >= 1
    passed = (applicable == 0) or has_mechanism

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
        principle=meta.get("principle", "Operable"),
        title=meta.get("title", "Ubicación"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
