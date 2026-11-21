"""Inventory of Brief files in a directory.

Reads ``.yaml``, ``.yml``, and ``.json`` files with :func:`mcw.schema.load_brief`.
List fields are counts of the strings each Brief carries. This is not a score
and not a conversion rate. The inventory does not call a model or write files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcw.errors import MCWError
from mcw.models import Brief
from mcw.schema import CHANNEL_ALIASES, load_brief

_BRIEF_SUFFIXES = {".yaml", ".yml", ".json"}

_COUNT_FIELDS = (
    "selling_points",
    "must_include",
    "must_avoid",
    "forbidden_claims",
    "regulatory_notes",
    "disclaimers",
    "pain_points",
    "claims_allowed",
    "required_elements",
)


def list_briefs(
    directory: str | Path = "briefs",
    *,
    channel: str | None = None,
    brief_id: str | None = None,
) -> dict[str, Any]:
    """List Brief files that sit directly inside ``directory``.

    Hidden files, other suffixes, and subdirectories are ignored. Files that
    fail to parse or validate are recorded in ``skipped`` and do not fail the
    inventory. ``channel`` matches a canonical id, the Chinese channel label,
    or an entry in ``CHANNEL_ALIASES``. ``brief_id`` matches ``Brief.id``
    exactly. The two filters are combined. Only briefs that pass the filters
    are counted.
    """
    root = Path(directory)
    if not root.is_dir():
        raise MCWError(f"找不到 Brief 目录: {directory}")
    try:
        children = list(root.iterdir())
    except OSError as exc:
        raise MCWError(f"无法读取 Brief 目录: {directory}: {exc}") from exc

    files = sorted((path for path in children if _is_brief_file(path)), key=lambda path: path.name)
    briefs: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for path in files:
        shown = _display_path(directory, path)
        try:
            brief = load_brief(path)
        except (MCWError, OSError, UnicodeError) as exc:
            skipped.append({"path": shown, "error": _short_error(exc)})
            continue
        if not _accepts(brief, channel=channel, brief_id=brief_id):
            continue
        briefs.append(_brief_row(brief, shown))
    return {
        "directory": directory if isinstance(directory, str) else Path(directory).as_posix(),
        "briefs": briefs,
        "skipped": skipped,
        "brief_count": len(briefs),
        "channels": _channel_rows(briefs),
    }


def _is_brief_file(path: Path) -> bool:
    return path.is_file() and not path.name.startswith(".") and path.suffix.lower() in _BRIEF_SUFFIXES


def _display_path(directory: str | Path, file_path: Path) -> str:
    """Posix path under the directory argument, relative when that argument is."""
    return (Path(directory) / file_path.name).as_posix()


def _short_error(exc: BaseException) -> str:
    return " ".join(str(exc).split())


def _accepts(brief: Brief, *, channel: str | None, brief_id: str | None) -> bool:
    if brief_id is not None and brief.id != brief_id:
        return False
    if channel is None:
        return True
    text = channel.strip()
    if text == brief.channel or text == brief.channel_label:
        return True
    canonical = CHANNEL_ALIASES.get(text) or CHANNEL_ALIASES.get(text.lower())
    return bool(canonical) and canonical == brief.channel


def _brief_row(brief: Brief, path: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "path": path,
        "id": brief.id,
        "title": brief.title,
        "locale": brief.locale,
        "product_name": brief.product_name,
        "category": brief.category,
        "audience_segment": brief.audience_segment,
        "tone": brief.tone,
        "channel": brief.channel,
        "channel_label": brief.channel_label,
        "channel_format": brief.channel_format,
        "max_chars": brief.max_chars,
    }
    for name in _COUNT_FIELDS:
        row[name] = len(getattr(brief, name))
    return row


def _channel_rows(briefs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for item in briefs:
        channel = str(item["channel"])
        counts[channel] = counts.get(channel, 0) + 1
        labels[channel] = str(item["channel_label"])
    ranked = sorted(counts, key=lambda channel: (-counts[channel], channel))
    return [
        {"channel": channel, "channel_label": labels[channel], "brief_count": counts[channel]}
        for channel in ranked
    ]
