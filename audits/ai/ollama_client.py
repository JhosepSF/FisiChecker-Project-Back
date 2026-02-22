# audits/ai/ollama_client.py
import os
import json
import re
import time
import logging
import requests
from typing import Optional, Dict, Any, List, Union, Tuple
from django.conf import settings

logger = logging.getLogger("audits.ai")

# === Config basado en settings o entorno ===
OLLAMA_HOST = getattr(settings, "OLLAMA_HOST", os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
DEFAULT_MODEL = getattr(settings, "OLLAMA_MODEL", os.environ.get("OLLAMA_MODEL", "llama3.1:latest"))

# Reutiliza conexiones HTTP (más estable y rápido)
_SESSION = requests.Session()


class OllamaClientError(Exception):
    pass


def _build_options(
    temperature: float,
    max_tokens: int,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Construye el objeto 'options' seguro para Ollama."""
    opts: Dict[str, Any] = {
        "temperature": float(temperature),
        "num_predict": int(max_tokens),
    }
    if isinstance(options, dict):
        opts.update(options)
    return opts


def _safe_preview(text: str, limit: int = 2000) -> str:
    """Recorta texto para logs (evita logs gigantes)."""
    if not text:
        return ""
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "…(trunc)"


def _post_json(url: str, payload: Dict[str, Any], timeout: int) -> requests.Response:
    """
    POST con timeout separado (connect, read) y logs útiles.
    - connect timeout corto para no quedarse colgado si el host no responde
    - read timeout configurable (timeout)
    """
    # 5s para conectar, `timeout` para leer respuesta
    return _SESSION.post(url, json=payload, timeout=(5, timeout))


def ollama_chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 800,
    options: Optional[Dict[str, Any]] = None,
    timeout: int = 300,
) -> str:
    """
    Llama a /api/chat con una lista de mensajes:
    [{"role":"system"/"user"/"assistant","content":"..."}].
    Retorna el contenido final del asistente como string (NUNCA None).
    """
    url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
    payload: Dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "stream": False,
        "options": _build_options(temperature, max_tokens, options),
    }

    try:
        r = _post_json(url, payload, timeout=timeout)

        # Si no vino JSON, loguea rápido el body para diagnóstico
        ct = r.headers.get("Content-Type", "")
        if "application/json" not in ct.lower():
            logger.error(
                "Ollama chat non-JSON response status=%s content-type=%s body=%s",
                r.status_code, ct, _safe_preview(r.text)
            )

        r.raise_for_status()

        try:
            data = r.json()
        except Exception:
            logger.exception("Ollama chat: failed to decode JSON. body=%s", _safe_preview(r.text))
            raise OllamaClientError("Ollama chat: response is not valid JSON")

        msg = data.get("message", {}) if isinstance(data, dict) else {}
        content = msg.get("content") if isinstance(msg, dict) else ""
        return (content or "").strip()

    except requests.exceptions.RequestException:
        # Aquí entran timeout, connection error, http error, etc.
        status = getattr(locals().get("r", None), "status_code", None)
        body = getattr(locals().get("r", None), "text", "")
        logger.exception("Ollama chat request failed status=%s body=%s", status, _safe_preview(body))
        raise OllamaClientError(f"Ollama chat request failed (status={status})")
    except OllamaClientError:
        raise
    except Exception:
        logger.exception("Ollama chat unexpected error")
        raise OllamaClientError("Ollama chat unexpected error")


def ollama_generate(
    prompt: str,
    model: Optional[str] = None,
    system: str = "",
    temperature: float = 0.1,
    max_tokens: int = 800,
    json_mode: bool = False,
    options: Optional[Dict[str, Any]] = None,
    timeout: int = 300,
) -> str:
    """
    Intento de /api/generate (single prompt).
    Si el servidor responde 404 (endpoint no soportado), se usa /api/chat como fallback.
    Retorna texto (string), nunca None.
    """
    url = f"{OLLAMA_HOST.rstrip('/')}/api/generate"
    base_prompt = prompt
    if json_mode:
        base_prompt += "\n\nResponde SOLO en JSON válido, sin comentarios ni texto adicional."

    payload: Dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "prompt": base_prompt,
        "stream": False,
        "options": _build_options(temperature, max_tokens, options),
    }

    # 'system' no está formalmente soportado en /api/generate → lo inyectamos en el prompt.
    if system:
        payload["prompt"] = f"SISTEMA:\n{system.strip()}\n\nUSUARIO:\n{payload['prompt']}"

    try:
        r = _post_json(url, payload, timeout=timeout)

        # Si generate no existe -> fallback a chat
        if r.status_code == 404:
            messages: List[Dict[str, str]] = []
            if system:
                messages.append({"role": "system", "content": system})
            u_prompt = base_prompt
            if json_mode:
                u_prompt += "\n\nResponde SOLO en JSON válido."
            messages.append({"role": "user", "content": u_prompt})
            return ollama_chat(
                messages=messages,
                model=model or DEFAULT_MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
                options=options,
                timeout=timeout,
            )

        ct = r.headers.get("Content-Type", "")
        if "application/json" not in ct.lower():
            logger.error(
                "Ollama generate non-JSON response status=%s content-type=%s body=%s",
                r.status_code, ct, _safe_preview(r.text)
            )

        r.raise_for_status()

        try:
            data = r.json()
        except Exception:
            logger.exception("Ollama generate: failed to decode JSON. body=%s", _safe_preview(r.text))
            raise OllamaClientError("Ollama generate: response is not valid JSON")

        content = data.get("response") if isinstance(data, dict) else ""
        return (content or "").strip()

    except requests.exceptions.RequestException:
        status = getattr(locals().get("r", None), "status_code", None)
        body = getattr(locals().get("r", None), "text", "")
        logger.exception("Ollama generate request failed status=%s body=%s", status, _safe_preview(body))
        raise OllamaClientError(f"Ollama generate request failed (status={status})")
    except OllamaClientError:
        raise
    except Exception:
        logger.exception("Ollama generate unexpected error")
        raise OllamaClientError("Ollama generate unexpected error")


# =========================
# Normalización de respuestas
# =========================

def _strip_code_fences(text: str) -> str:
    """Quita ```...``` o ```json ...``` para facilitar el parseo."""
    if not text:
        return ""
    s = text.strip()
    s = re.sub(r"^\s*```(?:json)?\s*", "", s, flags=re.I)
    s = re.sub(r"\s*```\s*$", "", s, flags=re.I)
    return s.strip()


def _raw_decode_first_json(s: str) -> Tuple[bool, Any, Optional[str]]:
    """
    Intenta extraer el primer JSON válido desde el string usando JSONDecoder.raw_decode.
    Útil cuando el modelo mete texto antes/después.
    """
    if not s:
        return False, None, "empty"
    dec = json.JSONDecoder()
    s2 = s.lstrip()
    try:
        obj, _idx = dec.raw_decode(s2)
        return True, obj, None
    except Exception as e:
        return False, None, str(e)


def _try_json_variants(txt: str) -> Tuple[bool, Union[Dict[str, Any], List[Any], None], Optional[str]]:
    """
    Intenta parsear JSON en varias formas:
      - texto completo
      - raw_decode (primer JSON válido)
      - primer objeto {...} (no greedy, lo más corto)
      - primer array [...]
    Devuelve (ok, obj, error_msg)
    """
    if not txt:
        return False, None, "empty"

    s = _strip_code_fences(txt)

    # 1) Intento directo
    try:
        obj = json.loads(s)
        return True, obj, None
    except Exception as e1:
        err1 = str(e1)

    # 2) Intento raw_decode (primer JSON válido al inicio tras lstrip)
    ok2, obj2, err2 = _raw_decode_first_json(s)
    if ok2:
        return True, obj2, None

    # 3) Extraer primer objeto { ... } (no greedy: el más corto posible)
    try:
        m = re.search(r"\{.*?\}", s, re.S)
        if m:
            obj = json.loads(m.group(0))
            return True, obj, None
    except Exception as e3:
        err3 = str(e3)
    else:
        err3 = None

    # 4) Extraer primer array [ ... ] (no greedy)
    try:
        m = re.search(r"\[.*?\]", s, re.S)
        if m:
            obj = json.loads(m.group(0))
            return True, obj, None
    except Exception as e4:
        err4 = str(e4)
    else:
        err4 = None

    joined_errs = "; ".join([e for e in (err1, err2, err3, err4) if e])
    return False, None, joined_errs or "json parse failed"


def _coerce_to_dict(obj: Any) -> Dict[str, Any]:
    """
    Garantiza dict:
      - dict → dict
      - list → {"data": list}
      - str  → {"text": str}
      - None → {"text": ""}
      - otro → {"data": obj}
    """
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, list):
        return {"data": obj}
    if isinstance(obj, (bytes, bytearray)):
        try:
            return {"text": obj.decode("utf-8", "ignore")}
        except Exception:
            return {"data": obj}
    if isinstance(obj, str):
        return {"text": obj}
    if obj is None:
        return {"text": ""}
    return {"data": obj}


# =========================
# API de alto nivel (SIEMPRE dict)
# =========================

def ask_json(
    prompt: str,
    context: str = "",
    system: str = "",
    model: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 800,
    timeout: int = 300,
    max_retries: int = 2,
) -> Dict[str, Any]:
    """
    Pide explícitamente JSON usando /api/chat.
    GARANTIZA devolver Dict[str, Any] para que el resto del código pueda usar .get(...) sin romper.
    """
    user_prompt = prompt
    if context:
        user_prompt += f"\n\nContexto (JSON/Texto):\n{context[:8000]}"
    user_prompt += "\n\nResponde SOLO en JSON válido (sin backticks ni comentarios)."

    messages: List[Dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_prompt})

    last_text = ""
    last_err = ""

    for attempt in range(max_retries + 1):
        try:
            txt = ollama_chat(
                messages=messages,
                model=model or DEFAULT_MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            last_text = txt or ""
            ok, obj, err = _try_json_variants(last_text)
            if ok:
                return _coerce_to_dict(obj)
            last_err = err or "json parse failed"

        except OllamaClientError as e:
            last_text = f"LLM error: {e}"
            last_err = str(e)
            logger.exception("ask_json OllamaClientError attempt=%s", attempt)

        except Exception as e:
            last_text = f"LLM error: {e}"
            last_err = str(e)
            logger.exception("ask_json unexpected error attempt=%s", attempt)

        # Reintento: reforzar instrucción + backoff corto
        if attempt < max_retries:
            messages[-1]["content"] += (
                "\n\nATENCIÓN: Responde SOLO en JSON plano (objeto o arreglo) sin ``` ni explicaciones."
                "\nSi fallas, responde únicamente con el JSON sin texto adicional."
            )
            time.sleep(0.5 * (2 ** attempt))
            continue

    # Fallback si falla todo → SIEMPRE dict
    return {
        "text": last_text,
        "parse_error": True,
        "error": last_err,
        "message": "No fue posible parsear la respuesta del modelo como JSON válido.",
    }