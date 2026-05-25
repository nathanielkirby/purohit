from __future__ import annotations

from pathlib import Path

import yaml

from reanalyze.host_profiles import HostProfiles
from reanalyze.remote_import import (
    event_data_path,
    home_relative_path,
    parse_ini_dependencies_text,
)
from reanalyze.static_manager import find_event_config


def test_home_relative_path_preserves_suffix_after_home():
    rel = home_relative_path("/home/source/Projects/ligo/input/H1.dat", Path("/home/source"))
    assert rel.as_posix() == "Projects/ligo/input/H1.dat"


def test_event_data_path_uses_event_local_home_relative_layout(tmp_path):
    target = event_data_path(tmp_path / "proj", "S1", "/home/source/Projects/ligo/input/H1.dat", Path("/home/source"))
    assert target == tmp_path / "proj" / "working" / "S1" / "data" / "home-relative" / "Projects" / "ligo" / "input" / "H1.dat"


def test_parse_ini_dependencies_skips_preserved_roots():
    text = """
psd_file = /home/source/psd/H1.dat
basis_file = /cvmfs/example/basis.hdf5
not_a_path = hello
"""
    deps = parse_ini_dependencies_text(text)
    assert len(deps) == 1
    assert deps[0].key == "psd_file"
    assert deps[0].source_path == "/home/source/psd/H1.dat"
    assert deps[0].kind == "psd"


def test_find_event_config_prefers_submit_ini(tmp_path):
    project = tmp_path / "project"
    event_dir = project / "working" / "S1"
    event_dir.mkdir(parents=True)
    (event_dir / "config.ini").write_text("label=source\n")
    submit_ini = event_dir / "config.target.ini"
    submit_ini.write_text("label=target\n")
    (event_dir / "status.yaml").write_text(yaml.safe_dump({"submit_ini": str(submit_ini)}))

    assert find_event_config(project, "S1") == submit_ini


def test_find_event_config_ignores_generated_configs(tmp_path):
    project = tmp_path / "project"
    event_dir = project / "working" / "S1"
    event_dir.mkdir(parents=True)
    original = event_dir / "config.ini"
    original.write_text("label=source\n")
    (event_dir / "config.target.ini").write_text("label=target\n")
    (event_dir / "config.gwave.ini").write_text("label=gwave\n")

    assert find_event_config(project, "S1") == original


def test_host_profiles_loads_arbitrary_names(tmp_path):
    path = tmp_path / "hosts.yaml"
    path.write_text(yaml.safe_dump({"hosts": {"alpha": {"ssh": "user@alpha", "home": "/home/user", "project_dir": "/home/user/project", "hostname_contains": ["alpha"]}}}))
    profiles = HostProfiles.load(path)
    assert profiles["alpha"].ssh == "user@alpha"
    assert profiles["alpha"].home == Path("/home/user")
