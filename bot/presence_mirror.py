"""Mirror another Discord session's visible activities onto this session."""

from __future__ import annotations

import json
from typing import Any

# The source session_id must not be forwarded: it identifies another session,
# and Discord stamps the publishing session itself. id/created_at are kept
# verbatim so the republished copy matches what official clients send.
FORWARDED_SESSION_FIELDS = frozenset({"session_id"})

# PLAYING through HANG. Type 6 is only displayed with an active voice state.
MIRRORABLE_ACTIVITY_TYPES = frozenset({0, 1, 2, 3, 4, 5, 6})


def extract_session_list(payload: Any) -> list[dict[str, Any]]:
    """Return session objects from READY or SESSIONS_REPLACE payloads."""
    if isinstance(payload, list):
        sessions = payload
    elif isinstance(payload, dict):
        sessions = payload.get("sessions", payload.get("data", []))
        if isinstance(sessions, dict):
            sessions = sessions.get("sessions", [])
    else:
        return []

    return [session for session in sessions if isinstance(session, dict)]


def _normalize_activity(activity: Any) -> dict[str, Any] | None:
    if not isinstance(activity, dict):
        return None

    try:
        activity_type = int(activity.get("type"))
    except (TypeError, ValueError):
        return None
    if activity_type not in MIRRORABLE_ACTIVITY_TYPES:
        return None

    name = str(activity.get("name") or "").strip()
    if not name or len(name) > 128:
        return None

    outgoing = {
        key: value
        for key, value in activity.items()
        if key not in FORWARDED_SESSION_FIELDS and value is not None
    }
    outgoing["name"] = name
    outgoing["type"] = activity_type
    return outgoing


def mirrorable_session_activities(
    payload: Any, current_session_id: str
) -> list[dict[str, Any]]:
    """Collect visible activities from every session except this one."""
    mirrored: list[dict[str, Any]] = []
    seen: set[str] = set()

    for session in extract_session_list(payload):
        source_session_id = str(
            session.get("session_id") or ""
        )
        for activity in session.get("activities") or []:
            if not isinstance(activity, dict):
                continue
            source = str(activity.get("session_id") or source_session_id)
            if not source or source == current_session_id:
                continue

            normalized = _normalize_activity(activity)
            if normalized is None:
                continue
            signature = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
            if signature not in seen:
                seen.add(signature)
                mirrored.append(normalized)

    return mirrored


def activities_signature(activities: list[dict[str, Any]]) -> str:
    """Return a stable fingerprint used to suppress duplicate presence writes."""
    return json.dumps(activities, sort_keys=True, separators=(",", ":"))


def summarize_activities(activities: list[dict[str, Any]]) -> str:
    """Describe mirrored activities without logging song details or artists."""
    summary = set()
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        try:
            activity_type = int(activity.get("type"))
        except (TypeError, ValueError):
            continue
        name = str(activity.get("name") or "").strip()
        if name:
            summary.add(f"{activity_type}:{name}")
    return ",".join(sorted(summary))
