"""DataUpdateCoordinator for one beste.schule account/student.

Each ConfigEntry creates one coordinator instance. The coordinator:

  * Polls the API on a schedule (default 24h).
  * Diffs grades against the previous snapshot stored in HA's persistent
    Storage helper.
  * Fires `besteschule_grade_added/changed/removed/...` events on the HA
    bus when something differs.
  * Returns a `data` dict that the sensor entities read from.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthError, BesteSchuleClient, BesteSchuleError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_INTERVAL_ID,
    CONF_JOURNAL_LOOKBACK_DAYS,
    CONF_SCAN_INTERVAL_HOURS,
    CONF_STUDENT_ID,
    CONF_STUDENT_NAME,
    CONF_CALENDAR_LOOKAHEAD_WEEKS,
    CONF_CALENDAR_DELETE_AFTER_DAYS,
    DATA_AVERAGE,
    DATA_FETCHED_AT,
    DATA_FINALGRADES,
    DATA_GRADES,
    DATA_JOURNAL,
    DATA_STUDENT_ID,
    DATA_STUDENT_LABEL,
    DEFAULT_JOURNAL_LOOKBACK_DAYS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DEFAULT_CALENDAR_LOOKAHEAD_WEEKS,
    DEFAULT_CALENDAR_DELETE_AFTER_DAYS,
    DOMAIN,
    EVENT_GRADES_UPDATED,
    EVENT_GRADE_ADDED,
    EVENT_GRADE_CHANGED,
    EVENT_GRADE_REMOVED,
)
from .diff import diff_grades, grade_signature
from .formatter import average

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1


class BesteSchuleCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Per-entry coordinator. One per child."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        scan_hours = entry.options.get(
            CONF_SCAN_INTERVAL_HOURS,
            entry.data.get(CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}-{entry.title}",
            update_interval=timedelta(hours=int(scan_hours)),
        )
        self.entry = entry
        self.client = BesteSchuleClient(
            entry.data[CONF_ACCESS_TOKEN],
            async_get_clientsession(hass),
        )
        self._student_id: int = int(entry.data[CONF_STUDENT_ID])
        self._student_label: str = entry.data.get(CONF_STUDENT_NAME) or str(
            self._student_id
        )
        self._interval_id: int = int(entry.data.get(CONF_INTERVAL_ID) or 0)
        self._store: Store = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.snapshot"
        )
        self._snapshot_loaded = False
        self._had_previous_snapshot = False
        self._previous_signatures: list[dict] = []

    @property
    def student_id(self) -> int:
        return self._student_id

    @property
    def student_label(self) -> str:
        return self._student_label

    # ---- main loop -----------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        if not self._snapshot_loaded:
            stored = await self._store.async_load()
            if stored is not None:
                self._had_previous_snapshot = True
                self._previous_signatures = stored.get("grades") or []
            self._snapshot_loaded = True

        try:
            try:
                grades = await self.client.grades(self._student_id)
            except BesteSchuleError as exc:
                _LOGGER.error("Error fetching grades: %s", exc)
                grades = self.data.get(DATA_GRADES) or [] if self.data else []

            try:
                finals = await self.client.finalgrades(
                    self._student_id, interval_id=self._interval_id or None
                )
            except BesteSchuleError as exc:
                _LOGGER.error("Error fetching final grades: %s", exc)
                finals = self.data.get(DATA_FINALGRADES) or [] if self.data else []

            lookback = self.entry.options.get(
                CONF_JOURNAL_LOOKBACK_DAYS,
                self.entry.data.get(
                    CONF_JOURNAL_LOOKBACK_DAYS, DEFAULT_JOURNAL_LOOKBACK_DAYS
                ),
            )
            lookahead = self.entry.options.get(
                CONF_CALENDAR_LOOKAHEAD_WEEKS,
                self.entry.data.get(
                    CONF_CALENDAR_LOOKAHEAD_WEEKS, DEFAULT_CALENDAR_LOOKAHEAD_WEEKS
                ),
            )
            delete_after = self.entry.options.get(
                CONF_CALENDAR_DELETE_AFTER_DAYS,
                self.entry.data.get(
                    CONF_CALENDAR_DELETE_AFTER_DAYS, DEFAULT_CALENDAR_DELETE_AFTER_DAYS
                ),
            )

            journal_days: list[dict] = []
            if lookback > 0 or lookahead > 0:
                now = datetime.now(timezone.utc)

                # We want to fetch weeks from 'lookback' days ago up to 'lookahead' weeks from now.
                # However, the API works by ISO weeks.
                # To be safe, we fetch the current week, and 'lookahead' future weeks.
                # If lookback > 7, we might need previous weeks too.

                weeks_to_fetch: set[str] = set()

                # Current week
                year, week, _ = now.isocalendar()
                weeks_to_fetch.add(f"{year}-{week:02d}")

                # Future weeks
                for i in range(1, lookahead + 1):
                    future_dt = now + timedelta(weeks=i)
                    f_year, f_week, _ = future_dt.isocalendar()
                    weeks_to_fetch.add(f"{f_year}-{f_week:02d}")

                # Past weeks (if lookback is large)
                if lookback > 7:
                    for i in range(1, (lookback // 7) + 1):
                        past_dt = now - timedelta(weeks=i)
                        p_year, p_week, _ = past_dt.isocalendar()
                        weeks_to_fetch.add(f"{p_year}-{p_week:02d}")

                for yw in sorted(weeks_to_fetch):
                    try:
                        result = await self.client.journal_week(self._student_id, yw)
                        if isinstance(result, list):
                            weeks = result
                        elif isinstance(result, dict):
                            weeks = [result]
                        else:
                            weeks = []

                        for w in weeks:
                            days = w.get("days") or []
                            journal_days.extend(days)
                    except BesteSchuleError as exc:
                        _LOGGER.warning("Failed to fetch journal week %s: %s", yw, exc)

                if not journal_days and self.data and self.data.get(DATA_JOURNAL):
                    journal_days = self.data.get(DATA_JOURNAL)
                else:
                    # Deduplicate days by date if any
                    seen_dates = set()
                    dedup_days = []
                    for d in journal_days:
                        dt_str = d.get("date")
                        if dt_str not in seen_dates:
                            dedup_days.append(d)
                            seen_dates.add(dt_str)
                    journal_days = dedup_days

                    # Filter by delete_after
                    if delete_after > 0:
                        cutoff = (now - timedelta(days=delete_after)).date()
                        journal_days = [
                            d for d in journal_days
                            if not d.get("date") or datetime.strptime(d["date"], "%Y-%m-%d").date() >= cutoff
                        ]
            elif self.data:
                journal_days = self.data.get(DATA_JOURNAL) or []
        except AuthError as exc:
            # Tells HA to surface a "re-authentication required" notification.
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except BesteSchuleError as exc:
            # Tells the coordinator the fetch failed; previous data stays around.
            raise UpdateFailed(str(exc)) from exc

        # Diff against the previous snapshot. Skipped on the very first run
        # after install, otherwise the user would get bombarded with "added"
        # events for every existing grade.
        new_signatures = [grade_signature(g) for g in grades]
        if self._had_previous_snapshot:
            self._fire_change_events(self._previous_signatures, grades)
        self._previous_signatures = new_signatures
        await self._store.async_save({"grades": new_signatures})
        self._had_previous_snapshot = True

        fetched_at = datetime.now(timezone.utc)
        return {
            DATA_GRADES: grades,
            DATA_FINALGRADES: finals,
            DATA_JOURNAL: journal_days,
            DATA_STUDENT_LABEL: self._student_label,
            DATA_STUDENT_ID: self._student_id,
            DATA_FETCHED_AT: fetched_at,
            DATA_AVERAGE: average(grades),
        }

    # ---- helpers -------------------------------------------------------

    def _fire_change_events(
        self, previous_signatures: list[dict], new_grades: list[dict]
    ) -> None:
        # Reconstruct dummy "old" objects from signatures so diff_grades can
        # compare uniformly. Signatures are already minimal.
        old_for_diff: list[dict] = [
            {
                "id": s.get("id"),
                "value": s.get("value"),
                "given_at": s.get("given_at"),
                "subject": {
                    "id": s.get("subject_id"),
                    "name": s.get("subject_name"),
                },
                "collection": {"name": s.get("collection")},
                "teacher": {"name": s.get("teacher")},
            }
            for s in previous_signatures
        ]
        delta = diff_grades(old_for_diff, new_grades)
        if delta.is_empty():
            return

        base = {
            "entry_id": self.entry.entry_id,
            "student_id": self._student_id,
            "student": self._student_label,
        }
        for g in delta.added:
            self.hass.bus.async_fire(EVENT_GRADE_ADDED, {**base, **g})
        for g in delta.removed:
            self.hass.bus.async_fire(EVENT_GRADE_REMOVED, {**base, **g})
        for ch in delta.changed:
            self.hass.bus.async_fire(
                EVENT_GRADE_CHANGED,
                {**base, "old": ch["old"], "new": ch["new"]},
            )
        self.hass.bus.async_fire(
            EVENT_GRADES_UPDATED,
            {
                **base,
                "added": len(delta.added),
                "changed": len(delta.changed),
                "removed": len(delta.removed),
            },
        )
        _LOGGER.info(
            "%s: fired change events (+%d ~%d -%d)",
            self._student_label,
            len(delta.added),
            len(delta.changed),
            len(delta.removed),
        )
