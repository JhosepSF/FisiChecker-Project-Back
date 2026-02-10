# audits/checks/criteria/p4/c_4_1_3_status_messages.py
from typing import Dict, Any, List, Optional, Tuple
import re

from ....wcag.context import PageContext
from ....wcag.constants import WCAG_META
from ..base import CriterionOutcome, CheckMode, verdict_from_counts, score_from_verdict
from ..applicability import ensure_na_if_no_applicable, normalize_pass_for_applicable

try:
    from ....ai.ollama_client import ask_json
except Exception:
    ask_json = None

CODE = "4.1.3"

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

# Palabras clave típicas de mensajes de estado (éxito/advertencia/error/info/toast)
STATUS_TEXT_RE = re.compile(
    r"(exito|éxito|correcto|guardado|enviado|actualizado|"
    r"error|fall[oó]|inv[aá]lido|advertencia|warning|alerta|"
    r"info|informaci[oó]n|notificaci[oó]n|toast|"
    r"progreso|cargando|loading|completado|finalizado)",
    re.I
)

# Roles/atributos que exponen mensajes a AT sin mover el foco
ANNOUNCE_ROLES = {"status", "alert", "log", "progressbar", "timer", "marquee"}
LIVE_OK = {"polite", "assertive"}

def _as_list(x):
    if not x: return []
    if isinstance(x, list): return x
    return list(x)

def _s(v: Any) -> str:
    return "" if v is None else str(v)

def _lower(v: Any) -> str:
    return _s(v).strip().lower()

def _get_attr(node: Any, name: str) -> Optional[str]:
    try:
        if isinstance(node, dict):
            val = node.get(name);  return _s(val) if val is not None else None
        if hasattr(node, "get"):
            val = node.get(name)  # type: ignore[attr-defined]
            return _s(val) if val is not None else None
    except Exception:
        pass
    return None

def _get_text(node: Any) -> str:
    if isinstance(node, dict):
        for k in ("text","inner_text","aria-label","title","label"):
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

def _iter_potential_messages(ctx: PageContext):
    """
    Recorre nodos que suelen contener mensajes: [role in ANNOUNCE_ROLES], [aria-live], 
    y elementos con clases/palabras clave 'alert|error|success|toast|notification|progress'
    """
    soup = getattr(ctx, "soup", None)
    nodes: List[Any] = []
    if soup is None:
        # Fallback: usa una lista plana si el extractor la provee
        nodes = _as_list(getattr(ctx, "message_nodes", []))
        for n in nodes:
            yield n
        return

    try:
        # Roles con live region por defecto
        for r in ANNOUNCE_ROLES:
            nodes += list(soup.find_all(attrs={"role": r}))
    except Exception:
        pass
    try:
        nodes += list(soup.find_all(attrs={"aria-live": True}))
    except Exception:
        pass
    try:
        # señales por clase
        for cls in ("alert", "error", "success", "toast", "notification", "progress"):
            nodes += list(soup.find_all(class_=re.compile(cls, re.I)))
    except Exception:
        pass

    # quitar duplicados simples
    seen = set()
    for el in nodes:
        try:
            key = id(el)
            if key in seen: 
                continue
            seen.add(key)
            yield el
        except Exception:
            continue

def _is_announced(node: Any) -> bool:
    role = _lower(_get_attr(node, "role"))
    if role in ANNOUNCE_ROLES:
        return True
    live = _lower(_get_attr(node, "aria-live"))
    if live in LIVE_OK:
        return True
    # algunos frameworks usan aria-atomic/aria-relevant sin aria-live explícito → no contamos
    return False

# ------------------------------------------------------------
# RAW
# ------------------------------------------------------------

def _compute_counts_raw(ctx: PageContext) -> Dict[str, Any]:
    """
    4.1.3 (AA) — Mensajes de estado: 
      - Los mensajes (error/éxito/info/progreso) deben ser anunciados por AT sin mover el foco.
      - Aceptamos role=status/alert/log/progressbar/timer/marquee o aria-live=polite|assertive.
      - Señalamos contenedores con texto de status sin role/aria-live como violación.
    """
    soup = getattr(ctx, "soup", None)
    if soup is None:
        # si no hay DOM, intentar con texto plano de página
        txt = _s(getattr(ctx, "document_text", ""))
        return {
            "na": True,
            "note": "Sin DOM; 4.1.3 requiere revisar live regions. Se sugiere RENDERED.",
            "found_keywords": bool(STATUS_TEXT_RE.search(txt or "")),
            "ok_ratio": 1.0
        }

    applicable = 0
    announced = 0
    unannounced = 0
    offenders: List[Dict[str, Any]] = []

    for el in _iter_potential_messages(ctx):
        t = _get_text(el)
        if not t or not STATUS_TEXT_RE.search(t):
            # si el extractor había marcado explicitamente message_nodes sin texto, ignoramos
            continue
        applicable += 1
        if _is_announced(el):
            announced += 1
        else:
            unannounced += 1
            offenders.append({
                "tag": _s(getattr(el, "name", "")),
                "text": t[:180],
                "reason": "Mensaje de estado sin role de live region ni aria-live."
            })

    ok_ratio = 1.0 if applicable == 0 else max(0.0, min(1.0, announced / max(1, applicable)))
    return {
        "applicable": applicable,
        "announced": announced,
        "unannounced": unannounced,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": (
            "RAW: identifica mensajes por palabras clave y verifica role=status/alert/log/progressbar/timer/marquee o aria-live. "
            "Sin esas pistas, el mensaje puede no anunciarse a usuarios de lector de pantalla."
        )
    }

