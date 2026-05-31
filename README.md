# purohit

Utilities for preparing, submitting, and monitoring `bilby_pipe` and `pyRing` Runs.

Purohit is designed for a shared gravitational-wave rerun project where one or
more submit hosts prepare event working directories, submit HTCondor DAGs  and publish a lightweight browser control panel.



## Installation

First, create a conda env


## Catalog re-analysis and Bilby PE jobs 

export REPO=/path/to/the/cloned/repo

1. Setup the environment.

```cd $REPO```

We suggest using conda:

```conda env create -f conda-environment.yml```

``` conda activate pur```



this will create and activate new env called `pur`


2. Install purohit

   ```pip install -e .```

3. Also, make the below script in scripts dir executable:
``` chomd +x scripts/*.sh```

4. Initialize env variables

Copy the script in ```$REPO/scripts/init_env.sh``` to a location outside $REPO, change it accordingly, and source it:

```source scripts/init_env.sh```


5. Initialize the project

   A project initialization involves copying inis from the source dir to destination project dir.

   If the source is not CIT, then this initiates rsync. 

   ``` ./scripts/init_project.sh```

6. Start the back-end (cluster-side) monitor
   ```./scripts/start_cluster_manager.sh start ```

   other possible args are ```stop, status, restart```
   
8. Start the front-end (laptop side) server:

   ```scripts/open_laptop_tunnel.sh cit (or gwave)```




## What Purohit does

Purohit supports three related workflows:

1. **Same-cluster operation**: prepare, submit, and monitor jobs on the same host
   where the input INIs already live.
2. **Remote import to a submit cluster**: discover INIs on a source host, copy
   only selected event INIs and their referenced input files to a target submit
   cluster, rewrite paths, and submit locally from the target cluster.
3. **Central command center**: aggregate multiple cluster-local Purohit managers
   into one browser-facing control panel. ( not merged)

The important safety rule is that submission and Condor operations stay local to
the relevant submit host. The central manager routes commands; it does not run
`bilby_pipe`, `condor_q`, or `condor_rm` itself.

## Repository layout

```text
reanalyze/
  reanalyze.py              legacy PERerun preparation/submission helpers
  static_monitor.py         static status/event-page publisher
  tunnel_manager.py         localhost API, command queue, file browser backend
  tunnel_webapp.py          web app entrypoint with public static pages + tokened API
  output_products.py        event-scoped product/config discovery and serving
  remote_import.py          explicit source-host -> target-cluster materialization
  central_manager.py        multi-cluster status aggregator and command router
scripts/
  run_tunnel_manager.py     recommended cluster-local manager entrypoint
  import_remote_events.py   remote source -> target project import CLI
  run_central_manager.py    central multi-cluster manager entrypoint
docs/
  remote-event-import.md
  central-command-center.md
```



## Testing and continuous integration

GitHub Actions runs the automated test suite on every pull request and push. The
workflow runs on `ubuntu-latest` with Python 3.10, 3.11, and 3.12. For each
Python version, CI checks out the repository, installs the packages listed in
`requirements-test.txt`, sets `PYTHONPATH=.`, and runs:

```bash
pytest -q
```

The tests do not require a live HTCondor installation or the full target LIGO
runtime environment. Test fixtures provide minimal stubs for optional runtime-only
imports such as `htcondor2` and `waveformtools`; tests that need Condor status
behavior monkeypatch it directly.

To run the same tests locally from the repository root:

```bash
python -m pip install -r requirements-test.txt
PYTHONPATH=. pytest -q
```

## Acknowledgements

The packaging work in this repository builds on the packaging effort proposed by
@chungyinleo in #8, while preserving the existing `reanalyze/` source layout.
