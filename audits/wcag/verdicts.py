# audits/wcag/verdicts.py
from typing import Dict, Any, Tuple
from .constants import WCAG_META  # { "1.4.3": {"title":..., "level":..., "principle":...}, ... }

VERDICT_PASS = "CUMPLE"
VERDICT_FAIL = "NO CUMPLE"
VERDICT_PARTIAL = "CUMPLE PARCIALMENTE"
VERDICT_NA = "NA"

def _ratio_to_verdict(ratio: float, pass_thr: float, partial_thr: float) -> str:
    if ratio >= pass_thr:
        return VERDICT_PASS
    if ratio >= partial_thr:
        return VERDICT_PARTIAL
    return VERDICT_FAIL

def infer_verdict_for_code(code: str, res: Dict[str, Any]) -> Tuple[str, float | None]:
    """
    Devuelve (verdict, score_hint) usando heurísticas por código.
    'res' es el bloque {'passed': bool, 'details': {...}} que salieron de tus checks.
    """
    d = res.get("details") or {}
    # === Ejemplos más usados ===
    if code == "1.1.1":  # img alt
        total = int(d.get("images_total", 0) or 0)
        ok = int(d.get("with_alt_or_decorative", 0) or 0)
        if total == 0:
            return (VERDICT_NA, None)
        ratio = ok / total if total else 1.0
        return (_ratio_to_verdict(ratio, pass_thr=1.0, partial_thr=0.3), ratio)

    if code == "1.2.2":  # captions
        vids = int(d.get("videos", 0) or 0)
        missing = int(d.get("videos_without_captions", 0) or 0)
        if vids == 0:
            return (VERDICT_NA, None)
        ratio = (vids - missing) / vids
        return (_ratio_to_verdict(ratio, pass_thr=1.0, partial_thr=0.3), ratio)

    if code == "1.4.2":  # audio control
        issues = int(d.get("autoplay_issues", 0) or 0)
        return (VERDICT_PASS if issues == 0 else VERDICT_FAIL, None)

    if code == "1.3.1":  # info & relationships
        th_issues = int(d.get("tables_without_th", 0) or 0)
        hierarchy_ok = bool(d.get("heading_hierarchy_ok", True))
        # Si no hay tablas y jerarquía ok -> PASS
        if th_issues == 0 and hierarchy_ok:
            return (VERDICT_PASS, None)
        # Si hay mezcla (algunas tablas sin <th> o jerarquía rompe) => PARTIAL
        if th_issues > 0 and hierarchy_ok:
            return (VERDICT_PARTIAL, None)
        if th_issues == 0 and not hierarchy_ok:
            return (VERDICT_PARTIAL, None)
        return (VERDICT_FAIL, None)

    if code == "1.3.5":  # autocomplete tokens
        total = int(d.get("inputs_total", 0) or 0)
        with_auto = int(d.get("inputs_with_autocomplete", 0) or 0)
        if total == 0:
            return (VERDICT_NA, None)
        ratio = with_auto / total
        return (_ratio_to_verdict(ratio, pass_thr=1.0, partial_thr=0.3), ratio)

    if code == "1.4.3":  # contraste texto
        tested = int(d.get("tested_nodes", d.get("tested_desktop", 0)) or 0)  # raw o rendered
        fails = int(d.get("fails", d.get("fails_desktop", 0)) or 0)
        if tested == 0:
            return (VERDICT_NA, None)
        ratio = (tested - fails) / tested
        return (_ratio_to_verdict(ratio, pass_thr=1.0, partial_thr=0.3), ratio)

    if code == "1.4.4":  # zoom bloqueado
        zb = bool(d.get("zoom_blocked", False))
        return (VERDICT_FAIL if zb else VERDICT_PASS, None)

    if code == "1.4.10":  # reflow
        overflow = bool(d.get("has_horizontal_overflow_at_320px", False))
        return (VERDICT_FAIL if overflow else VERDICT_PASS, None)

    if code == "1.4.11":  # contraste no textual
        tested = int(d.get("tested", 0) or 0)
        fails = int(d.get("fails", 0) or 0)
        if tested == 0:
            return (VERDICT_NA, None)
        ratio = (tested - fails) / tested
        return (_ratio_to_verdict(ratio, pass_thr=1.0, partial_thr=0.3), ratio)

    if code == "2.1.1":  # teclado
        t = int(d.get("tabindex_gt0", 0) or 0)
        o = int(d.get("onclick_noninteractive", 0) or 0)
        if t == 0 and o == 0:
            return (VERDICT_PASS, None)
        if t > 5 or o > 5:  # Muchos problemas = FAIL
            return (VERDICT_FAIL, None)
        return (VERDICT_PARTIAL, None)  # Cualquier problema = PARTIAL

    if code == "2.4.1":  # saltar bloques
        has_main = bool(d.get("has_main", False))
        has_skip = bool(d.get("has_skip_link", False))
        if has_main or has_skip:
            return (VERDICT_PASS, None)
        return (VERDICT_FAIL, None)

    if code == "2.4.2":  # título de página
        has_title = bool(d.get("has_title", False))
        return (VERDICT_PASS if has_title else VERDICT_FAIL, None)

    if code == "2.4.4":  # propósito de enlaces
        ratio = float(d.get("ratio", 0.0) or 0.0)
        # PASS >= 1.0; PARTIAL >= 0.3; FAIL < 0.3
        return (_ratio_to_verdict(ratio, pass_thr=1.0, partial_thr=0.3), ratio)

    if code == "2.4.6":  # encabezados/labels
        # Para encabezados: ok si no hay vacíos ni genéricos
        head_app = int(d.get("applicable_headings", 0) or 0)
        head_empty = int(d.get("headings_empty", 0) or 0)
        head_generic = int(d.get("headings_generic", 0) or 0)
        head_violations = head_empty + head_generic
        
        # Para etiquetas: ok si no hay ausentes ni genéricas
        label_app = int(d.get("applicable_labels", 0) or 0)
        label_missing = int(d.get("labels_missing", 0) or 0)
        label_generic = int(d.get("labels_generic", 0) or 0)
        label_violations = label_missing + label_generic
        
        # Total: suma de ambos aplicables y violaciones
        total_app = head_app + label_app
        if total_app == 0:
            return (VERDICT_NA, None)
        total_violations = head_violations + label_violations
        ratio = (total_app - total_violations) / total_app
        return (_ratio_to_verdict(ratio, pass_thr=1.0, partial_thr=0.3), ratio)

    if code == "2.4.7":  # foco visible (rendered)
        tested = int(d.get("tested", 0) or 0)
        vis = int(d.get("visible", 0) or 0)
        if tested == 0:
            return (VERDICT_NA, None)
        ratio = vis / tested
        return (_ratio_to_verdict(ratio, pass_thr=1.0, partial_thr=0.3), ratio)

    if code == "2.5.5":  # tamaño del objetivo
        tested = int(d.get("tested", 0) or 0)
        small = int(d.get("too_small", 0) or 0)
        if tested == 0:
            return (VERDICT_NA, None)
        ratio = (tested - small) / tested
        return (_ratio_to_verdict(ratio, pass_thr=1.0, partial_thr=0.3), ratio)

    if code == "3.1.1":  # idioma de página
        lang_present = bool(d.get("lang_present", False))
        return (VERDICT_PASS if lang_present else VERDICT_FAIL, None)

    if code == "3.1.2":  # idioma de partes (sin validar corrección)
        parts = int(d.get("parts_with_lang", 0) or 0)
        # No podemos saber si se requerían. Sin señal, lo tratamos como NA.
        return (VERDICT_NA if parts == 0 else VERDICT_PASS, None)

    if code == "3.2.1":  # On Focus
        tested = int(d.get("tested", 0) or 0)
        offenders = d.get("offenders") or []
        if tested == 0:
            return (VERDICT_NA, None)
        return (VERDICT_PASS if not offenders else VERDICT_FAIL, None)

    if code == "3.2.2":  # On Input
        tested = int(d.get("tested", 0) or 0)
        offenders = d.get("offenders") or []
        if tested == 0:
            return (VERDICT_NA, None)
        return (VERDICT_PASS if not offenders else VERDICT_FAIL, None)

    if code == "3.3.2":  # etiquetas/instrucciones
        total = int(d.get("inputs_total", 0) or 0)
        labeled = int(d.get("inputs_labeled", 0) or 0)
        if total == 0:
            return (VERDICT_NA, None)
        ratio = labeled / total
        return (_ratio_to_verdict(ratio, pass_thr=1.0, partial_thr=0.3), ratio)

    if code == "4.1.1":  # parsing
        dup = d.get("duplicate_ids") or []
        return (VERDICT_PASS if len(dup) == 0 else VERDICT_FAIL, None)

    if code == "4.1.2":  # name/role/value
        applicable = int(d.get("applicable", 0) or 0)
        violations = int(d.get("violations", 0) or 0)
        if applicable == 0:
            return (VERDICT_NA, None)
        ratio = (applicable - violations) / applicable
        return (_ratio_to_verdict(ratio, pass_thr=1.0, partial_thr=0.3), ratio)

    if code == "4.1.3":  # status messages (rendered)
        all_candidates = int(d.get("candidates_all", 0) or 0)
        mis_all = d.get("misannotated") or []
        obs_cnt = int(d.get("observed_count", 0) or 0)
        now_candidates = int(d.get("now_candidates", 0) or 0)
        # Si realmente no hubo mensajes (ni ahora, ni observados, ni candidatos), NA
        if all_candidates == 0 and obs_cnt == 0 and now_candidates == 0:
            return (VERDICT_NA, None)
        return (VERDICT_PASS if len(mis_all) == 0 else VERDICT_PARTIAL, None)

    # fallback
    return (VERDICT_PASS if res.get("passed") else VERDICT_FAIL, None)


def enrich_wcag_with_verdicts(wcag: Dict[str, Any]) -> Dict[str, Any]:
    """Devuelve un nuevo dict con 'verdict' y 'score_hint' agregados por criterio."""
    enriched = {}
    for code, res in wcag.items():
        meta = WCAG_META.get(code, {})
        verdict, score_hint = infer_verdict_for_code(code, res)
        enriched[code] = {
            **res,
            "verdict": verdict,
            "score_hint": score_hint,
            "meta": meta,
        }
    return enriched
