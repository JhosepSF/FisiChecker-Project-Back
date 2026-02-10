# audits/checks/criteria/p2/c_2_2_3_no_timing.py
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

CODE = "2.2.3"

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
    Acepta: números (segundos), '5s', '3m', '2h', '120000ms'
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = _lower(v)
    if s == "":
        return None
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(ms|s|m|h)?\s*$", s)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2) or "s"
    if unit == "ms": return num / 1000.0
    if unit == "s":  return num
    if unit == "m":  return num * 60.0
    if unit == "h":  return num * 3600.0
    return None

# Meta refresh: content="5; url=/foo"
META_REFRESH_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(?:;.*)?$", re.I)

# Pistas textuales genéricas (para 'hint-only')
COUNTDOWN_HINTS = ("countdown","timer","tiempo restante","time left","session expires","expira en","timeout","tiempo limite","limite de tiempo")

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
                    "essential": False,
                    "real_time": False,
                    "source": "meta",
                })
        except Exception:
            continue
    return out

def _collect_declared_time_limits(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Usa colecciones opcionales del extractor si existen.
    Esperados (opcionales):
      - ctx.timers: [{type, seconds, essential, real_time}]
      - ctx.session_timeout: {seconds, essential?, real_time?}
      - ctx.countdown_widgets: [{seconds, essential?, real_time?}]
      - ctx.auto_advance_components: se ignoran como “límite de tiempo” (no suelen restringir funcionalidad, cubiertos por 2.2.2)
      - ctx.quiz_or_exam_timers: [{seconds, essential?}]  # si marca 'essential' no aplica
    """
    out: List[Dict[str, Any]] = []

    for t in _as_list(getattr(ctx, "timers", [])):
        if isinstance(t, dict):
            out.append({
                "type": _lower(t.get("type") or "timer"),
                "seconds": _to_seconds(t.get("seconds")),
                "essential": _bool(t.get("essential")),
                "real_time": _bool(t.get("real_time")),
                "source": "timers",
            })

    st = getattr(ctx, "session_timeout", None)
    if isinstance(st, dict):
        out.append({
            "type": "session_timeout",
            "seconds": _to_seconds(st.get("seconds")),
            "essential": _bool(st.get("essential")),
            "real_time": _bool(st.get("real_time")),
            "source": "session_timeout",
        })

    for w in _as_list(getattr(ctx, "countdown_widgets", [])):
        if isinstance(w, dict):
            out.append({
                "type": "countdown",
                "seconds": _to_seconds(w.get("seconds")),
                "essential": _bool(w.get("essential")),
                "real_time": _bool(w.get("real_time")),
                "source": "countdown_widgets",
            })

    # Si tienes una lista específica para exámenes/pruebas
    for q in _as_list(getattr(ctx, "quiz_or_exam_timers", [])):
        if isinstance(q, dict):
            out.append({
                "type": "quiz_or_exam",
                "seconds": _to_seconds(q.get("seconds")),
                "essential": _bool(q.get("essential")),
                "real_time": _bool(q.get("real_time")),
                "source": "quiz_or_exam_timers",
            })

    return out

def _collect_from_text(ctx: PageContext) -> List[Dict[str, Any]]:
    """
    Heurística textual: detecta “expira en 2:00”, “tiempo restante 30s”, etc.
    No conocemos segundos exactos → 'hint_only'.
    """
    out: List[Dict[str, Any]] = []
    txt = _lower(getattr(ctx, "page_text", "") or getattr(ctx, "title_text", ""))
    if not txt and getattr(ctx, "soup", None) is not None:
        try:
            txt = _lower(getattr(ctx, "soup").get_text())
        except Exception:
            txt = ""
    if any(h in txt for h in COUNTDOWN_HINTS):
        out.append({
            "type": "text_countdown_hint",
            "seconds": None,
            "essential": False,
            "real_time": False,
            "source": "page_text",
            "hint": "Detectado texto que sugiere límite de tiempo.",
        })
    return out

def _collect_candidates(ctx: PageContext) -> List[Dict[str, Any]]:
    cands: List[Dict[str, Any]] = []
    cands.extend(_extract_meta_refresh(ctx))
    cands.extend(_collect_declared_time_limits(ctx))
    cands.extend(_collect_from_text(ctx))
    return cands

# -------------------------------------------------------------------
# Evaluación (RAW)
# -------------------------------------------------------------------

def _is_timing_applicable(item: Dict[str, Any]) -> bool:
    """
    Aplica si hay indicio de límite de tiempo que afecta la interacción/funcionalidad.
    Excepciones de 2.2.3:
      - eventos de tiempo real (real_time=True)
      - contenido esencial con temporización (essential=True)
      - medios sincronizados no interactivos (no los recolectamos aquí)
    """
    if _bool(item.get("real_time")) or _bool(item.get("essential")):
        return False

    typ = _lower(item.get("type"))
    # ignoramos 'auto_advance' / carruseles aquí (cubiertos por 2.2.2; no es “límite” de funcionalidad)
    if typ in ("auto_advance","carousel","slider","moving","animation","auto_update"):
        return False

    # meta refresh, timeouts de sesión, countdown/quiz … sí aplican
    sec = item.get("seconds")
    has_time = isinstance(sec, (int, float)) and sec > 0.0
    hint_only = (not has_time) and (typ == "text_countdown_hint")

    return has_time or hint_only

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    RAW (estricto AAA): si existe **cualquier** temporización aplicable (y no es real_time/essential),
    es una **violación** de 2.2.3. No basta con poder ajustar/extender (eso cubre 2.2.1, pero 2.2.3 exige *sin* temporización).
    """
    items = _collect_candidates(ctx)

    examined = len(items)
    applicable = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []
    types_count: Dict[str, int] = {}

    for it in items:
        typ = _lower(it.get("type") or "timer")
        types_count[typ] = types_count.get(typ, 0) + 1

        if not _is_timing_applicable(it):
            continue

        applicable += 1
        violations += 1
        offenders.append({
            "type": typ,
            "seconds": it.get("seconds"),
            "source": it.get("source"),
            "reason": "Existe temporización que afecta la funcionalidad. 2.2.3 (AAA) requiere que no haya temporización.",
            "hint": it.get("hint")
        })

    ok_ratio = 1.0 if applicable == 0 else 0.0  # si hay algo aplicable, AAA falla

    details: Dict[str, Any] = {
        "items_examined": examined,
        "applicable": applicable,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "types_count": types_count,
        "note": (
            "RAW: 2.2.3 (AAA) requiere que la funcionalidad **no** dependa de temporización. "
            "Cualquier límite de tiempo detectado (meta refresh, session timeout, countdown/quiz, etc.) "
            "que no sea de tiempo real ni esencial, se marca como violación, aunque 2.2.1 ofrezca mitigaciones."
        )
    }
    if applicable == 0:
        details["na"] = True
        details["ok_ratio"] = None
        details["note"] += " | NA: no se detectaron dependencias de temporización aplicables para 2.2.3."
    return details

# -------------------------------------------------------------------
# RENDERED (verificación en ejecución)
# -------------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    En RENDERED, el extractor puede exponer:
      rctx.no_timing_test = [
        {
          "type": "session_timeout|meta_refresh|countdown|quiz_or_exam|other",
          "seconds": number | None,
          "real_time": bool,
          "essential": bool,
          "observed": bool,           # se observó expiración/redirección o bloqueo por tiempo
          "notes": str
        }, ...
      ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 2.2.3; no se pudo evaluar en modo renderizado."}

    d = _compute_counts_raw(rctx)
    d["rendered"] = True

    tests = _as_list(getattr(rctx, "no_timing_test", []))
    if not tests:
        d["note"] = (d.get("note","") + " | RENDERED: no se proporcionó 'no_timing_test'.").strip()
        # ➜ NA si tampoco hubo aplicables (según RAW)
        if int(d.get("applicable", 0) or 0) == 0:
            d["na"] = True
            d["ok_ratio"] = None
            d["note"] += " | RENDERED→NA: sin ítems aplicables."
        return d

    applicable = 0
    violations = 0
    offenders: List[Dict[str, Any]] = []

    for t in tests:
        if not isinstance(t, dict):
            continue

        # Excepciones AAA
        if _bool(t.get("real_time")) or _bool(t.get("essential")):
            continue

        typ = _lower(t.get("type") or "timer")
        sec = _to_seconds(t.get("seconds"))
        observed = bool(t.get("observed"))

        # Si se observó expiración/redirección/bloqueo por tiempo → violación directa
        if observed:
            applicable += 1
            violations += 1
            offenders.append({
                "type": typ,
                "seconds": sec,
                "reason": "En ejecución: se observó expiración/redirección o bloqueo dependiente del tiempo.",
            })
            continue

        # Aunque no se observe, si hay límite declarado → AAA falla
        if sec is not None and sec > 0.0:
            applicable += 1
            violations += 1
            offenders.append({
                "type": typ,
                "seconds": sec,
                "reason": "Temporización declarada. 2.2.3 exige que no exista temporización.",
            })

    ok_ratio = 1.0 if applicable == 0 else 0.0

    d.update({
        "applicable": applicable,
        "violations": violations,
        "ok_ratio": ok_ratio,
        "offenders": offenders + _as_list(d.get("offenders", [])),
        "note": (d.get("note","") + " | RENDERED: verificación directa de expiraciones/redirects/locks por tiempo.").strip()
    })
    
    if applicable == 0:
        d["na"] = True
        d["ok_ratio"] = None
        d["note"] += " | RENDERED→NA: sin ítems aplicables."
        
    return d

# -------------------------------------------------------------------
# IA opcional
# -------------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str] = None) -> Dict[str, Any]:
    """
    IA: sugiere eliminar dependencias de tiempo o convertirlas en no esenciales.
    Ejemplos:
      - Eliminar meta refresh; pedir confirmación del usuario.
      - Quitar expiraciones forzadas en formularios/pasos; guardar estado y permitir retomar.
      - Para exámenes/procesos con tiempo: justificar 'essential=True' o rediseñar para no depender del tiempo.
    """
    if ask_json is None:
        return {"ai_used": False, "ai_message": "IA no configurada.", "manual_required": False}

    offs = details.get("offenders", []) or []
    if not offs and (details.get("violations", 0) or 0) == 0:
        return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "summary": {
            "applicable": details.get("applicable", 0),
            "violations": details.get("violations", 0),
            "types_count": details.get("types_count", {}),
        },
        "offenders": offs[:20],
        "html_snippet": (html_sample or "")[:2400],
    }
    prompt = (
        "Actúa como auditor WCAG 2.2.3 (No Timing, AAA). "
        "Para cada offender, propone cómo eliminar la temporización o volverla no esencial: "
        "- Sustituir meta refresh por confirmación del usuario; "
        "- Quitar expiraciones de formularios / conservar estado y permitir retomar; "
        "- Si es una evaluación con tiempo, justificar 'essential' o rediseñar para no depender del tiempo; "
        "- Evitar bloqueos por tiempo durante tareas críticas. "
        "Devuelve JSON: { suggestions: [{type, reason, redesign?, server_fix?, ui_fix?, notes?}], manual_review?: bool, summary?: string }"
    )
    try:
        ai_resp = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ai_resp, "manual_required": bool(ai_resp.get("manual_review", False))}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# -------------------------------------------------------------------
# Orquestación
# -------------------------------------------------------------------

def run_2_2_3(
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

    is_na = bool(details.get("na")) or int(details.get("applicable", 0) or 0) == 0
    if is_na:
        details["na"] = True
        if details.get("ok_ratio") == 1:
            details["ok_ratio"] = None
        details["note"] = (details.get("note","") + " | NA: sin dependencias de temporización aplicables.").strip()

        verdict = verdict_from_counts(details, True)  # 'passed' irrelevante en NA
        score0 = score_from_verdict(verdict)
        meta = WCAG_META.get(CODE, {})
        return CriterionOutcome(
            code=CODE,
            passed=False,  # irrelevante en NA
            verdict=verdict,
            score_0_2=score0,
            details=details,
            level=meta.get("level", "AAA"),
            principle=meta.get("principle", "Operable"),
            title=meta.get("title", "Sin temporización"),
            source=src,
            score_hint=details.get("ok_ratio"),
            manual_required=False
        )
    
    # 3) passed / verdict / score
    # AAA: si hay algo aplicable, falla
    passed = (int(details.get("applicable", 0) or 0) == 0)

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
        title=meta.get("title", "Sin temporización"),
        source=src,
        score_hint=details.get("ok_ratio"),
        manual_required=manual_required
    )
