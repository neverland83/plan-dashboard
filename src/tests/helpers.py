"""测试辅助：httpx.Client 的 Fake 实现（零网络）。"""
from __future__ import annotations


class FakeResponse:
    def __init__(self, status_code: int = 200, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json = json_data
        self.text = text if text else ("" if json_data is None else "json")

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=None  # type: ignore[arg-type]
            )


class FakeClient:
    """按 URL 子串路由到预设响应；未命中直接抛错（防止真实请求漏网）。

    routes: { url_substring: response_spec }
      response_spec 可以是 FakeResponse，或 (status, json_dict) / (status, "-text-")
    """

    def __init__(self, routes: dict):
        self.routes = routes
        self.requests: list[tuple[str, str]] = []   # (method, url) 记录，供断言

    def get(self, url: str, **_kw) -> FakeResponse:
        self.requests.append(("GET", url))
        return self._match(url)

    def post(self, url: str, **_kw) -> FakeResponse:
        self.requests.append(("POST", url))
        return self._match(url)

    def _match(self, url: str) -> FakeResponse:
        for sub, spec in self.routes.items():
            if sub in url:
                if isinstance(spec, FakeResponse):
                    return spec
                status, payload = spec
                if isinstance(payload, dict):
                    return FakeResponse(status, json_data=payload)
                return FakeResponse(status, text=payload)
        raise AssertionError(f"测试试图访问未 mock 的 URL：{url}")

    # context manager 兼容（adapters 用 with httpx.Client(...) as client）
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
