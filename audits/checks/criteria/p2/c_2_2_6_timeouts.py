# audits/checks/criteria/p2/c_2_2_6_timeouts.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict
from ..applicability import ensure_na_if_no_applicable, normalize_pass_for_applicable

# IA opcional
try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "2.2.6"

# -------------------------------------------------------------------
# Utilidades
# -------------------------------------------------------------------

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

def _to_seconds(v: Any) -> Optional[float]:
    """
    Convierte duraciones simples a segundos.
    Acepta: números (s), '5000ms', '5s', '1.5m', '2h'
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    sv = _lower(v)
    if sv == "":
        return None
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(ms|s|m|h)?\s*$", sv)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2) or "s"
    if unit == "ms": return num / 1000.0
    if unit == "s":  return num
    if unit == "m":  return num * 60.0
    if unit == "h":  return num * 3600.0
    return None

def _to_hours(v: Any) -> Optional[float]:
    sec = _to_seconds(v)
    if sec is None:
        return None
    return sec / 3600.0

# Detectar “duración explícita” en textos: 30 s, 2 min, 1 hora, 24h, etc.
RE_DURATION_TEXT = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>(s|sec|seg|segundos?)|(m|min|minutos?)|(h|hr|hora?s?))",
    re.IGNORECASE
)

# Meta refresh: content="300; url=/foo"
META_REFRESH_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(?:;.*)?$", re.I)

TWENTY_HOURS_SEC = 20 * 3600.0

# -------------------------------------------------------------------
# Recolección (RAW)
# -------------------------------------------------------------------

def _extract_meta_refresh(ctx: PageContext) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    soup = getattr(ctx, "soup", None)
    if soup is None:
        return out
    try:
        metas = soup.find_all("meta", attrs={"http-equiv": re.compile(r"refresh", re.I)})
    except Exception:
        metas = []
    for m in metas:
        try:
            content = (m.get("content") or "").strip()
            mm = META_REFRESH_RE.match(content)
            if mm:
                sec = float(mm.group(1))
                out.append({
                    "type": "meta_refresh",
                    "seconds": sec,
                    "may_cause_data_loss": True,  # conservador
                    "data_preserved_hours": None,
                    "source": "meta",
                })
        except Exception:
            continue
    return out

def _collect_declared_timeouts(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Colecciones opcionales esperadas del extractor:
      - session_timeout: { seconds, may_cause_data_loss?, data_preserved_hours?, notice_text?, warned_duration_seconds? }
      - timers: [{ type, seconds, may_cause_data_loss?, data_preserved_hours?, notice_text? }]
      - quiz_or_exam_timers: [{ seconds, may_cause_data_loss?, data_preserved_hours? }]
    """
    out: List[Dict[str, Any]] = []

    st = getattr(ctx, "session_timeout", None)
    if isinstance(st, dict):
        out.append({
            "type": "session_timeout",
            "seconds": _to_seconds(st.get("seconds")),
            "may_cause_data_loss": _bool(st.get("may_cause_data_loss")) or True,  # conservador
            "data_preserved_hours": _to_hours(st.get("data_preserved_hours")),
            "notice_text": _s(st.get("notice_text")),
            "warned_duration_seconds": _to_seconds(st.get("warned_duration_seconds")),
            "source": "session_timeout",
        })

    for t in _as_list(getattr(ctx, "timers", [])):
        if isinstance(t, dict):
            out.append({
                "type": _lower(t.get("type") or "timer"),
                "seconds": _to_seconds(t.get("seconds")),
                "may_cause_data_loss": _bool(t.get("may_cause_data_loss")),
                "data_preserved_hours": _to_hours(t.get("data_preserved_hours")),
                "notice_text": _s(t.get("notice_text")),
                "warned_duration_seconds": _to_seconds(t.get("warned_duration_seconds")),
                "source": "timers",
            })

    for q in _as_list(getattr(ctx, "quiz_or_exam_timers", [])):
        if isinstance(q, dict):
            out.append({
                "type": "quiz_or_exam",
                "seconds": _to_seconds(q.get("seconds")),
                "may_cause_data_loss": _bool(q.get("may_cause_data_loss")) or True,
                "data_preserved_hours": _to_hours(q.get("data_preserved_hours")),
                "notice_text": _s(q.get("notice_text")),
                "warned_duration_seconds": _to_seconds(q.get("warned_duration_seconds")),
                "source": "quiz_or_exam_timers",
            })

    return out

