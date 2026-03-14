from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LocalOpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_s: float = 45.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s

    @classmethod
    def from_env(cls) -> "LocalOpenAICompatibleClient":
        base_url = os.getenv("LOCAL_AGENT_BASE_URL") or cls._detect_base_url()
        return cls(
            base_url=base_url,
            model=os.getenv("LOCAL_AGENT_MODEL") or cls._detect_default_model(base_url),
            api_key=os.getenv("LOCAL_AGENT_API_KEY", ""),
            timeout_s=float(os.getenv("LOCAL_AGENT_TIMEOUT_S", "45")),
        )

    def plan_json(self, *, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=True, indent=2)},
            ],
            # Many local OpenAI-compatible servers understand this. If they ignore it,
            # we still parse the returned content as JSON below.
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                raw_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Local model request failed with HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Local model endpoint is unavailable: {exc.reason}") from exc

        try:
            message = raw_payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Local model response did not contain a chat completion choice.") from exc

        content = self._extract_message_text(message.get("content"))
        if not content:
            raise RuntimeError("Local model returned an empty completion.")

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Local model returned non-JSON content: {content[:240]}") from exc

    @staticmethod
    def _extract_message_text(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    chunks.append(str(item.get("text") or ""))
            return "".join(chunks).strip()
        return ""

    @classmethod
    def _detect_base_url(cls) -> str:
        for candidate in ("http://127.0.0.1:1234/v1", "http://127.0.0.1:11434/v1"):
            if cls._probe_models_endpoint(candidate):
                return candidate
        return "http://127.0.0.1:1234/v1"

    @classmethod
    def _detect_default_model(cls, base_url: str) -> str:
        models = cls._fetch_model_ids(base_url)
        if models:
            return models[0]
        if "11434" in base_url:
            return "qwen2.5:0.5b"
        return "local-agent"

    @classmethod
    def _probe_models_endpoint(cls, base_url: str) -> bool:
        try:
            cls._fetch_models_payload(base_url, timeout_s=0.75)
            return True
        except RuntimeError:
            return False

    @classmethod
    def _fetch_model_ids(cls, base_url: str) -> list[str]:
        payload = cls._fetch_models_payload(base_url, timeout_s=1.5)
        models = payload.get("data", [])
        ids: list[str] = []
        if isinstance(models, list):
            for item in models:
                if isinstance(item, dict):
                    model_id = item.get("id")
                    if model_id:
                        ids.append(str(model_id))
        return ids

    @staticmethod
    def _fetch_models_payload(base_url: str, *, timeout_s: float) -> dict[str, Any]:
        request = Request(
            f"{base_url.rstrip('/')}/models",
            headers={"Content-Type": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Model probe failed with HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Model probe failed: {exc.reason}") from exc
