# audits/checks/criteria/p1/c_1_3_6_identify_purpose.py
from typing import Dict, Any, List, Optional, Tuple, Pattern
import re
import unicodedata

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  # si no existe, el modo IA queda deshabilitado

CODE = "1.3.6"

# -------------------------
# Utilidades
# -------------------------

def _as_list(x):
    if not x:
        return []
    if isinstance(x, list):
        return x
    return list(x)

def _get_attr(node: Any, name: str) -> Optional[str]:
    """
    Lee atributo 'name' de dict o bs4.Tag. Tolera listas y None.
    Devuelve str o None.
    """
    try:
        if isinstance(node, dict):
            val = node.get(name)
            if val is None:
                return None
            if isinstance(val, list):
                return " ".join(str(v) for v in val)
            return str(val)
        if hasattr(node, "get"):  # bs4.Tag
            val = node.get(name)  # type: ignore[attr-defined]
            if val is None:
                return None
            if isinstance(val, list):
                return " ".join(str(v) for v in val)
            return str(val)
    except Exception:
        pass
    return None

def _tag_name(node: Any) -> str:
    """Nombre de etiqueta real (dict['tag'] o bs4.Tag.name)."""
    try:
        if isinstance(node, dict):
            t = node.get("tag")
            return str(t).lower() if t else ""
        # bs4.Tag
        if hasattr(node, "name") and node.name:
            return str(node.name).lower()
    except Exception:
        pass
    return ""

def _text_of(node: Any) -> str:
    if isinstance(node, dict):
        for k in ("text", "label", "inner_text", "aria-label", "title"):
            v = node.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""
    if hasattr(node, "get_text"):
        try:
            t = node.get_text()  # type: ignore[attr-defined]
            return t.strip() if isinstance(t, str) else ""
        except Exception:
            pass
    if isinstance(node, str):
        return node
    return ""

def _iter_semantic_regions(ctx) -> List[Any]:
    """
    Devuelve nodos landmark/role reales si hay soup; si no, crea pseudo-nodos
    a partir de ctx.landmarks (Dict[str,bool]).
    """
    soup = getattr(ctx, "soup", None)
    if soup is not None:
        nodes: List[Any] = []
        seen = set()
        # roles ARIA frecuentes
        for r in ("main", "navigation", "banner", "contentinfo", "complementary", "search", "region", "form"):
            try:
                for el in soup.find_all(attrs={"role": r}):
                    if id(el) in seen:
                        continue
                    seen.add(id(el))
                    nodes.append(el)
            except Exception:
                pass
        # landmarks semánticos
        for tag in ("main", "nav", "header", "footer", "aside"):
            try:
                for el in soup.find_all(tag):
                    if id(el) in seen:
                        continue
                    seen.add(id(el))
                    nodes.append(el)
            except Exception:
                pass
        return nodes

    # Fallback: sólo tienes el dict booleano
    lm_map = getattr(ctx, "landmarks", None)
    if isinstance(lm_map, dict):
        pseudo = []
        for name, present in lm_map.items():
            if present:
                pseudo.append({
                    "tag": name,
                    "role": name if name in {"main", "navigation", "banner", "contentinfo", "complementary", "search", "form", "region"} else ""
                })
        return pseudo
    return []

