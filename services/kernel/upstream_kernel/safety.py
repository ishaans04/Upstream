"""PRD 7.5 + 14.4: no missions in high flow, flood warnings, darkness, or private land.

These are hard gates, not scores. A mission with enormous expected information gain is
still not worth sending someone to a swollen bank in the dark, so the check runs before
any candidate is ranked rather than as a penalty afterwards.
"""
from __future__ import annotations

import datetime as dt

# Conservative fixed window. A pilot deployment should replace this with real
# sunrise/sunset for the catchment's latitude and date.
DAYLIGHT_START_H, DAYLIGHT_END_H = 7, 20


def mission_allowed(*, now: dt.datetime, flow_condition: str, flood_warning: bool,
                    node_attrs: dict) -> tuple[bool, str]:
    if flood_warning:
        return False, "flood warning in force"
    if flow_condition == "storm":
        return False, "high flow: unsafe to approach the bank"
    local_hour = now.astimezone(dt.UTC).hour
    if not (DAYLIGHT_START_H <= local_hour < DAYLIGHT_END_H):
        return False, "outside daylight hours"
    if not node_attrs.get("public_access", True):
        return False, "not a public access point"
    return True, ""
