"""PRD 7.5 + 14.4: no missions in high flow, flood warnings, darkness, or private land.

These are hard gates, not scores. A mission with enormous expected information gain is
still not worth sending someone to a swollen bank in the dark, so the check runs before
any candidate is ranked rather than as a penalty afterwards.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

# Conservative fixed window, in the catchment's own local time. A pilot deployment should replace this with real
# sunrise/sunset for the catchment's latitude and date.
DAYLIGHT_START_H, DAYLIGHT_END_H = 7, 20


def mission_allowed(*, now: dt.datetime, flow_condition: str, flood_warning: bool,
                    node_attrs: dict, local_tz: str = "UTC") -> tuple[bool, str]:
    """`local_tz` is the catchment's IANA zone. Daylight is a local fact: judged in UTC,
    the gate would send a Delhi volunteer (UTC+5:30) to a drain bank at 01:00."""
    if flood_warning:
        return False, "flood warning in force"
    if flow_condition == "storm":
        return False, "high flow: unsafe to approach the bank"
    local_hour = now.astimezone(ZoneInfo(local_tz)).hour
    if not (DAYLIGHT_START_H <= local_hour < DAYLIGHT_END_H):
        return False, "outside daylight hours"
    if not node_attrs.get("public_access", True):
        return False, "not a public access point"
    return True, ""
