"""Config flow.

Two-step setup:

  1. **token** — paste a Personal Access Token. We call /me + /students
     to validate and discover children.
  2. **student** — if the token sees more than one student (typical for
     guardians with multiple kids), let the user pick which one this
     entry should track. Auto-skipped for single-student tokens.

Each created entry is identified by `student_id` (so adding the same
child twice is rejected). To track a second child or use a second
account, the user just runs the wizard again — that's the "multiple
instances" the previous add-on simulated, but here it's native HA.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthError, BesteSchuleClient, BesteSchuleError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_INTERVAL_ID,
    CONF_JOURNAL_LOOKBACK_DAYS,
    CONF_SCAN_INTERVAL_HOURS,
    CONF_STUDENT_ID,
    CONF_STUDENT_NAME,
    DEFAULT_JOURNAL_LOOKBACK_DAYS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    MAX_SCAN_INTERVAL_HOURS,
    MIN_SCAN_INTERVAL_HOURS,
)

_LOGGER = logging.getLogger(__name__)


def _student_label(s: dict) -> str:
    parts = [s.get("forename") or "", s.get("name") or ""]
    label = " ".join(p for p in parts if p).strip()
    return label or s.get("nickname") or str(s.get("id") or "?")


class BesteSchuleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the user-driven setup wizard."""

    VERSION = 1

    def __init__(self) -> None:
        self._token: str | None = None
        self._students: list[dict] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_token(user_input)

    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_ACCESS_TOKEN].strip()
            client = BesteSchuleClient(token, async_get_clientsession(self.hass))
            try:
                students = await client.students()
            except AuthError:
                errors["base"] = "invalid_auth"
            except BesteSchuleError as exc:
                _LOGGER.warning("API error during setup: %s", exc)
                errors["base"] = "cannot_connect"
            else:
                if not students:
                    errors["base"] = "no_students"
                else:
                    self._token = token
                    self._students = students
                    if len(students) == 1:
                        return await self._create_entry(students[0])
                    return await self.async_step_student()

        return self.async_show_form(
            step_id="token",
            data_schema=vol.Schema({vol.Required(CONF_ACCESS_TOKEN): str}),
            errors=errors,
            description_placeholders={
                "url": "https://beste.schule",
            },
        )

    async def async_step_student(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            chosen_id = int(user_input[CONF_STUDENT_ID])
            chosen = next(
                (s for s in self._students if int(s["id"]) == chosen_id), None
            )
            if chosen is None:
                return self.async_abort(reason="unknown_student")
            return await self._create_entry(chosen)

        options = {str(s["id"]): _student_label(s) for s in self._students}
        return self.async_show_form(
            step_id="student",
            data_schema=vol.Schema(
                {vol.Required(CONF_STUDENT_ID): vol.In(options)}
            ),
        )

    async def _create_entry(self, student: dict) -> ConfigFlowResult:
        student_id = int(student["id"])
        await self.async_set_unique_id(f"student-{student_id}")
        self._abort_if_unique_id_configured()
        label = _student_label(student)
        return self.async_create_entry(
            title=label,
            data={
                CONF_ACCESS_TOKEN: self._token,
                CONF_STUDENT_ID: student_id,
                CONF_STUDENT_NAME: label,
                CONF_INTERVAL_ID: 0,
            },
            options={
                CONF_SCAN_INTERVAL_HOURS: DEFAULT_SCAN_INTERVAL_HOURS,
                CONF_JOURNAL_LOOKBACK_DAYS: DEFAULT_JOURNAL_LOOKBACK_DAYS,
            },
        )

    # ---- re-auth flow when the token expires --------------------------

    async def async_step_reauth(
        self, _entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            token = user_input[CONF_ACCESS_TOKEN].strip()
            client = BesteSchuleClient(token, async_get_clientsession(self.hass))
            try:
                await client.me()
            except AuthError:
                errors["base"] = "invalid_auth"
            except BesteSchuleError as exc:
                _LOGGER.warning("API error during re-auth: %s", exc)
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_ACCESS_TOKEN: token},
                    reason="reauth_successful",
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_ACCESS_TOKEN): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BesteSchuleOptionsFlow(config_entry)


class BesteSchuleOptionsFlow(OptionsFlow):
    """Lets the user change the scan interval / journal lookback later."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self._entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL_HOURS,
                        default=opts.get(
                            CONF_SCAN_INTERVAL_HOURS,
                            DEFAULT_SCAN_INTERVAL_HOURS,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_SCAN_INTERVAL_HOURS,
                            max=MAX_SCAN_INTERVAL_HOURS,
                        ),
                    ),
                    vol.Required(
                        CONF_JOURNAL_LOOKBACK_DAYS,
                        default=opts.get(
                            CONF_JOURNAL_LOOKBACK_DAYS,
                            DEFAULT_JOURNAL_LOOKBACK_DAYS,
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=90)),
                }
            ),
        )
