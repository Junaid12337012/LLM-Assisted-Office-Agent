from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> None:
    base_url = os.getenv("LOCAL_AGENT_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
    api_key = os.getenv("LOCAL_AGENT_API_KEY", "")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    models_request = Request(f"{base_url}/models", headers=headers, method="GET")
    try:
        with urlopen(models_request, timeout=20) as response:
            models_payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"local-server-error: HTTP {exc.code}: {detail}")
    except URLError as exc:
        raise SystemExit(f"local-server-error: {exc.reason}")

    print(json.dumps(models_payload, indent=2))


if __name__ == "__main__":
    main()