# ------------------------------------------------------------
# RENDERED
# ------------------------------------------------------------

def _compute_counts_rendered(rctx: Optional[PageContext]) -> Dict[str, Any]:
    """
    rctx.status_messages_test = [
      { "selector": str, "text": str, "is_status_like": bool, "is_announced": bool, "role": str|None, "aria_live": str|None, "notes": str|None }
    ]
    """
    if rctx is None:
        return {"na": True, "note": "No se proveyó rendered_ctx para 4.1.3; no se pudo evaluar en modo renderizado."}

    data = _as_list(getattr(rctx, "status_messages_test", []))
    if not data:
        d = _compute_counts_raw(rctx); d["rendered"]=True
        d["note"] = d.get("note","") + " | RENDERED: sin 'status_messages_test', se reusó RAW."
        return d

    applicable = 0
    announced = 0
    unannounced = 0
    offenders: List[Dict[str, Any]] = []

    for it in data:
        if not isinstance(it, dict): continue
        if not bool(it.get("is_status_like")): continue
        applicable += 1
        if bool(it.get("is_announced")):
            announced += 1
        else:
            unannounced += 1
            offenders.append({
                "selector": _s(it.get("selector")),
                "text": _s(it.get("text"))[:180],
                "role": _s(it.get("role")),
                "aria_live": _s(it.get("aria_live")),
                "reason": "Mensaje de estado no anunciado (runtime).",
                "notes": _s(it.get("notes"))
            })

    ok_ratio = 1.0 if applicable == 0 else max(0.0, min(1.0, announced / max(1, applicable)))
    return {
        "rendered": True,
        "applicable": applicable,
        "announced": announced,
        "unannounced": unannounced,
        "ok_ratio": ok_ratio,
        "offenders": offenders,
        "note": "RENDERED: verificación de anuncio efectivo (por el runner) de mensajes de estado."
    }

# ------------------------------------------------------------
# IA opcional
# ------------------------------------------------------------

def _ai_review(details: Dict[str, Any], html_sample: Optional[str]=None) -> Dict[str, Any]:
    if ask_json is None:
        return {"ai_used": False, "manual_required": False, "ai_message":"IA no configurada."}
    need = int(details.get("unannounced", 0) or 0) > 0
    if not need: return {"ai_used": False, "manual_required": False}

    ctx_json = {
        "offenders": (details.get("offenders", []) or [])[:25],
        "html_snippet": (html_sample or "")[:2200],
        "recipes": [
            "<div role='status' aria-live='polite'>Guardado correctamente</div>",
            "<div role='alert'>Error al enviar. Revisa los campos resaltados.</div>",
            "Para barras de progreso, actualizar aria-valuenow y usar role='progressbar'."
        ]
    }
    prompt = (
        "Eres auditor WCAG 4.1.3 (Status Messages, AA). "
        "Convierte los contenedores de mensajes en live regions accesibles. "
        "Devuelve JSON: {suggestions:[{selector?, snippet, rationale}], manual_review?:bool, summary?:string }"
    )
    try:
        ans = ask_json(prompt=prompt, context=str(ctx_json))
        return {"ai_used": True, "ai_review": ans, "manual_required": False}
    except Exception as e:
        return {"ai_used": False, "ai_error": str(e), "manual_required": False}

# ------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------

def run_4_1_3(
    ctx: PageContext,
    mode: CheckMode=CheckMode.RAW,
    rendered_ctx: Optional[PageContext]=None,
    html_for_ai: Optional[str]=None
) -> CriterionOutcome:

    if mode == CheckMode.RENDERED:
        if rendered_ctx is None:
            details=_compute_counts_raw(ctx); details["warning"]="Se pidió RENDERED sin rendered_ctx; fallback a RAW."; src="raw"
        else:
            details=_compute_counts_rendered(rendered_ctx); src="rendered"
    else:
        details=_compute_counts_raw(ctx); src="raw"

    manual_required=False
    if mode == CheckMode.AI:
        ai=_ai_review(details, html_sample=html_for_ai); details["ai_info"]=ai; src="ai"
        manual_required=bool(ai.get("manual_review", False))

    # Aplicabilidad / NA
    ensure_na_if_no_applicable(details, applicable_keys=("applicable",),
                               note_suffix="no se detectaron mensajes de estado en el ámbito evaluado")

    # Ultra estricto: PASS solo si 100%, PARTIAL >= 80%, FAIL < 80%
    applicable = int(details.get("applicable", 0) or 0)
    unannounced = int(details.get("unannounced", 0) or 0)
    
    if applicable == 0:
        passed = False  # NA
        details["ratio"] = None
    elif unannounced == 0:
        passed = True
        details["ratio"] = 1.0
    else:
        ok_count = applicable - unannounced
        ratio = ok_count / applicable
        details["ratio"] = ratio
        # PARTIAL si >= 80%, FAIL si < 80%
        if ratio >= 0.80:
            passed = True  # verdict_from_counts detectará partial
        else:
            passed = False

    verdict = verdict_from_counts(details, passed)
    score0=score_from_verdict(verdict)
    meta=WCAG_META.get(CODE, {})
    return CriterionOutcome(
        code=CODE, passed=passed, verdict=verdict, score_0_2=score0, details=details,
        level=meta.get("level","AA"), principle=meta.get("principle","Robusto"),
        title=meta.get("title","Mensajes de estado"),
        source=src, score_hint=details.get("ok_ratio"), manual_required=manual_required
    )
