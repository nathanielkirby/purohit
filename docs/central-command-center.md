# Central command center

The central command center aggregates multiple cluster-local Purohit managers into one control panel.

Each cluster still runs its own local manager. That manager submits and monitors jobs on its own cluster. The central manager only:

```text
1. reads each cluster's static status snapshots
2. combines the job tables into one central page
3. routes user commands to the selected cluster's command queue
```

This keeps Condor operations local to the relevant submit host while providing one browser-facing control panel.

## Cluster-local managers

Run the normal tunnel manager on each cluster. For example, on each submit host:

```bash
python scripts/run_tunnel_manager.py \
  --project-dir /path/to/project \
  --webdir /path/to/public_html/monitor \
  --host 127.0.0.1 \
  --port 8766 \
  --token-file /path/to/project/control/tunnel_token.txt
```

The local manager writes files such as:

```text
status.json
health.json
command_results.json
dag_details.json
tunnel.html
files.html
```

## Central config

Create a central config YAML, for example `control/central.yaml`:

```yaml
clusters:
  cluster_a:
    ssh: user@cluster-a-login.example.org
    project_dir: /home/user/Projects/ligo/rean5
    webdir: /home/user/public_html/monitor
    label: Cluster A

  cluster_b:
    ssh: user@cluster-b-login.example.org
    project_dir: /home/user/Projects/ligo/rean5
    webdir: /home/user/public_html/monitor
    label: Cluster B
```

If the central manager is running on the same host as a cluster, omit `ssh` for that cluster and paths are read/written locally.

The command queue defaults to:

```text
<project_dir>/control/tunnel_commands.jsonl
```

You can override it with:

```yaml
queue_path: /path/to/project/control/tunnel_commands.jsonl
```

## Run the central manager

On your laptop or on a trusted login host:

```bash
python scripts/run_central_manager.py \
  --config /path/to/control/central.yaml \
  --webdir /path/to/central-webdir \
  --host 127.0.0.1 \
  --port 8770 \
  --token-file /path/to/central_token.txt \
  --interval 30
```

Open:

```text
/path/to/central-webdir/central.html
```

or, if served over a web server, the corresponding `central.html` URL.

The browser talks to one central endpoint, by default:

```text
http://127.0.0.1:8770
```

## Do you need two SSH tunnels?

No, not for the browser-facing UI. The central manager is the only browser-facing endpoint.

The central manager itself must be able to access the clusters. It can do this by direct SSH, by SSH config aliases, or by whatever login route your environment supports. If you run the central manager on your laptop, then your laptop needs SSH access to each cluster. If one cluster is reachable only through another login host, set up your `~/.ssh/config` with `ProxyJump` and use that host alias in the central YAML.

## Command routing

When you click `Submit`, `Hold`, `Release`, `Remove`, or `Reset`, the central manager appends a JSON command to that cluster's command queue. The cluster-local tunnel manager drains the queue and performs the actual operation locally.

This preserves the safety model:

```text
central manager: aggregate and route
cluster-local manager: submit, hold, release, remove, monitor
```

## Safety notes

- The central manager refuses to bind to a non-local host without `--token-file`.
- Commands are routed to explicit cluster names.
- A failed cluster does not break the whole central page; its row shows an error while other clusters continue updating.
- The central manager does not run `bilby_pipe`, `condor_q`, or `condor_rm` itself.
