# audits/checks/criteria/p1/c_1_3_1_info_and_relationships.py
from typing import Dict, Any, List, Optional
import re
from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict

# IA opcional 
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None  # si no existe, el modo IA queda deshabilitado

CODE = "1.3.1"

# -------------------------
# Utilidades
# -------------------------

def _get_attr(node: Any, name: str) -> Optional[str]:
    """Lee un atributo de dict o BeautifulSoup.Tag; tolera listas y None."""
    try:
        if isinstance(node, dict):
            val = node.get(name)
            if val is None: return None
            if isinstance(val, list):
                return " ".join(str(x) for x in val)
            return str(val)
        if hasattr(node, "get"):  # bs4.Tag
            val = node.get(name)  # type: ignore[attr-defined]
            if val is None: return None
            if isinstance(val, list):
                return " ".join(str(x) for x in val)
            return str(val)
    except Exception:
        pass
    return None

def _iter_landmarks(ctx) -> List[Any]:
    """
    Devuelve una lista de nodos landmark reales. Prioriza:
      1) ctx.landmark_nodes si existe,
      2) buscar en soup por role y por tags semánticos,
      3) como último recurso, convierte el dict ctx.landmarks {name:bool} a
         pseudo-nodos {'tag': name, 'role': name|''} sólo para no romper el flujo.
    """
    # 1) Si el extractor ya te da nodos:
    lm_nodes = getattr(ctx, "landmark_nodes", None)
    if isinstance(lm_nodes, list) and lm_nodes:
        return lm_nodes

    out: List[Any] = []
    soup = getattr(ctx, "soup", None)
    if soup is not None:
        seen = set()
        # roles explícitos
        for r in ("main", "navigation", "banner", "contentinfo", "complementary", "search"):
            try:
                for el in soup.find_all(attrs={"role": r}):
                    if id(el) in seen: continue
                    seen.add(id(el)); out.append(el)
            except Exception:
                pass
        # landmarks semánticos
        for tag in ("main", "nav", "header", "footer", "aside"):
            try:
                for el in soup.find_all(tag):
                    if id(el) in seen: continue
                    seen.add(id(el)); out.append(el)
            except Exception:
                pass

    if out:
        return out

    # 3) Fallback: si sólo hay el dict booleano, devuelve 'pseudo-nodos'
    lm_map = getattr(ctx, "landmarks", None)
    if isinstance(lm_map, dict):
        pseudo = []
        for name, present in lm_map.items():
            if present:
                pseudo.append({"tag": name, "role": name if name in {"main","navigation","banner","contentinfo","complementary","search"} else ""})
        return pseudo
    return []

