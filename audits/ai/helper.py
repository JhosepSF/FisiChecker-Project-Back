# audits/ai/helper.py
from typing import Optional, Dict, Any
from .ollama_client import ask_json


class AiHelper:
    def __init__(self, model: Optional[str] = None, timeout: int = 300):
        self.model = model or "llama3.1:latest"
        self.timeout = timeout

    def evaluate_criterion(self, prompt: str, context: str = "") -> Dict[str, Any]:
        """
        Devuelve dict con: { verdict ('pass'|'partial'|'fail'|'na'), score_0_2:int, explanation:str }
        """
        json_resp = ask_json(
            prompt=prompt,
            context=context,
            model=self.model,
            timeout=self.timeout,
        )
        # Normalización mínima
        v = (json_resp.get("verdict") or "partial").lower()
        if v not in {"pass","partial","fail","na"}:
            v = "partial"
        score = json_resp.get("score_0_2")
        try:
            score = int(score) if score is not None else None
        except Exception:
            score = None
        return {
            "verdict": v,
            "score_0_2": score,
            "explanation": json_resp.get("explanation") or ""
        }
