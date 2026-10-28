"""Source-tree layout helpers for fixed-subdirectory config discovery.

The default discovery mode searches ``source_dir`` recursively for INIs whose
filename contains the approximant token. Some source trees (e.g. O3) instead
keep exactly one config per event in a fixed subdirectory with an arbitrary
filename::

    source_dir/<event>/ProdF1/<anything>.ini

``discover_subdir_configs`` handles that layout. The same logic is duplicated
inside ``remote_import.REMOTE_DISCOVERY_CODE`` because that code runs on the
source host, where Purohit may not be installed; keep the two in sync.
"""

from __future__ import annotations

from pathlib import Path
import re


# GW followed by digits/underscores (e.g. GW190521_030229), or S + 6 digits +
# up to two letters (e.g. S190425z, S190513bm, S200105).
O3_EVENT_PATTERN = r"GW[0-9_]+|S[0-9]{6}[A-Za-z]{0,2}"
O3_CONFIG_SUBDIR = "ProdF1"


def compile_event_pattern(pattern: str | None) -> re.Pattern[str] | None:
    """Compile an event-name regex; matching uses ``fullmatch``."""

    return re.compile(pattern) if pattern else None


def event_name_matches(event: str, pattern: re.Pattern[str] | None) -> bool:
    return pattern is None or pattern.fullmatch(event) is not None


def discover_subdir_configs(
    source_dir: Path,
    config_subdir: str,
    event_pattern: str | None = None,
    events: list[str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(selected, skipped)`` for ``source_dir/<event>/<config_subdir>/*.ini``.

    Only immediate children of ``source_dir`` whose names fully match
    ``event_pattern`` are considered. Each must contain exactly one ``.ini``
    directly inside ``config_subdir`` (not recursive); otherwise the event is
    reported in ``skipped`` with a reason instead of guessing.
    """

    pattern = compile_event_pattern(event_pattern)
    wanted = set(events or [])
    selected: dict[str, str] = {}
    skipped: dict[str, str] = {}
    for event_dir in sorted(path for path in source_dir.iterdir() if path.is_dir()):
        event = event_dir.name
        if not event_name_matches(event, pattern):
            continue
        if wanted and event not in wanted:
            continue
        subdir = event_dir / config_subdir
        if not subdir.is_dir():
            skipped[event] = f"missing {config_subdir}/ directory"
            continue
        inis = sorted(path for path in subdir.glob("*.ini") if path.is_file())
        if len(inis) != 1:
            skipped[event] = f"expected exactly one .ini in {config_subdir}/, found {len(inis)}: {[path.name for path in inis]}"
            continue
        selected[event] = str(inis[0])
    return selected, skipped
