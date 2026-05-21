from pathlib import Path

from reanalyze.reanalyze import PERerun


def _make_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "label=old-label",
                "accounting=ligo.prod.o4.cbc.pe.bilby",
                "accounting-user=old-user",
                "outdir=../../../../pe.o4/GWTC5-HLV/project/working/S240001a/old",
                "webdir=old-webdir",
                "request-memory=4",
                "request-disk=4",
                "analysis-executable=/old/bin/bilby_pipe_analysis",
                "submit=False",
                "sampler-kwargs={'nlive': 100}",
                "a_1 = Uniform(name='a_1', minimum=0, maximum=0.99)",
                "a_2 = Uniform(name='a_2', minimum=0, maximum=0.99)",
                "",
            ]
        )
    )


def test_source_dir_is_read_only_input_and_project_dir_receives_outputs(tmp_path, monkeypatch):
    source_ini = tmp_path / "source" / "S240001a" / "bilby-IMRPhenomXPHM.ini"
    _make_config(source_ini)
    source_text_before = source_ini.read_text()
    project_dir = tmp_path / "project"
    monkeypatch.setattr("shutil.which", lambda executable: "/env/bin/bilby_pipe_analysis")

    rerun = PERerun(
        source_dir=tmp_path / "source",
        project_dir=project_dir,
        apx="IMRPhenomXPHM",
        accounting="ligo.dev.o4.cbc.pe.bilby",
        accounting_user="vaishak.prasad",
    )
    rerun.prepare_configs()
    rerun.reconfigure()

    copied_ini = project_dir / "working" / "S240001a" / source_ini.name
    text = copied_ini.read_text()
    assert source_ini.read_text() == source_text_before
    assert f"outdir={project_dir / 'working' / 'S240001a' / 'pe'}" in text
    assert f"webdir={project_dir / 'webdir'}" in text
    assert "accounting=ligo.dev.o4.cbc.pe.bilby" in text
    assert "accounting-user=vaishak.prasad" in text
    assert "label=S240001a_p2" in text
    assert "submit=condor" in text
    assert "analysis-executable=/env/bin/bilby_pipe_analysis" in text


def test_reconfigure_runs_on_resumed_project_even_when_copy_is_persistent(tmp_path, monkeypatch):
    source_ini = tmp_path / "source" / "S240001a" / "bilby-IMRPhenomXPHM.ini"
    _make_config(source_ini)
    project_dir = tmp_path / "project"
    copied_ini = project_dir / "working" / "S240001a" / source_ini.name
    copied_ini.parent.mkdir(parents=True)
    copied_ini.write_text("label=stale\noutdir=/read-only/source/tree\n")
    (project_dir / "submitted_jobs.txt").write_text("S239999a\n")
    monkeypatch.setattr("shutil.which", lambda executable: "/env/bin/bilby_pipe_analysis")

    rerun = PERerun(
        source_dir=tmp_path / "source",
        project_dir=project_dir,
        apx="IMRPhenomXPHM",
        accounting_user="vaishak.prasad",
    )
    rerun.source_dict = {"S240001a": str(source_ini)}
    _copied, rerun.config_paths = rerun.copy_inis()
    rerun.reconfigure()

    text = copied_ini.read_text()
    assert "label=S240001a_p2" in text
    assert f"outdir={project_dir / 'working' / 'S240001a' / 'pe'}" in text
    assert "accounting=ligo.dev.o4.cbc.pe.bilby" in text
    assert "accounting-user=vaishak.prasad" in text
