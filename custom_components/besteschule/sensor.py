"""Sensor platform.

Per ConfigEntry we create:

  * grades        — count, with `markdown` + `grades` + `average` attributes
  * average       — overall numeric average (with state_class for graphs)
  * finalgrades   — count, with `markdown` + `finalgrades` attributes
  * journal       — count, with `markdown` + `days` attributes
  * last_update   — ISO timestamp

The big payloads (markdown table, raw lists) live in entity attributes
so the sensor `state` itself stays a small scalar that HA is happy to
log and graph. Markdown card pulls them out via
`{{ state_attr('sensor.besteschule_<child>_grades', 'markdown') }}`.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DATA_AVERAGE,
    DATA_FETCHED_AT,
    DATA_FINALGRADES,
    DATA_GRADES,
    DATA_JOURNAL,
    DATA_STUDENT_LABEL,
    DOMAIN,
)
from .coordinator import BesteSchuleCoordinator
from .diff import grade_signature
from .formatter import (
    finalgrades_to_markdown,
    grades_to_markdown,
    journal_to_markdown,
)


@dataclass(frozen=True, kw_only=True)
class BesteSchuleSensorDescription(SensorEntityDescription):
    """One row in the sensor list. `value_fn` reads the coordinator data."""

    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _grades_state(data: dict) -> int:
    return len(data.get(DATA_GRADES) or [])


def _grades_attrs(data: dict) -> dict:
    grades = data.get(DATA_GRADES) or []
    fetched_at: datetime = data[DATA_FETCHED_AT]
    avg = data.get(DATA_AVERAGE)
    return {
        "markdown": grades_to_markdown(
            grades,
            student_label=data[DATA_STUDENT_LABEL],
            fetched_at=fetched_at.astimezone(),
        ),
        "grades": [grade_signature(g) for g in grades],
        "average": round(avg, 2) if avg is not None else None,
        "updated_at": fetched_at.isoformat(),
    }


def _average_state(data: dict) -> float | None:
    avg = data.get(DATA_AVERAGE)
    return None if avg is None else round(avg, 2)


def _finalgrades_state(data: dict) -> int:
    return len(data.get(DATA_FINALGRADES) or [])


def _finalgrades_attrs(data: dict) -> dict:
    finals = data.get(DATA_FINALGRADES) or []
    fetched_at: datetime = data[DATA_FETCHED_AT]
    return {
        "markdown": finalgrades_to_markdown(
            finals,
            student_label=data[DATA_STUDENT_LABEL],
            fetched_at=fetched_at.astimezone(),
        ),
        "finalgrades": [
            {
                "subject": (f.get("subject") or {}).get("name"),
                "interval": (f.get("interval") or {}).get("name"),
                "value": f.get("value"),
                "value_calc": f.get("value_calc"),
            }
            for f in finals
        ],
        "updated_at": fetched_at.isoformat(),
    }


def _journal_state(data: dict) -> int:
    days = data.get(DATA_JOURNAL) or []
    return sum(
        len(d.get("lessons") or []) + len(d.get("notes") or []) for d in days
    )


def _journal_attrs(data: dict) -> dict:
    days = data.get(DATA_JOURNAL) or []
    fetched_at: datetime = data[DATA_FETCHED_AT]
    return {
        "markdown": journal_to_markdown(
            days,
            student_label=data[DATA_STUDENT_LABEL],
            fetched_at=fetched_at.astimezone(),
        ),
        "days": len(days),
        "updated_at": fetched_at.isoformat(),
    }


SENSORS: tuple[BesteSchuleSensorDescription, ...] = (
    BesteSchuleSensorDescription(
        key="grades",
        translation_key="grades",
        name="Noten",
        icon="mdi:school",
        native_unit_of_measurement="Noten",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_grades_state,
        attrs_fn=_grades_attrs,
    ),
    BesteSchuleSensorDescription(
        key="average",
        translation_key="average",
        name="Notendurchschnitt",
        icon="mdi:calculator-variant",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_average_state,
    ),
    BesteSchuleSensorDescription(
        key="finalgrades",
        translation_key="finalgrades",
        name="Endnoten",
        icon="mdi:certificate",
        native_unit_of_measurement="Endnoten",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_finalgrades_state,
        attrs_fn=_finalgrades_attrs,
    ),
    BesteSchuleSensorDescription(
        key="journal",
        translation_key="journal",
        name="Klassenbuch",
        icon="mdi:notebook",
        native_unit_of_measurement="Einträge",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_journal_state,
        attrs_fn=_journal_attrs,
    ),
    BesteSchuleSensorDescription(
        key="last_update",
        translation_key="last_update",
        name="Letzte Aktualisierung",
        icon="mdi:clock-check",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.get(DATA_FETCHED_AT),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BesteSchuleCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        BesteSchuleSensor(coordinator, entry, desc) for desc in SENSORS
    )


class BesteSchuleSensor(
    CoordinatorEntity[BesteSchuleCoordinator], SensorEntity
):
    """One sensor row, driven by the coordinator."""

    entity_description: BesteSchuleSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BesteSchuleCoordinator,
        entry: ConfigEntry,
        description: BesteSchuleSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"beste.schule – {coordinator.student_label}",
            manufacturer="beste.schule",
            model="API",
            configuration_url="https://beste.schule",
        )

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if (
            self.coordinator.data is None
            or self.entity_description.attrs_fn is None
        ):
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