def _bool_attr(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")

def _group_has_legend(members: List[Dict[str, Any]]) -> bool:
    """
    Revisa si algún control del grupo está dentro de un <fieldset> con <legend>
    o si el extractor ya marcó la existencia de leyenda a nivel de grupo/miembro.
    """
    candidate_flags = (
        "in_fieldset",
        "has_fieldset_legend",
        "group_has_legend",
        "fieldset_has_legend",
        "has_legend",
    )
    for mem in members:
        for k in candidate_flags:
            if _bool_attr(mem.get(k)):
                return True
    return False

def _as_list(x) -> List[Dict[str, Any]]:
    if not x:
        return []
    if isinstance(x, list):
        return x
    return list(x)

def _level_from_tag(tag: Optional[str]) -> Optional[int]:
    if not tag:
        return None
    t = tag.lower().strip()
    if len(t) == 2 and t[0] == "h" and t[1].isdigit():
        return int(t[1])
    if t in {"h1","h2","h3","h4","h5","h6"}:
        return int(t[1])
    return None

def _has_accessible_name(ctrl: Dict[str, Any]) -> bool:
    """
    Nombre accesible para controles de formulario (no hidden/button/reset/submit/image):
      - <label for=...> asociado (flag 'label_for' o 'has_label')
      - label envolvente (wrapped_by_label)
      - aria-label no vacío
      - aria-labelledby presente
      - title no vacío
    Nota: placeholder solo NO cuenta como nombre accesible.
    """
    if ctrl.get("type") in {"hidden", "button", "submit", "reset", "image"}:
        return True  # No exigimos label para estos en 1.3.1
    if ctrl.get("role") == "button":
        return True
    # señales de nombre accesible
    if ctrl.get("has_label") or ctrl.get("wrapped_by_label") or ctrl.get("label_for"):
        return True
    aria_label = (ctrl.get("aria-label") or "").strip()
    aria_labelledby = (ctrl.get("aria-labelledby") or "").strip()
    title = (ctrl.get("title") or "").strip()
    if aria_label or aria_labelledby or title:
        return True
    # placeholder NO cuenta
    return False

def _is_group_control(ctrl: Dict[str, Any]) -> bool:
    return (ctrl.get("type") in {"radio", "checkbox"}) or (ctrl.get("role") in {"radio", "checkbox"})

def _is_data_table(tbl: Dict[str, Any]) -> bool:
    """
    Heurística: tabla de datos si (filas >=2 y cols >=2) y no es 'presentation/none',
    y no está marcada como layout explícito.
    """
    role = (tbl.get("role") or "").lower()
    rows = int(tbl.get("rows") or tbl.get("row_count") or 0)
    cols = int(tbl.get("cols") or tbl.get("col_count") or 0)
    is_layout = bool(tbl.get("is_layout_table"))
    return (rows >= 2 and cols >= 2) and (role not in {"presentation", "none"}) and (not is_layout)

def _has_data_headers(tbl: Dict[str, Any]) -> bool:
    """
    Cumplimiento mínimo: hay <th> o atributos headers/scope en celdas header.
    Aceptamos flags del extractor.
    """
    th = int(tbl.get("th_count") or 0)
    has_scope = bool(tbl.get("has_scope"))
    has_headers_attr = bool(tbl.get("has_headers_attr"))
    return bool(th > 0 or has_scope or has_headers_attr)

def _list_semantics_ok(lst: Dict[str, Any]) -> bool:
    """
    <ul>/<ol> deben contener <li>; <dl> debe tener pares <dt>/<dd>.
    Acepta counts del extractor si existen.
    """
    tag = (lst.get("tag") or "").lower()
    li = int(lst.get("li_count") or 0)
    dt = int(lst.get("dt_count") or 0)
    dd = int(lst.get("dd_count") or 0)
    if tag in {"ul", "ol"}:
        return li > 0
    if tag == "dl":
        return (dt > 0 and dd > 0)
    # si no sabemos, no marcamos fallo
    return True

def _compute_heading_jumps(headings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Detecta saltos bruscos de jerarquía (p.ej., H2 -> H4 sin H3 intermedio).
    """
    jumps = 0
    offenders = []
    prev = None
    for h in headings:
        lvl = h.get("level") or _level_from_tag(h.get("tag"))
        if lvl is None:
            continue
        if prev is not None and (lvl - prev) > 1:
            jumps += 1
            offenders.append({
                "tag": h.get("tag"),
                "text": (h.get("text") or "")[:180],
                "level": lvl,
                "prev_level": prev,
                "reason": f"Salto de jerarquía H{prev} → H{lvl}."
            })
        prev = lvl
    return {"heading_jumps": jumps, "heading_offenders": offenders}

# -------------------------
# Núcleo del criterio
# -------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    # Recolecta elementos desde el extractor (defensivo con nombres alternos)
    headings: List[Dict[str, Any]] = _as_list(getattr(ctx, "headings", []) or getattr(ctx, "h_tags", []))
    lists_: List[Dict[str, Any]] = _as_list(getattr(ctx, "lists", []) or getattr(ctx, "list_nodes", []))
    tables: List[Dict[str, Any]] = _as_list(getattr(ctx, "tables", []))
    controls: List[Dict[str, Any]] = _as_list(
        getattr(ctx, "form_controls", []) or getattr(ctx, "inputs", []) or getattr(ctx, "form_fields", [])
    )
    landmarks = _iter_landmarks(ctx)

    # --- Encabezados
    h_levels = [(h.get("level") or _level_from_tag(h.get("tag"))) for h in headings if (h.get("level") or _level_from_tag(h.get("tag")))]
    h1_present = any(l == 1 for l in h_levels)
    jump_info = _compute_heading_jumps(headings)

    # --- Listas
    lists_total = len(lists_)
    lists_bad = 0
    list_offenders: List[Dict[str, Any]] = []
    for lst in lists_:
        if not _list_semantics_ok(lst):
            lists_bad += 1
            list_offenders.append({
                "tag": (lst.get("tag") or "").lower(),
                "id": lst.get("id", ""),
                "class": lst.get("class", []),
                "reason": "Estructura de lista no válida (ul/ol sin li, o dl sin dt/dd)."
            })

    # --- Tablas
    tables_total = len(tables)
    data_tables = 0
    data_tables_missing_headers = 0
    table_offenders: List[Dict[str, Any]] = []
    for t in tables:
        if _is_data_table(t):
            data_tables += 1
            if not _has_data_headers(t):
                data_tables_missing_headers += 1
                table_offenders.append({
                    "tag": "table",
                    "id": t.get("id", ""),
                    "class": t.get("class", []),
                    "rows": int(t.get("rows") or t.get("row_count") or 0),
                    "cols": int(t.get("cols") or t.get("col_count") or 0),
                    "th_count": int(t.get("th_count") or 0),
                    "has_scope": bool(t.get("has_scope")),
                    "has_headers_attr": bool(t.get("has_headers_attr")),
                    "reason": "Tabla de datos sin cabeceras (<th>/scope/headers)."
                })

    # --- Formularios
    controls_total = 0
    controls_missing_label = 0
    control_offenders: List[Dict[str, Any]] = []
    group_missing_legend = 0
    group_total = 0

    # Agrupa radios/checkbox por 'name' para exigir fieldset/legend cuando hay grupos
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for c in controls:
        tag = (c.get("tag") or "").lower()
        ctrl_type = (c.get("type") or "").lower()
        if tag not in {"input", "select", "textarea"} and c.get("role") not in {"textbox", "combobox", "spinbutton", "slider", "checkbox", "radio"}:
            continue

        # Conteo de controles que requieren nombre accesible
        if ctrl_type not in {"hidden", "button", "submit", "reset", "image"}:
            controls_total += 1
            if not _has_accessible_name(c):
                controls_missing_label += 1
                control_offenders.append({
                    "tag": tag or c.get("role"),
                    "type": ctrl_type or c.get("role", ""),
                    "id": c.get("id", ""),
                    "name": c.get("name", ""),
                    "class": c.get("class", []),
                    "reason": "Control de formulario sin nombre accesible (label/aria-label/aria-labelledby/title)."
                })

        # Radios/checkbox → grupos por 'name'
        if _is_group_control(c):
            n = (c.get("name") or "").strip()
            if n:
                groups.setdefault(n, []).append(c)

    # Verifica fieldset/legend para grupos (cuando haya >=2 radios o checkboxes con mismo name)
    for name, members in groups.items():
        if len(members) >= 2:
            group_total += 1
            has_legend = _group_has_legend(members)
            if not has_legend:
                group_missing_legend += 1
                control_offenders.append({
                    "tag": "fieldset",
                    "name": name,
                    "count": len(members),
                    "reason": "Grupo de radios/checkbox sin <fieldset> y <legend>."
                })

    # --- Landmarks mínimos
    main_roles = 0
    for lm in landmarks:
        role = (_get_attr(lm, "role") or _get_attr(lm, "tag") or "").lower()
        if role == "main" or (_get_attr(lm, "tag") or "").lower() == "main":
            main_roles += 1
    multiple_main = max(0, main_roles - 1)

    # --- Agregados / métricas
    heading_jumps = int(jump_info["heading_jumps"])

    offenders_all: List[Dict[str, Any]] = []
    offenders_all.extend(jump_info["heading_offenders"])
    if list_offenders:
        offenders_all.extend(list_offenders)
    offenders_all.extend(table_offenders)
    offenders_all.extend(control_offenders)
    if multiple_main > 0:
        offenders_all.append({"tag": "main", "reason": "Hay múltiples regiones 'main' en la página."})

    # ok_ratio aproximado: elementos correctos / elementos evaluados
    denom = (
        controls_total
        + data_tables
        + lists_total
        + len(h_levels)      # <-- sin 'max(1, …)' para permitir denom=0 => NA
        + (group_total or 0)
    )
    nom = (
        (controls_total - controls_missing_label)
        + (data_tables - data_tables_missing_headers)
        + (lists_total - lists_bad)
        + max(0, len(h_levels) - heading_jumps)
        + (group_total - group_missing_legend)
    )
    ok_ratio = 1.0 if denom == 0 else round(max(0.0, min(1.0, nom / denom)), 4)

    details: Dict[str, Any] = {
        # Encabezados
        "headings_total": len(h_levels),
        "h1_present": h1_present,
        "heading_jumps": heading_jumps,
        # Listas
        "lists_total": len(lists_),
        "lists_bad": lists_bad,
        # Tablas
        "tables_total": tables_total,
        "data_tables": data_tables,
        "data_tables_missing_headers": data_tables_missing_headers,
        # Formularios
        "controls_total": controls_total,
        "controls_missing_label": controls_missing_label,
        "groups_total": group_total,
        "groups_missing_legend": group_missing_legend,
        # Landmarks
        "main_regions": main_roles,
        "multiple_main": multiple_main,
        # Meta
        "ok_ratio": ok_ratio,
        "offenders": offenders_all,
        "note": (
            "RAW: 1.3.1 verifica que la estructura/relaciones visuales estén codificadas semánticamente: "
            "encabezados jerárquicos sin saltos bruscos; listas con elementos válidos; "
            "tablas de datos con cabeceras (<th>/scope/headers); controles de formulario con nombre accesible; "
            "grupos de radios/checkbox con <fieldset>/<legend>. Reporta múltiples 'main' como problema."
        )
    }

    # NA explícito si no hay nada que evaluar
    zero_sample = (
        details["headings_total"] == 0
        and details["lists_total"] == 0
        and details["data_tables"] == 0
        and details["controls_total"] == 0
        and details["groups_total"] == 0
        and details["main_regions"] == 0
    )
    if zero_sample:
        details["na"] = True
        details["ok_ratio"] = 1.0

    return details

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    Si dispones de DOM post-render (Playwright), aquí puedes:
      - Resolver aria-labelledby/aria-describedby → texto real (mejorando nombres accesibles)
      - Verificar encabezados 'visualmente' promovidos (CSS) sin <hN> real (p.ej., role='heading' + aria-level)
      - Detectar listas visuales (•, -, ·) no semánticas convertidas a <ul>/<ol> mediante ARIA (role='list'/'listitem')
      - Distinguir layout-table vs data-table con heurísticas de estilos (display: table...) si lo marcas en el extractor
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 1.3.1; no se pudo evaluar en modo renderizado."}
    d = _compute_counts_raw(rctx)
    d["rendered"] = True
    d["note"] = (d.get("note", "") + " | RENDERED: resolvible a aria-labelledby, role='heading' + aria-level, role='list'/'listitem'.").strip()
    return d

# -------------------------
# IA opcional
# -------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    Si hay problemas, la IA sugiere soluciones puntuales por tipo:
      - Encabezados: nivel sugerido y snippet
      - Formularios: label y atributos ARIA sugeridos
      - Tablas: <th scope='col/row'> o headers/id ejemplo
      - Listas: convertir parrafos en <ul><li>...</li></ul>
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": 'IA no configurada.', "manual_required": False}

    issues = (
        details.get("controls_missing_label", 0)
        + details.get("data_tables_missing_headers", 0)
        + details.get("groups_missing_legend", 0)
        + details.get("lists_bad", 0)
        + details.get("heading_jumps", 0)
        + details.get("multiple_main", 0)
    )
    if issues == 0:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "headings_total": details.get("headings_total", 0),
            "heading_jumps": details.get("heading_jumps", 0),
            "controls_missing_label": details.get("controls_missing_label", 0),
            "data_tables_missing_headers": details.get("data_tables_missing_headers", 0),
            "groups_missing_legend": details.get("groups_missing_legend", 0),
            "lists_bad": details.get("lists_bad", 0),
            "multiple_main": details.get("multiple_main", 0),
        },
        "offenders": details.get("offenders", [])[:12],
        "html_snippet": (html_sample or "")[:2500],
    }
    prompt = (
        "Actúa como auditor de accesibilidad para WCAG 1.3.1 (Información y relaciones). "
        "Dado el contexto y offenders, sugiere FIXES concretos por cada elemento: "
        "1) Para encabezados con saltos: qué nivel usar y snippet HTML corregido; "
        "2) Para controles sin nombre accesible: <label for> o aria-label/aria-labelledby; "
        "3) Para tablas de datos: añadir <th scope='col/row'> o headers/id y <caption> opcional; "
        "4) Para listas mal estructuradas: convertir a <ul><li>…</li></ul>; "
        "5) Para grupos de radios/checkbox: envolver en <fieldset><legend>…</legend>…; "
        "6) Para múltiples 'main': dejar solo una región main. "
        "Devuelve JSON: { suggestions: [{reason, fix_html}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------
# Orquestación
# -------------------------

def run_1_3_1(
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

    # 3) Veredicto/score con NA cuando no hay muestra
    zero_sample = bool(details.get("na") is True) or (
        details.get("headings_total", 0) == 0
        and details.get("lists_total", 0) == 0
        and details.get("data_tables", 0) == 0
        and details.get("controls_total", 0) == 0
        and details.get("groups_total", 0) == 0
        and details.get("main_regions", 0) == 0
    )

    if zero_sample:
        details["na"] = True
        verdict = "na"
        passed = True
    else:
        violations = (
            details.get("controls_missing_label", 0)
            + details.get("data_tables_missing_headers", 0)
            + details.get("groups_missing_legend", 0)
            + details.get("lists_bad", 0)
            + details.get("heading_jumps", 0)
            + details.get("multiple_main", 0)
        )
        
        # Lógica ultra estricta: PASS solo si 100%, PARTIAL >= 80%, FAIL < 80%
        total_checks = (
            details.get("controls_total", 0)
            + details.get("data_tables", 0)
            + details.get("groups_total", 0)
            + details.get("lists_total", 0)
            + details.get("headings_total", 0)
            + (1 if details.get("main_regions", 0) > 0 else 0)
        )
        
        if total_checks == 0 or violations == 0:
            passed = True
            details["ratio"] = 1.0
        else:
            ok_count = total_checks - violations
            ratio = ok_count / total_checks
            details["ratio"] = ratio
            # PARTIAL si >= 80%, FAIL si < 80%
            if ratio >= 0.80:
                passed = True  # verdict_from_counts detectará partial
            else:
                passed = False
        
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
        principle=meta.get("principle", "Perceptible"),
        title=meta.get("title", "Información y relaciones"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
