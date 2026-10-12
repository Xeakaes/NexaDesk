"""GitHub Copilot provider (OpenAI-compatible chat completions).

Auth is a two-step flow: the user's GitHub PAT is exchanged for a short-lived
Copilot token at ``copilot_internal/v2/token``; that token (plus the editor
identity headers Copilot requires) authorizes ``/chat/completions`` and
``/models``. The exchanged token is cached and refreshed before expiry.
"""

from __future__ import annotations

import time

import requests

from core.providers.base import ProviderError
from core.providers.openai_compatible import OpenAICompatibleProvider

_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
_BASE_URL = "https://api.github.com/copilot"
# Copilot gates the API on an editor identity; values are not verified against
# a whitelist, any consistent editor string works (third-party clients do this).
_EDITOR_HEADERS = {
    "Editor-Version": "GitHubCopilotChat/0.0.1",
    "Editor-Plugin-Version": "copilot-chat/0.0.1",
    "Copilot-Integration-Id": "vscode-chat",
}
_TOKEN_REFRESH_MARGIN_S = 60.0
_DEFAULT_TOKEN_TTL_S = 1500.0  # Copilot tokens live ~30 minutes


class GitHubCopilotProvider(OpenAICompatibleProvider):
    supports_tools = True
    supports_vision = True

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_s: float = 60.0,
        session: requests.Session | None = None,
        supports_vision: bool = True,
    ) -> None:
        super().__init__(
            base_url=_BASE_URL,
            api_key=api_key,
            model=model,
            timeout_s=timeout_s,
            session=session,
            supports_vision=supports_vision,
            provider_key="github",
        )
        self._copilot_token: str | None = None
        self._token_expires_at: float = 0.0

    def _exchange_token(self) -> None:
        """Trade the PAT for a short-lived Copilot token."""
        try:
            resp = self._session.post(
                _TOKEN_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    **_EDITOR_HEADERS,
                },
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            raise ProviderError(
                "github copilot token exchange failed (network)",
                error_code="provider_error",
            ) from exc
        if resp.status_code in (401, 403):
            raise ProviderError(
                "github copilot token exchange was rejected — check the PAT "
                "and that the account has Copilot access",
                error_code="unauthorized",
            )
        if resp.status_code != 200:
            raise ProviderError(
                f"github copilot token exchange failed (HTTP "
                f"{resp.status_code})",
                error_code="provider_error",
            )
        try:
            data = resp.json()
            token = data["token"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError(
                "github copilot token exchange returned a malformed response",
                error_code="provider_error",
            ) from exc
        self._copilot_token = token
        try:
            self._token_expires_at = float(
                data.get("expires_at") or (time.time() + _DEFAULT_TOKEN_TTL_S)
            )
        except (TypeError, ValueError):
            self._token_expires_at = time.time() + _DEFAULT_TOKEN_TTL_S

    def _ensure_token(self) -> str:
        if (
            self._copilot_token
            and time.time() < self._token_expires_at - _TOKEN_REFRESH_MARGIN_S
        ):
            return self._copilot_token
        self._exchange_token()
        return self._copilot_token or ""

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._ensure_token()}",
            **_EDITOR_HEADERS,
        }

    # list_models() is inherited: GET {base_url}/models with the exchanged
    # token (Copilot answers the standard {"data": [{"id": ...}]} catalog).