def _collect_timeout_notices(ctx: PageContext) -> List[str]:
    """
    Recolecta textos que aparenten ser avisos de timeout con duración.
    Busca en: ctx.timeout_notices (si existe) y texto de la página.
    """
    notices: List[str] = []

    for n in _as_list(getattr(ctx, "timeout_notices", [])):
        if isinstance(n, str) and n.strip():
            notices.append(n.strip())

    # fallback: texto de la página
    page_text = _s(getattr(ctx, "page_text", "")) or _s(getattr(ctx, "title_text", ""))
    if not page_text and getattr(ctx, "soup", None) is not None:
        try:
            page_text = _s(getattr(ctx, "soup").get_text())
        except Exception:
            page_text = ""

    # filtra líneas que mencionen sesiones / inactividad / expira / timeout
    hints = ("timeout", "expira", "inactividad", "inactivity", "sesión", "session")
    if any(h in _lower(page_text) for h in hints):
        notices.append(page_text[:2000])  # acota

    return notices

def _any_notice_has_explicit_duration(notices: List[str]) -> bool:
    for t in notices:
        if RE_DURATION_TEXT.search(t or ""):
            return True
    return False

# -------------------------------------------------------------------
# Evaluación (RAW)
# -------------------------------------------------------------------

def _is_applicable_timeout(item: Dict[str, Any]) -> bool:
    """
    2.2.6 aplica si:
      - hay límite de inactividad/tiempo (seconds>0 o meta refresh),
      - y puede causar pérdida de datos (may_cause_data_loss=True o desconocido → conservador True).
    No aplica si los datos se preservan ≥ 20 horas sin interacción.
    """
    sec = item.get("seconds")
    has_time = isinstance(sec, (int, float)) and sec > 0.0
    is_meta = (_lower(item.get("type") or "") == "meta_refresh")
    if not (has_time or is_meta):
        return False

    preserved_h = item.get("data_preserved_hours")
    if isinstance(preserved_h, (int, float)) and preserved_h >= 20.0:
        return False  # excepción ≥20h

    # Por defecto, asumimos que puede causar pérdida si no se indicó lo contrario
    may_loss = item.get("may_cause_data_loss")
    return True if may_loss is None else bool(may_loss)

