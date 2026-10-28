# Remote event import

This workflow is for cases where the source bilby configuration tree is too large to copy to a submit cluster. The expensive discovery step runs on the source host, while only selected event INIs and their referenced input files are copied to the target project.

The existing same-host workflow is unchanged. If source and target are the same cluster, keep using the existing `PERerun` and manager workflow. Remote import is an explicit separate stage.

## Host profiles

Create a host profile file, for example `control/hosts.yaml`:

```yaml
hosts:
  source:
    ssh: user@source-login.example.org
    home: /home/source_user
    hostname_contains:
      - source-login
    scheduler: condor

  target:
    ssh: submituser@target-login.example.org
    home: /home/submituser
    project_dir: /home/submituser/Projects/ligo/rean5
    scheduler: condor
```

The profile names are arbitrary. The code uses source and target host profiles and does not hard-code cluster or user names.

## Import from source host to target project

Run this from the target cluster or from a host that can access the source host:

```bash
python scripts/import_remote_events.py \
  --hosts /home/submituser/Projects/ligo/rean5/control/hosts.yaml \
  --source-host source \
  --target-host target \
  --source-dir /home/source_user/path/to/large/source \
  --target-project-dir /home/submituser/Projects/ligo/rean5 \
  --apx NRSur7dq4 \
  --event S240413p
```

Internally this does:

```text
1. run config discovery under source_dir on the source host
2. select matching event INIs
3. copy the selected INI only
4. scan the copied INI for path-valued dependencies
5. copy those dependency files only
6. preserve source HOME-relative paths under working/<event>/data/home-relative/
7. write a target submit INI
8. write input_manifest.json and status.yaml
```

## O3 source layout (`--config-subdir`, `--event-pattern`)

By default, discovery searches `source_dir` recursively for INIs whose filename contains `--apx`, and every top-level directory becomes an event. O3-style trees instead hold exactly one config per event in a fixed subdirectory, with an arbitrary filename:

```text
source_dir/
  GW190521_030229/ProdF1/<any-name>.ini   # used
  GW190521_030229/ProdF2/...              # ignored (other subfolders)
  S190425z/ProdF1/<any-name>.ini          # used
  scripts/...                             # ignored (not an event name)
```

Two options select this layout. Both work for the local (`PERerun`) and remote-import paths:

- `--config-subdir ProdF1`: use `source_dir/<event>/ProdF1/*.ini` (non-recursive) instead of the `--apx` filename match. Each event must contain exactly one INI there; events with none, several, or a missing `ProdF1/` are skipped and listed in the logs and in the summary under `skipped_events`. Approval tokens are ignored in this mode. `--apx` is still used when rewriting the target INI (e.g. the `NRSur7dq4` transfer path).
- `--event-pattern REGEX`: only top-level directories whose names **fully** match `REGEX` are treated as events. The O3 pattern is `GW[0-9_]+|S[0-9]{6}[A-Za-z]?` (GW + digits/underscores, or S + 6 digits + an optional letter). This also works without `--config-subdir`.

`scripts/init_env.sh` on the `O3` branch defaults to `CONFIG_SUBDIR=ProdF1` and the O3 `EVENT_PATTERN`. Set `CONFIG_SUBDIR=""` and/or `EVENT_PATTERN=""` before sourcing it to restore the legacy search.

```bash
python scripts/import_remote_events.py \
  --hosts control/hosts.yaml --source-host cit --target-host gwave \
  --source-dir /home/source_user/O3/working \
  --apx IMRPhenomXPHM \
  --config-subdir ProdF1 \
  --event-pattern 'GW[0-9_]+|S[0-9]{6}[A-Za-z]?'
```

## Target layout

For event `S240413p`, a target project gets:

```text
working/S240413p/
  original/
    config.source.ini
  data/
    home-relative/
      Projects/...
  config.target.ini
  input_manifest.json
  status.yaml
```

`status.yaml` records `submit_ini`. The submission manager now prefers `submit_ini` when present, so the tunnel/static manager submits the target-cluster config instead of accidentally selecting a generated or source config.

## Path policy

Dependency paths found in path-like keys are copied to event-local data paths:

```text
/source/home/Projects/shared/psds/H1.dat
  -> <target_project>/working/<event>/data/home-relative/Projects/shared/psds/H1.dat
```

Remaining source-home paths in the INI are rewritten by preserving the path suffix after `HOME`:

```text
/source/home/Projects/ligo/rean5/...
  -> /target/home/Projects/ligo/rean5/...
```

Preserved roots such as `/cvmfs`, `/archive`, `/frames`, and `/hdfs` are not copied by default.

## Submission

After import, run the tunnel/static manager on the target cluster. Submission remains local to the manager process:

```bash
python scripts/run_tunnel_manager.py \
  --project-dir /home/submituser/Projects/ligo/rean5 \
  --webdir /home/submituser/public_html/monitor \
  --host 127.0.0.1 \
  --port 8766
```

This means jobs imported to the target cluster are submitted from the target cluster, while same-cluster jobs can still use the existing workflow.
