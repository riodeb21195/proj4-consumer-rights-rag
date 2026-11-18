"""Thin HTTP client for the RAG API (the UI never talks to the database directly)."""

from __future__ import annotations

from typing import Any

import httpx


class ApiError(RuntimeError):
    pass


class ApiClient:
    def __init__(self, base_url: str, client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=180.0)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> object:
        try:
            resp = self.client.request(method, f"{self.base_url}{path}", json=payload)
        except httpx.HTTPError as exc:
            raise ApiError(f"API not reachable: {exc}") from exc
        if resp.status_code >= 400:
            detail = resp.json().get("detail", resp.text) if resp.content else resp.reason_phrase
            raise ApiError(f"API error {resp.status_code}: {detail}")
        return resp.json()

    def ask(self, question: str, k: int = 5, mode: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"question": question, "k": k}
        if mode:
            payload["mode"] = mode
        result = self._request("POST", "/ask", payload)
        assert isinstance(result, dict)
        return result

    def evaluation(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/evaluation")
        assert isinstance(result, list)
        return result

    def health(self) -> dict[str, Any]:
        result = self._request("GET", "/health")
        assert isinstance(result, dict)
        return result


def evaluation_table(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Latest result per variant, flattened for display."""
    latest: dict[str, dict[str, Any]] = {}
    for result in results:  # API returns oldest first
        latest[str(result["variant"])] = result
    rows = []
    for variant, result in sorted(latest.items()):
        row: dict[str, Any] = {"variant": variant, "created_at": result.get("created_at", "")}
        row.update({k: round(float(v), 3) for k, v in result["metrics"].items()})
        row["questions"] = result.get("n_questions")
        rows.append(row)
    return rows