def _item_has_own_notice_with_duration(item: Dict[str, Any]) -> bool:
    if _to_seconds(item.get("warned_duration_seconds")) is not None:
        return True
    if RE_DURATION_TEXT.search(_s(item.get("notice_text"))):
        return True
    return False

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW: si hay timeouts aplicables que puedan causar pérdida de datos, se exige informar la
    duración de inactividad (en cualquier punto relevante del flujo), salvo que los datos se
    conserven ≥ 20 horas sin interacción.
    """
    items = []
    items.extend(_extract_meta_refresh(ctx))
    items.extend(_collect_declared_timeouts(ctx))

    notices = _collect_timeout_notices(ctx)
    any_global_notice = _any_notice_has_explicit_duration(notices)

    examined = len(items)
    applicable = 0
    compliant = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []
    types_count: Dict[str, int] = {}

    for it in items:
        typ = _lower(it.get("type") or "timeout")
        types_count[typ] = types_count.get(typ, 0) + 1

        if not _is_applicable_timeout(it):
            continue

        applicable += 1

        # Cumple si: (a) datos preservados ≥20h, o (b) existe aviso con duración (propio o global)
        preserved_h = it.get("data_preserved_hours")
        preserved_ok = isinstance(preserved_h, (int, float)) and preserved_h >= 20.0
        has_notice = _item_has_own_notice_with_duration(it) or any_global_notice

        if preserved_ok or has_notice:
            compliant += 1
        else:
            violations += 1
            offenders.append({
                "type": typ,
                "seconds": it.get("seconds"),
                "source": it.get("source"),
                "reason": "Timeout aplicable sin aviso de duración y sin preservación de datos ≥ 20h."
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, compliant / max(1, applicable))), 4)

    details: Dict[str, Any] = {
        "timeouts_examined": examined,
        "applicable": applicable,
        "compliant": compliant,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "types_count": types_count,
        "notices_detected": len(notices),
        "global_notice_with_duration": any_global_notice,
        "note": (
            "RAW: 2.2.6 (AAA) exige informar la duración de inactividad que produce pérdida de datos, "
            "salvo que los datos se conserven ≥20h. Se consideran timeouts de sesión, meta refresh y "
            "temporizadores de tareas críticas (exámenes, formularios largos)."
        )
    }
    return details

# -------------------------------------------------------------------
# RENDERED (prueba en ejecución)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede exponer:
      rctx.timeouts_test = [
        {
          "type": "session_timeout|meta_refresh|quiz_or_exam|other",
          "seconds": number | None,
          "may_cause_data_loss": bool,
          "data_preserved_hours": number | None,
          "notice_visible": bool,                 # ¿se mostró aviso?
          "notice_has_duration": bool,           # ¿contiene duración explícita?
          "observed_expire": bool,               # se observó expiración real por inactividad
          "notes": str
        }, ...
      ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.2.6; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    tests = _as_list(getattr(rctx, "timeouts_test", []))
    if not tests:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'timeouts_test'.").strip()
        return d

    applicable = 0
    compliant = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for t in tests:
        if not isinstance(t, dict):
            continue

        # Aplicabilidad (igual que RAW)
        if not _is_applicable_timeout(t):
            continue

        applicable += 1

        preserved_h = t.get("data_preserved_hours")
        preserved_ok = isinstance(preserved_h, (int, float)) and preserved_h >= 20.0
        notice_ok = bool(t.get("notice_visible")) and bool(t.get("notice_has_duration"))

        if preserved_ok or notice_ok:
            compliant += 1
        else:
            violations += 1
            offenders.append({
                "type": _lower(t.get("type") or "timeout"),
                "seconds": t.get("seconds"),
                "reason": "En ejecución: timeout aplicable sin aviso con duración ni preservación ≥20h.",
                "observed_expire": bool(t.get("observed_expire"))
            })

    ok_ratio = 1.0 if applicable == 0 else round(max(0.0, min(1.0, compliant / max(1, applicable))), 4)

    d.update({
        "applicable": applicable,
        "compliant": compliant,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders + _as_list(d.get("offenders", [])),
        "note": (d.get("note","") + " | RENDERED: verificación directa de aviso con duración o preservación ≥20h.").strip()
    })
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: propone cómo cumplir 2.2.6:
      - Mostrar aviso claro (p.ej. al iniciar el flujo) con la duración exacta: “La sesión expira tras 30 min de inactividad”.
      - Si no es posible avisar, conservar datos ≥ 20h (autosave de borradores/estado).
      - Incluir 'Mantener sesión activa' o 'Recordatorio' si aplica; explicar consecuencia (posible pérdida).
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    needs_help = (details.get("violations", 0) or 0) > 0
    if not needs_help:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "applicable": details.get("applicable", 0),
            "violations": details.get("violations", 0),
            "global_notice_with_duration": details.get("global_notice_with_duration", False),
        },
        "offenders": (details.get("offenders", []) or [])[:20],
        "html_snippet": (html_sample or "")[:2200],
    }
    prompt = (
        "Actúa como auditor WCAG 2.2.6 (Timeouts, AAA). "
        "Para cada offender, sugiere añadir aviso con duración explícita (min/seg/h), "
        "o conservar los datos al menos 20 horas. "
        "Devuelve JSON: { suggestions: [{type, reason, recommended_notice?, example_text?, persistence_strategy?, notes?}], "
        "manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_2_2_6(
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
        manual_required = ai_info.get("manual_review", False)

    # 3) Aplicabilidad / NA
    ensure_na_if_no_applicable(details, applicable_keys=("applicable",),
                               note_suffix="no se detectaron timeouts aplicables que pudieran causar pérdida de datos")

    # 4) passed / verdict / score
    passed = normalize_pass_for_applicable(details, violations_key="violations", applicable_keys=("applicable",))

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
        title=meta.get("title", "Timeouts"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