def _bool_attr(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")

def _norm(s: Optional[str]) -> str:
    if not s:
        return ""
    s2 = unicodedata.normalize("NFKD", s)
    s2 = s2.encode("ascii", "ignore").decode("ascii")
    return s2.lower().strip()

def _get_accessible_name(el: Any) -> str:
    """
    Nombre accesible típico para botones/enlaces/icon-buttons:
      - text (visible), aria-label, title, aria-labelledby_text (si lo provee el extractor)
    """
    # Intenta atributos directos
    for k in ("text", "aria-label", "title", "aria_labelledby_text", "aria-labelledby_text"):
        v = _get_attr(el, k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # Fallback al texto visible del nodo
    t = _text_of(el)
    return t

def _is_interactive(el: Any) -> bool:
    tag = _tag_name(el)
    role = (_get_attr(el, "role") or "").lower()

    if tag in {"button", "a", "summary", "input"}:
        if tag == "a":
            href = _get_attr(el, "href") or ""
            if href.strip():
                return True
            ti = _get_attr(el, "tabindex")
            try:
                return int(str(ti)) >= 0
            except Exception:
                return False
        return True
    return role in {
        "button", "link", "menuitem", "menuitemcheckbox", "menuitemradio", "tab", "treeitem",
        "switch", "checkbox", "radio", "option", "slider"
    }

def _is_icon_only(el: Any) -> bool:
    """
    Heurística: control solo-ícono (svg/i) sin nombre accesible.
    """
    name = _norm(_get_accessible_name(el))
    if name:
        return False
    if _bool_attr(_get_attr(el, "icon_only")) or _bool_attr(_get_attr(el, "has_icon")) or _bool_attr(_get_attr(el, "is_icon_button")):
        return True
    txt = _norm(_text_of(el))
    return bool(txt and len(txt) <= 2)  # símbolos como ×, ▶

# -------------------------
# Propósitos comunes (iconos/controles/zonas)
# Basado en 'Common Purposes' de WCAG (no exhaustivo; bilingüe ES/EN).
# -------------------------

_COMMON_PURPOSE_PATTERNS: List[Tuple[Pattern, str]] = [
    # navegación/estructura
    (re.compile(r"\b(home|inicio|principal)\b", re.I), "home"),
    (re.compile(r"\b(menu|men[uú])\b", re.I), "menu"),
    (re.compile(r"\b(search|buscar|busqueda|b[uú]squeda)\b", re.I), "search"),
    (re.compile(r"\b(settings|ajustes|configuraci[oó]n)\b", re.I), "settings"),
    (re.compile(r"\b(help|ayuda|soporte)\b", re.I), "help"),
    (re.compile(r"\b(info|informaci[oó]n)\b", re.I), "info"),

    # acciones comunes
    (re.compile(r"\b(close|cerrar|salir|quitar)\b", re.I), "close"),
    (re.compile(r"\b(back|atr[aá]s|volver)\b", re.I), "back"),
    (re.compile(r"\b(next|siguiente|continuar)\b", re.I), "next"),
    (re.compile(r"\b(prev(io)?|anterior)\b", re.I), "previous"),
    (re.compile(r"\b(edit|editar)\b", re.I), "edit"),
    (re.compile(r"\b(save|guardar)\b", re.I), "save"),
    (re.compile(r"\b(delete|eliminar|borrar)\b", re.I), "delete"),
    (re.compile(r"\b(add|agregar|a[nñ]adir|\+)\b", re.I), "add"),
    (re.compile(r"\b(remove|quitar)\b", re.I), "remove"),
    (re.compile(r"\b(download|descargar)\b", re.I), "download"),
    (re.compile(r"\b(upload|subir)\b", re.I), "upload"),
    (re.compile(r"\b(share|compartir)\b", re.I), "share"),
    (re.compile(r"\b(print|imprimir)\b", re.I), "print"),
    (re.compile(r"\b(filter|filtrar|filtro)\b", re.I), "filter"),
    (re.compile(r"\b(sort|ordenar|orden)\b", re.I), "sort"),
    (re.compile(r"\b(refresh|recargar|actualizar)\b", re.I), "refresh"),
    (re.compile(r"\b(full\s?screen|pantalla completa)\b", re.I), "fullscreen"),
    (re.compile(r"\b(zoom in|acercar)\b", re.I), "zoom-in"),
    (re.compile(r"\b(zoom out|alejar)\b", re.I), "zoom-out"),

    # multimedia
    (re.compile(r"\b(play|reproducir)\b", re.I), "play"),
    (re.compile(r"\b(pause|pausa)\b", re.I), "pause"),
    (re.compile(r"\b(stop|detener)\b", re.I), "stop"),
    (re.compile(r"\b(mute|silencio|silenciar)\b", re.I), "mute"),
    (re.compile(r"\b(unmute|activar sonido)\b", re.I), "unmute"),

    # cuenta/compra
    (re.compile(r"\b(login|log in|iniciar sesi[oó]n|entrar)\b", re.I), "login"),
    (re.compile(r"\b(logout|log out|cerrar sesi[oó]n)\b", re.I), "logout"),
    (re.compile(r"\b(register|sign ?up|registro|crear cuenta)\b", re.I), "signup"),
    (re.compile(r"\b(profile|perfil|account|cuenta)\b", re.I), "account"),
    (re.compile(r"\b(cart|carrito|cesta|basket)\b", re.I), "cart"),
    (re.compile(r"\b(wishlist|lista de deseos)\b", re.I), "wishlist"),

    # comunicación
    (re.compile(r"\b(email|correo)\b", re.I), "email"),
    (re.compile(r"\b(phone|tel[eé]fono|llamar)\b", re.I), "phone"),
    (re.compile(r"\b(chat|mensaje|messaging|conversaci[oó]n)\b", re.I), "chat"),
    (re.compile(r"\b(calendar|calendario|agenda)\b", re.I), "calendar"),

    # marcadores/estado
    (re.compile(r"\b(bookmark|marcador|favorito)\b", re.I), "bookmark"),
    (re.compile(r"\b(star|estrella|favorito)\b", re.I), "star"),
    (re.compile(r"\b(heart|coraz[oó]n|like|me gusta)\b", re.I), "like"),
    (re.compile(r"\b(dislike|no me gusta)\b", re.I), "dislike"),
]

_ICON_CLASS_HINTS = re.compile(
    r"(icon|fa|bi|mdi)[\-\s_:]?(search|close|menu|home|settings|download|upload|print|share|play|pause|stop|cart|trash|delete|edit|save|filter|sort|star|heart)",
    re.I
)

# Landmarks / roles comunes (propósitos de regiones)
_LANDMARK_ROLES = {
    "banner", "main", "contentinfo", "navigation", "search", "complementary", "form", "region"
}

# -------------------------
# Detección de propósitos
# -------------------------

def _map_common_purpose(name_text: str, class_text: str) -> Optional[str]:
    """
    Intenta mapear el nombre accesible (o clases) a un propósito conocido.
    """
    if name_text:
        for pat, token in _COMMON_PURPOSE_PATTERNS:
            if pat.search(name_text):
                return token
    if class_text and _ICON_CLASS_HINTS.search(class_text):
        m = _ICON_CLASS_HINTS.search(class_text)
        if m and len(m.groups()) >= 2:
            return m.group(2).lower()
        return "icon-hint"
    return None

def _collect_interactives(ctx: PageContext) -> List[Any]:
    cands: List[Any] = []
    for src in ("buttons", "links", "widgets", "controls", "focusables"):
        cands.extend(_as_list(getattr(ctx, src, []) or []))
    # eliminar duplicados simples por id/xpath/src
    seen = set()
    out: List[Any] = []
    for el in cands:
        key = _get_attr(el, "id") or _get_attr(el, "xpath") or _get_attr(el, "data-xpath") or _get_attr(el, "src") or str(id(el))
        if key in seen:
            continue
        seen.add(key)
        out.append(el)
    return out

def _collect_regions(ctx: PageContext) -> List[Any]:
    """
    Landmarks reales desde el DOM si es posible; como refuerzo, añade regions/containers
    del extractor (pueden ser dict/Tags).
    """
    regions: List[Any] = _iter_semantic_regions(ctx)
    regions.extend(_as_list(getattr(ctx, "regions", []) or []))
    regions.extend(_as_list(getattr(ctx, "containers", []) or []))
    return regions

# -------------------------
# Núcleo del criterio
# -------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    1.3.6 (AAA): El propósito de componentes de la IU, iconos y regiones debe ser
    determinable programáticamente usando propósitos comunes (landmarks, nombres accesibles, etc.).
    Este check:
      - Verifica que botones/enlaces/icon-buttons tengan nombre accesible y que mapee a propósitos comunes.
      - Señala 'icon-only' sin nombre accesible (falta de propósito determinable).
      - Detecta landmarks adecuados (navigation, search, main, etc.) y gaps evidentes.
    """
    interactives = _collect_interactives(ctx)
    regions = _collect_regions(ctx)

    # ---- Controles / iconos
    icons_examined = 0
    icons_missing_name = 0
    icons_with_common_purpose = 0
    icons_unknown_purpose = 0
    icon_offenders: List[Dict[str, Any]] = []

    for el in interactives:
        if not _is_interactive(el):
            continue
        icons_examined += 1
        tag = _tag_name(el) or (_get_attr(el, "role") or "")
        classes = (_get_attr(el, "class") or "").lower()
        name = _get_accessible_name(el)

        if _is_icon_only(el):
            icons_missing_name += 1
            icon_offenders.append({
                "tag": tag,
                "id": _get_attr(el, "id") or "",
                "class": _get_attr(el, "class") or "",
                "reason": "Control solo-ícono sin nombre accesible (propósito no determinable)."
            })
            continue

        purpose = _map_common_purpose(name, classes)
        if purpose:
            icons_with_common_purpose += 1
        else:
            # Nombre hay, pero no lo podemos mapear a lista común → requiere revisión
            icons_unknown_purpose += 1
            icon_offenders.append({
                "tag": tag,
                "id": _get_attr(el, "id") or "",
                "label": (name or "")[:120],
                "reason": "Nombre accesible presente pero no mapea a propósito común conocido (revisión)."
            })

    # ---- Regiones / Landmarks
    landmarks_detected = 0
    landmark_gaps = 0
    region_offenders: List[Dict[str, Any]] = []

    for r in regions:
        role = (_get_attr(r, "role") or "").lower()
        tag = _tag_name(r)
        cls = (_get_attr(r, "class") or "").lower()
        name = _norm(_get_attr(r, "aria-label") or _get_attr(r, "label") or _get_attr(r, "name") or "")

        # Caso 1: landmark correcto
        if role in _LANDMARK_ROLES or tag in _LANDMARK_ROLES or tag in {"header", "footer", "nav", "main", "aside"}:
            landmarks_detected += 1
            # 'region' y 'form' requieren nombre para ser útiles como destino → si no lo tienen, es gap
            if role in {"region", "form"} and not name:
                landmark_gaps += 1
                region_offenders.append({
                    "tag": tag or role,
                    "role": role or tag,
                    "id": _get_attr(r, "id") or "",
                    "reason": "Landmark genérico ('region'/'form') sin nombre accesible (menos determinable)."
                })
            continue

        # Caso 2: sospechoso por clases pero sin landmark (gap)
        if any(k in cls for k in ("nav", "menu", "header", "footer", "sidebar", "aside", "search", "navbar", "topbar", "masthead", "breadcrumb")):
            landmark_gaps += 1
            region_offenders.append({
                "tag": tag or role or "div",
                "id": _get_attr(r, "id") or "",
                "class": _get_attr(r, "class") or "",
                "reason": "Contenedor con clases de navegación/estructura sin landmark apropiado (p.ej., <nav>, role='navigation')."
            })

    # ---- (Opcional) Propósitos de entradas por tokens de 1.3.5 (solo para reporting)
    controls = _as_list(getattr(ctx, "form_controls", []) or getattr(ctx, "inputs", []) or [])
    input_tokens = 0
    for c in controls:
        ac = (_get_attr(c, "autocomplete") or _get_attr(c, "autoComplete") or _get_attr(c, "data-autocomplete") or "").strip().lower()
        if ac:
            parts = [p for p in re.split(r"\s+", ac) if p]
            base = parts[-1] if parts else ""
            if base in {
                "name","honorific-prefix","given-name","additional-name","family-name","honorific-suffix","nickname",
                "username","new-password","current-password","one-time-code",
                "email","impp","photo","url","language",
                "tel","tel-country-code","tel-national","tel-area-code","tel-local","tel-local-prefix","tel-local-suffix","tel-extension",
                "organization","organization-title",
                "street-address","address-line1","address-line2","address-line3",
                "address-level1","address-level2","address-level3","address-level4",
                "country","country-name","postal-code",
                "bday","bday-day","bday-month","bday-year","sex",
                "cc-name","cc-given-name","cc-additional-name","cc-family-name","cc-number","cc-exp","cc-exp-month","cc-exp-year","cc-csc","cc-type",
                "transaction-currency","transaction-amount",
            }:
                input_tokens += 1

    # ---- Métricas y resultado RAW
    violations = icons_missing_name + landmark_gaps  # violaciones duras
    ok_ratio = 1.0
    denom = (icons_examined or 0) + (landmarks_detected or 0)
    if denom > 0:
        ok_ratio = round(max(0.0, min(1.0,
            ((icons_examined - icons_missing_name) + (landmarks_detected - landmark_gaps)) / max(1, denom)
        )), 4)

    details: Dict[str, Any] = {
        "icons_examined": icons_examined,
        "icons_missing_name": icons_missing_name,
        "icons_with_common_purpose": icons_with_common_purpose,
        "icons_unknown_purpose": icons_unknown_purpose,
        "landmarks_detected": landmarks_detected,
        "landmark_gaps": landmark_gaps,
        "input_purpose_tokens": input_tokens,  # informativo (de 1.3.5)
        "ok_ratio": ok_ratio,
        "offenders": icon_offenders + region_offenders,
        "note": (
            "RAW: 1.3.6 (AAA) verifica que el propósito de componentes de IU e iconos sea determinable "
            "programáticamente (nombres accesibles mapeados a propósitos comunes; landmarks apropiados). "
            "Falla duro si hay controles solo-ícono sin nombre o contenedores obvios sin landmark. "
            "Nombres no mapeables se marcan para revisión (pueden ser válidos según contexto)."
        )
    }

    # N/A si no hay absolutamente nada que revisar (sin interactivos NI landmarks/gaps)
    if icons_examined == 0 and (landmarks_detected + landmark_gaps) == 0:
        details["na"] = True

    return details

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED puedes:
      - Confirmar nombre accesible computado (AOM) de controles/icon-buttons.
      - Detectar icon-only por inspección del árbol accesible (role=img/graphics-symbol sin name).
      - Verificar landmarks reales presentes en el Accessibility Tree.
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.3.6; no se pudo evaluar en modo renderizado."}
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note", "") + " | RENDERED: usa árbol accesible para confirmar nombres/roles y landmarks.").strip()
    return d

# -------------------------
# IA opcional
# -------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    Propón:
      - aria-label/texto para icon-only (e.g., 'Cerrar', 'Buscar').
      - Mapeo de nombres a propósitos comunes cuando no se detectó automáticamente.
      - Landmarks adecuados para contenedores (p.ej., <nav>, role='navigation', role='search').
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    offenders = details.get("offenders", []) or []
    if not offenders:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "offenders": offenders[:20],
        "html_snippet": (html_sample or "")[:2500],
        "hint_purposes": [t for _, t in _COMMON_PURPOSE_PATTERNS][:30],
        "landmark_roles": sorted(list(_LANDMARK_ROLES)),
    }
    prompt = (
        "Actúa como auditor WCAG 1.3.6 (Identificar el propósito). "
        "Para cada offender, propone: 1) aria-label/texto visible adecuado si es icon-only; "
        "2) un propósito común sugerido (search, close, settings, etc.) basado en el snippet; "
        "3) landmark/role sugerido para contenedores ('navigation','search','main','banner','contentinfo'). "
        "Devuelve JSON: { suggestions: [{type, id?, tag?, reason, fix_html?, aria_label?, role?}], "
        "manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": True}  # AAA → casi siempre requiere revisión
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": True}

# -------------------------
# Orquestación
# -------------------------

def run_1_3_6(
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
    if details.get("na") is True:
        verdict = "na"
        passed = False               # 'pass' solo cuando pasa de verdad
        score0 = score_from_verdict(verdict)
        score_hint = None
    else:
        violations = int(details.get("icons_missing_name", 0)) + int(details.get("landmark_gaps", 0))
        passed = (violations == 0)
        verdict = verdict_from_counts(details, passed)
        score0 = score_from_verdict(verdict)
        score_hint = details.get("ok_ratio")

    meta = WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE,
        passed=(verdict == "pass"),
        verdict=verdict,
        score_0_2=score0,
        details=details,
        level=meta.get("level", "AAA"),
        principle=meta.get("principle", "Perceptible"),
        title=meta.get("title", "Identificar el propósito"),
        source=src,
        score_hint=score_hint,
        manual_required=manual_required or (details.get("icons_unknown_purpose", 0) > 0)
    )
