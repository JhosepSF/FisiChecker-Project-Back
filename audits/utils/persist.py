# audits/utils/persist.py
from typing import Dict, Any, List, Optional, Set, Type
from django.db import transaction, models

from audits.models import WebsiteAudit, WebsiteAuditResult
from audits.wcag.constants import WCAG_META

# Score por criterio: 0=fail, 1=partial, 2=pass, NA=0 (pero NA no contará en el score del parent)
# Score del parent (WebsiteAudit.score): promedio de criterios no-NA en escala 0-2
# Frontend debe dividir entre 2 y multiplicar por 100 para obtener porcentaje
VERDICT_TO_SCORE = {"fail": 0, "partial": 1, "pass": 2, "na": 0}

# Claves que, si todas están presentes y todas son 0, implican N/A automático
NA_IF_ZERO_KEYS: Dict[str, tuple[str, ...]] = {
    "1.2.1": ("media_total",),
    "1.2.2": ("requiring_captions", "videos_total"),
    "1.2.3": ("requiring_ad_or_alt", "videos_total"),
    "1.2.4": ("live_media_total", "requiring_captions"),
    "1.2.5": ("videos_total", "requiring_ad"),
    "1.2.6": ("videos_total", "requiring_sign"),
    "1.2.7": ("videos_total", "requiring_extended_ad"),
    "1.2.8": ("videos_total", "requiring_alt"),
    "1.2.9": ("live_audio_total",),
    "1.3.1": ("headings_total", "lists_total", "data_tables", "controls_total", "groups_total", "main_regions"),
    "1.3.2": ("focusables_total",),
    "1.3.3": ("texts_examined", "icon_only_interactives"),
    "1.3.4": ("orientation_lock_scripts", "orientation_css_blocks", "orientation_overlays", "rotation_messages"),
    "1.3.5": ("applicable", "controls_examined"),
    "1.3.6": ("icons_examined", "landmarks_detected", "input_purpose_tokens"),
    "1.4.1": ("links_total", "controls_total", "badges_total", "charts_total"),
    "1.4.2": ("media_total",),
    "1.4.11": ("tested",),
    "2.4.7": ("tested",),
    "2.5.5": ("tested",),
}

