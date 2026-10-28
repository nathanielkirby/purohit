from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from reanalyze import remote_import
from reanalyze.host_profiles import HostProfile
from reanalyze.reanalyze import PERerun
from reanalyze.source_layout import O3_CONFIG_SUBDIR, O3_EVENT_PATTERN, compile_event_pattern, discover_subdir_configs, event_name_matches


def _touch(path: Path, text: str = "label=x\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _make_o3_tree(root: Path) -> dict[str, Path]:
    """Source tree mixing valid O3 events, distractors, and broken events."""

    expected = {
        "GW190521_030229": _touch(root / "GW190521_030229" / "ProdF1" / "GW190521_030229_data0_config.ini"),
        "GW150914": _touch(root / "GW150914" / "ProdF1" / "whatever.ini"),
        "S190425z": _touch(root / "S190425z" / "ProdF1" / "config.ini"),
        "S200105": _touch(root / "S200105" / "ProdF1" / "run.ini"),
    }
    # Other prod folders and nested outputs inside valid events are ignored.
    _touch(root / "GW190521_030229" / "ProdF2" / "other.ini")
    _touch(root / "GW190521_030229" / "ProdF1" / "outdir" / "label_config_complete.ini")
    _touch(root / "S190425z" / "C01_offline" / "NRSur7dq4.ini")
    # Non-event folders are ignored even if they have the same layout.
    _touch(root / "scripts" / "ProdF1" / "config.ini")
    _touch(root / "old_GW150914" / "ProdF1" / "config.ini")
    _touch(root / "GW190521_ab" / "ProdF1" / "config.ini")
    _touch(root / "S19042" / "ProdF1" / "config.ini")
    _touch(root / "S190425zzz" / "ProdF1" / "config.ini")
    # Matching events with a broken layout are reported as skipped.
    _touch(root / "S190426c" / "ProdF1" / "a.ini")
    _touch(root / "S190426c" / "ProdF1" / "b.ini")
    (root / "GW190412" / "ProdF2").mkdir(parents=True)
    (root / "S190513bm").mkdir()  # valid two-letter name, but no ProdF1/
    return expected


@pytest.mark.parametrize(
    "name,ok",
    [
        ("GW190521_030229", True),
        ("GW150914", True),
        ("GW_", True),
        ("S190425z", True),
        ("S200105", True),
        ("GW190521_ab", False),
        ("gw150914", False),
        ("S19042", False),
        ("S1904251", False),
        ("S190513bm", True),
        ("S190425zzz", False),
        ("old_GW150914", False),
        ("scripts", False),
    ],
)
def test_o3_event_pattern(name, ok):
    assert event_name_matches(name, compile_event_pattern(O3_EVENT_PATTERN)) is ok


def test_discover_subdir_configs_selects_single_prod_ini(tmp_path):
    expected = _make_o3_tree(tmp_path)

    selected, skipped = discover_subdir_configs(tmp_path, O3_CONFIG_SUBDIR, O3_EVENT_PATTERN)

    assert selected == {event: str(path) for event, path in expected.items()}
    assert set(skipped) == {"S190426c", "GW190412", "S190513bm"}
    assert "found 2" in skipped["S190426c"]
    assert "missing ProdF1/" in skipped["GW190412"]


def test_discover_subdir_configs_honors_event_filter(tmp_path):
    expected = _make_o3_tree(tmp_path)

    selected, skipped = discover_subdir_configs(tmp_path, "ProdF1", O3_EVENT_PATTERN, events=["S190425z"])

    assert selected == {"S190425z": str(expected["S190425z"])}
    assert skipped == {}


def _run_remote_code_locally(source_dir: Path, *args: str) -> str:
    proc = subprocess.run(
        [sys.executable, "-", str(source_dir), *args],
        input=remote_import.REMOTE_DISCOVERY_CODE,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


def test_remote_discovery_matches_local_subdir_discovery(tmp_path, monkeypatch):
    _make_o3_tree(tmp_path)
    local_selected, local_skipped = discover_subdir_configs(tmp_path, "ProdF1", O3_EVENT_PATTERN)
    monkeypatch.setattr(remote_import, "run_remote_python", lambda host, code, args: _run_remote_code_locally(Path(args[0]), *args[1:]))

    discovery = remote_import.discover_remote_configs(
        HostProfile(name="cit", ssh="user@cit"),
        str(tmp_path),
        "NRSur7dq4",
        approvals={"S190425z": "no-such-token"},
        config_subdir="ProdF1",
        event_pattern=O3_EVENT_PATTERN,
        verbose=False,
    )

    assert {event: info["source_ini"] for event, info in discovery["events"].items()} == local_selected
    assert discovery["skipped"] == local_skipped


def test_remote_discovery_legacy_mode_unchanged_but_can_filter_events(tmp_path):
    _touch(tmp_path / "S240001a" / "nested" / "bilby-NRSur7dq4.ini")
    _touch(tmp_path / "scratch" / "bilby-NRSur7dq4.ini")

    legacy = json.loads(_run_remote_code_locally(tmp_path, "nrsur7dq4", "", "{}"))
    filtered = json.loads(_run_remote_code_locally(tmp_path, "nrsur7dq4", "", "{}", "", O3_EVENT_PATTERN + "|S[0-9]{6}[a-z]+"))

    assert set(legacy["events"]) == {"S240001a", "scratch"}
    assert set(filtered["events"]) == {"S240001a"}


def test_pererun_find_bilby_configs_with_config_subdir(tmp_path):
    source = tmp_path / "source"
    expected = _make_o3_tree(source)

    rerun = PERerun(
        source_dir=source,
        project_dir=tmp_path / "project",
        approvals={"S190425z": "no-such-token"},
        config_subdir="ProdF1",
        event_pattern=O3_EVENT_PATTERN,
        progress=False,
    )

    assert rerun.find_bilby_configs() == {event: str(path) for event, path in expected.items()}
    assert set(rerun.skipped_events) == {"S190426c", "GW190412", "S190513bm"}


def test_pererun_cache_is_invalidated_by_layout_change(tmp_path):
    source = tmp_path / "source"
    _make_o3_tree(source)
    _touch(source / "S190425z" / "bilby-NRSur7dq4.ini")

    legacy = PERerun(source_dir=source, project_dir=tmp_path / "project", progress=False, verbose=False)
    assert set(legacy.find_bilby_configs()) == {"S190425z"}

    o3 = PERerun(
        source_dir=source,
        project_dir=tmp_path / "project",
        config_subdir="ProdF1",
        event_pattern=O3_EVENT_PATTERN,
        progress=False,
        verbose=False,
    )
    assert o3.find_bilby_configs()["S190425z"].endswith("ProdF1/config.ini")
