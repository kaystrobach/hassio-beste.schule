"""Async client for the beste.schule REST API.

Uses the shared aiohttp session that Home Assistant provides via
`homeassistant.helpers.aiohttp_client.async_get_clientsession`. We never
create our own session — that's a HA convention so HTTP traffic shares
connection pooling and shutdown handling.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://beste.schule/api"
TIMEOUT = aiohttp.ClientTimeout(total=30)
USER_AGENT = "ha-besteschule/0.1"


class BesteSchuleError(Exception):
    """Base class for client errors."""


class AuthError(BesteSchuleError):
    """401/403 — bad token. Raises ConfigEntryAuthFailed at the caller."""


class BesteSchuleClient:
    def __init__(
        self,
        access_token: str,
        session: aiohttp.ClientSession,
        base_url: str = BASE_URL,
    ) -> None:
        if not access_token:
            raise ValueError("access_token must not be empty")
        self._base = base_url.rstrip("/")
        self._session = session
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }

    # ---- low-level -----------------------------------------------------

    async def _get(self, path: str, **params: Any) -> Any:
        flat: list[tuple[str, str]] = []
        for k, v in params.items():
            if v is None:
                continue
            if isinstance(v, dict):
                for sub_k, sub_v in v.items():
                    flat.append((f"{k}[{sub_k}]", _stringify(sub_v)))
            else:
                flat.append((k, _stringify(v)))
        url = f"{self._base}/{path.lstrip('/')}"
        _LOGGER.debug("GET %s params=%s", url, flat)
        try:
            async with self._session.get(
                url, params=flat, headers=self._headers, timeout=TIMEOUT
            ) as resp:
                if resp.status in (401, 403):
                    raise AuthError(f"auth failed: HTTP {resp.status}")
                if resp.status >= 400:
                    text = (await resp.text())[:200]
                    raise BesteSchuleError(
                        f"HTTP {resp.status} on {path}: {text}"
                    )
                return await resp.json(content_type=None)
        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            raise BesteSchuleError(f"network error on {path}: {exc}") from exc

    async def _list(self, path: str, **params: Any) -> list[dict]:
        body = await self._get(path, **params)
        data = body.get("data") if isinstance(body, dict) else body
        if not isinstance(data, list):
            raise BesteSchuleError(f"expected list on {path}, got {type(data)}")
        return data

    # ---- high-level ----------------------------------------------------

    async def me(self) -> dict:
        body = await self._get("me")
        return body.get("data", body) if isinstance(body, dict) else body

    async def students(self) -> list[dict]:
        return await self._list("students")

    async def grades(
        self,
        student_id: int,
        include: Iterable[str] = ("subject", "teacher", "collection"),
    ) -> list[dict]:
        return await self._list(
            "grades",
            filter={"student": student_id},
            include=",".join(include),
        )

    async def finalgrades(
        self,
        student_id: int,
        interval_id: int | None = None,
        include: Iterable[str] = ("subject", "interval", "teacher"),
    ) -> list[dict]:
        flt: dict[str, Any] = {"student": student_id}
        if interval_id:
            flt["interval"] = interval_id
        return await self._list(
            "finalgrades",
            filter=flt,
            include=",".join(include),
        )

    async def journal_days(
        self,
        student_id: int,
        date_from: str | None = None,
        date_to: str | None = None,
        include: Iterable[str] = (
            "lessons",
            "lessons.subject",
            "lessons.teachers",
            "lessons.notes",
            "notes",
        ),
    ) -> list[dict]:
        flt: dict[str, Any] = {"student": student_id}
        if date_from:
            flt["date_from"] = date_from
        if date_to:
            flt["date_to"] = date_to
        return await self._list(
            "journal/days",
            filter=flt,
            include=",".join(include),
        )


def _stringify(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return ",".join(str(x) for x in v)
    return str(v)