def _coerce_parent_score(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        if value.strip().upper() == "N/A":
            return None
        try:
            return float(value)
        except Exception:
            return None
    return None

def _safe_float(x: object) -> Optional[float]:
    """Convierte a float de forma segura (None/''/'null'/'nan' => None)."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if not s or s.lower() in {"none", "null", "nan"}:
        return None
    try:
        return float(s)
    except Exception:
        return None

def _num_or_none(x: object) -> Optional[float]:
    return _safe_float(x)

def _field_names(model_cls: Type[models.Model]) -> Set[str]:
    return {f.name for f in model_cls._meta.get_fields() if hasattr(f, "attname")}

def _allowed_verdicts() -> Set[str]:
    try:
        fld = WebsiteAuditResult._meta.get_field("verdict")
        choices = getattr(fld, "choices", None)
        if choices:
            return {c[0] for c in choices}
    except Exception:
        pass
    return {"pass", "fail", "na", "partial"}

ALLOWED_PARENT = _field_names(WebsiteAudit)
ALLOWED_RESULT = _field_names(WebsiteAuditResult)
ALLOWED_VERDICTS = _allowed_verdicts()

def _is_zero_sample_na(details: Dict[str, Any], code: Optional[str]) -> bool:
    keys = NA_IF_ZERO_KEYS.get(code or "", ())
    if not keys:
        return False
    seen_any = False
    for k in keys:
        if k in details:
            seen_any = True
            v = _safe_float(details.get(k)) or 0.0
            if v > 0.0:
                return False
    return seen_any  # había claves y ninguna > 0

def _infer_verdict(data: Dict[str, Any], code: Optional[str] = None) -> str:
    details = data.get("details") or {}

    # Reglas explícitas 1.1.1
    if code == "1.1.1":
        total = int(_safe_float(details.get("images_total")) or 0)
        missing = int(_safe_float(details.get("missing_alt")) or 0)
        if total == 0:
            details["na"] = True
            return "na"
        if missing == 0:
            return "pass"
        # Si falta menos del 50%, es partial; si falta 50% o más, es fail
        if missing < total / 2:
            return "partial"
        return "fail"

    # Reglas explícitas 1.2.x (lógica basada en porcentajes)
    if code == "1.2.2":
        total = int(details.get("videos_total") or 0)
        req   = int(details.get("requiring_captions") or 0)
        miss  = int(details.get("missing_captions") or 0)
        if total == 0 or req == 0:
            return "na"
        if miss == 0: return "pass"
        if miss < req / 2: return "partial"
        return "fail"

    if code == "1.2.3":
        total = int(details.get("videos_total") or 0)
        req   = int(details.get("requiring_ad_or_alt") or 0)
        miss  = int(details.get("missing_ad_or_alt") or 0)
        if total == 0 or req == 0:
            return "na"
        if miss == 0: return "pass"
        if miss < req / 2: return "partial"
        return "fail"

    if code == "1.2.4":
        total = int(details.get("live_media_total") or 0)
        req   = int(details.get("requiring_captions") or 0)
        miss  = int(details.get("missing_captions") or 0)
        if total == 0 or req == 0:
            return "na"
        if miss == 0: return "pass"
        if miss < req / 2: return "partial"
        return "fail"

    if code == "1.2.5":
        total = int(details.get("videos_total") or 0)
        req   = int(details.get("requiring_ad") or 0)
        miss  = int(details.get("missing_ad") or 0)
        if total == 0 or req == 0:
            return "na"
        if miss == 0: return "pass"
        if miss < req / 2: return "partial"
        return "fail"

    if code == "1.2.6":
        total = int(details.get("videos_total") or 0)
        req   = int(details.get("requiring_sign") or 0)
        miss  = int(details.get("missing_sign") or 0)
        if total == 0 or req == 0:
            return "na"
        if miss == 0: return "pass"
        if miss < req / 2: return "partial"
        return "fail"

    if code == "1.2.7":
        total = int(details.get("videos_total") or 0)
        req   = int(details.get("requiring_extended_ad") or 0)
        miss  = int(details.get("missing_extended_ad") or 0)
        if total == 0 or req == 0:
            return "na"
        if miss == 0: return "pass"
        if miss < req / 2: return "partial"
        return "fail"

    if code == "1.2.8":
        total = int(details.get("videos_total") or 0)
        req   = int(details.get("requiring_alt") or 0)
        miss  = int(details.get("missing_alt") or 0)
        if total == 0 or req == 0:
            return "na"
        if miss == 0: return "pass"
        if miss < req / 2: return "partial"
        return "fail"

    if code == "1.2.9":
        req  = int(details.get("live_audio_total") or 0)
        miss = int(details.get("missing_live_text_alt") or 0)
        if req == 0:
            return "na"
        if miss == 0: return "pass"
        if miss < req / 2: return "partial"
        return "fail"

    # Señal NA ya en details
    if isinstance(details, dict) and details.get("na") is True:
        return "na"

    # Heurística NA por “muestra 0”
    if _is_zero_sample_na(details, code):
        details["na"] = True
        return "na"

    # Respeta status/verdict si viene maquillado correctamente
    st = (data.get("status") or data.get("verdict"))
    if st in {"pass", "fail", "partial", "na"}:
        return st

    # Fallbacks genéricos
    if "passed" in data:
        return "pass" if bool(data["passed"]) else "fail"

    # Ratios: 100% = pass, >= 50% = partial, < 50% = fail
    for k in ("ok_ratio", "ratio", "meaningful_ratio", "inputs_label_ratio", "alt_ratio", "visible_ratio"):
        r = _safe_float(details.get(k))
        if r is not None:
            if r >= 0.999: return "pass"
            if r >= 0.5: return "partial"
            return "fail"

    # tested/fails: 0 fails = pass, < 50% fails = partial, >= 50% fails = fail
    tested = _safe_float(details.get("tested"))
    fails = _safe_float(details.get("fails"))
    if (tested is not None) and tested > 0:
        if (fails or 0) <= 0: return "pass"
        if fails is not None and fails < tested / 2: return "partial"
        return "fail"

    return "fail"

def persist_audit_with_results(
    url: str,
    response_meta: Dict[str, Any],
    wcag: Dict[str, Any],
    rendered: bool = False,
    rendered_codes: Optional[List[str]] = None,
    raw: Optional[bool] = None,
    ai: Optional[bool] = None,
    mode_effective: Optional[str] = None,
) -> WebsiteAudit:
    # Normaliza flags (sin None)
    mode_eff = (mode_effective or str((response_meta or {}).get("mode_effective") or "")).upper()
    rendered_flag = bool(rendered) or (mode_eff == "RENDERED")
    ai_flag       = (bool(ai) if ai is not None else False) or (mode_eff == "AI")
    if raw is None:
        raw_flag = mode_eff in ("RAW", "AUTO") or (not rendered_flag and not ai_flag)
    else:
        raw_flag = bool(raw)
    if not (raw_flag or rendered_flag or ai_flag):
        raw_flag = True

    parent_kwargs = {
        "url": url,
        "status_code": (response_meta.get("status_code") if isinstance(response_meta, dict) else None),
        "elapsed_ms": (response_meta.get("elapsed_ms") if isinstance(response_meta, dict) else None),
        "page_title": ((response_meta.get("page_title") or "")[:512] if isinstance(response_meta, dict) else ""),
        # El score del parent se calculará al final (0-100%) excluyendo criterios NA
        "score": None,
        "raw": raw_flag,
        "rendered": rendered_flag,
        "ai": ai_flag,
        "mode_effective": (mode_eff or None),
    }
    parent_kwargs = {k: v for k, v in parent_kwargs.items() if k in ALLOWED_PARENT}

    with transaction.atomic():
        audit = WebsiteAudit.objects.create(**parent_kwargs)

        rows: List[WebsiteAuditResult] = []

        # Acumuladores para score del parent (excluyendo N/A)
        non_na_sum = 0.0
        non_na_cnt = 0
        total_cnt = 0

        for code, data in (wcag or {}).items():
            meta = (WCAG_META.get(code) or {})
            payload = data if isinstance(data, dict) else {}
            details = payload.get("details")
            if not isinstance(details, dict):
                details = {}

            verdict = _infer_verdict(payload, code=code)
            if verdict not in ALLOWED_VERDICTS:
                verdict = "fail"

            # Métricas convenientes 1.1.1
            if code == "1.1.1":
                details["with_alt"] = int(_safe_float(details.get("with_alt")) or 0)
                details["decorative"] = int(_safe_float(details.get("decorative")) or 0)
                details["images_total"] = int(_safe_float(details.get("images_total")) or 0)
                details["missing_alt"] = int(_safe_float(details.get("missing_alt")) or 0)
                details["with_alt_or_decorative"] = details["with_alt"] + details["decorative"]

            # Fuente de la fila: primero usa el source del resultado si viene del check, luego los flags globales
            result_source = payload.get("source", "").lower() if isinstance(payload, dict) else ""
            if result_source in ("raw", "rendered", "ai"):
                src = result_source
            elif rendered_flag:
                src = "rendered"
            elif ai_flag:
                src = "ai"
            else:
                src = "raw"

            # Score por fila
            score_num = VERDICT_TO_SCORE.get(verdict, 1)
            if verdict == "na":
                details["na"] = True
                score_hint_val = None
            else:
                score_hint_val = _num_or_none(details.get("ok_ratio"))

            # Acumular para el parent (ignora N/A)
            if verdict != "na":
                non_na_sum += float(score_num)
                non_na_cnt += 1
            total_cnt += 1

            row_kwargs = {
                "audit": audit,
                "code": code,
                "title": meta.get("title", ""),
                "level": meta.get("level", ""),
                "principle": meta.get("principle", ""),
                "verdict": verdict,
                "source": src,
                "score": score_num,
                "score_hint": score_hint_val,
                "details": details,
            }
            row_kwargs = {k: v for k, v in row_kwargs.items() if k in ALLOWED_RESULT}
            rows.append(WebsiteAuditResult(**row_kwargs))

        if rows:
            WebsiteAuditResult.objects.bulk_create(rows)

        # Recalcular score del parent EXCLUYENDO N/A
        # Score en escala 0-2 (promedio de criterios evaluables) y penalizado por cobertura
        if "score" in ALLOWED_PARENT:
            if non_na_cnt > 0:
                base_score = non_na_sum / non_na_cnt  # escala 0..2
                coverage = (non_na_cnt / total_cnt) if total_cnt > 0 else 1.0
                parent_score = round(base_score * coverage, 4)
            else:
                parent_score = None  # todo N/A ⇒ sin score
            WebsiteAudit.objects.filter(pk=audit.pk).update(score=parent_score)
            # Refrescar el objeto desde la BD para que tenga el score actualizado
            audit.refresh_from_db()

        return audit
