"""Constants for the beste.schule integration."""
from __future__ import annotations

DOMAIN = "besteschule"

# Config / option keys
CONF_ACCESS_TOKEN = "access_token"
CONF_STUDENT_ID = "student_id"
CONF_STUDENT_NAME = "student_name"
CONF_INTERVAL_ID = "interval_id"
CONF_SCAN_INTERVAL_HOURS = "scan_interval_hours"
CONF_JOURNAL_LOOKBACK_DAYS = "journal_lookback_days"
CONF_CALENDAR_LOOKAHEAD_WEEKS = "calendar_lookahead_weeks"
CONF_CALENDAR_DELETE_AFTER_DAYS = "calendar_delete_after_days"

# Defaults
DEFAULT_SCAN_INTERVAL_HOURS = 24
DEFAULT_JOURNAL_LOOKBACK_DAYS = 14
DEFAULT_CALENDAR_LOOKAHEAD_WEEKS = 2
DEFAULT_CALENDAR_DELETE_AFTER_DAYS = 365
MIN_SCAN_INTERVAL_HOURS = 1
MAX_SCAN_INTERVAL_HOURS = 168  # one week

# Event names fired on hass.bus when grades change
EVENT_GRADE_ADDED = "besteschule_grade_added"
EVENT_GRADE_CHANGED = "besteschule_grade_changed"
EVENT_GRADE_REMOVED = "besteschule_grade_removed"
EVENT_GRADES_UPDATED = "besteschule_grades_updated"  # roll-up summary

# Coordinator data keys (returned by _async_update_data)
DATA_GRADES = "grades"
DATA_FINALGRADES = "finalgrades"
DATA_JOURNAL = "journal_days"
DATA_STUDENT_LABEL = "student_label"
DATA_STUDENT_ID = "student_id"
DATA_FETCHED_AT = "fetched_at"
DATA_AVERAGE = "average"
