# Bilby input staging

Purohit can stage local files referenced by copied bilby `.ini` files before submitting a job. This is useful when the config contains paths to PSDs, calibration-envelope files, data dumps, prior files, injection files, ROQ assets, or lookup tables that are readable on one account or host but not on the submit account.

The feature is disabled by default. Enable it by creating:

```text
<project_dir>/control/staging.yaml
```

## Local/shared-filesystem mode

Use this when the submit account can see the same filesystem path after files are copied into a shared project tree.

```yaml
enabled: true
transfer_enabled: false

local_project_dir: /home/vaishak.prasad/Projects/ligo/rean5
event_subdir: working/{event}
stage_subdir: staged_inputs
rewrite_config_suffix: .staged.ini

copy_roots:
  - /home/vaishak.prasad/Projects/ligo/rean5
  - /home/vaishak.prasad/Projects/ligo/shared_inputs

preserve_roots:
  - /cvmfs
  - /archive
  - /frames
  - /hdfs

strict_missing: false
hash_files: true
```

When `submit_event` is run, Purohit writes:

```text
working/<event>/staged_inputs/<copied files>
working/<event>/<original-name>.staged.ini
working/<event>/input_manifest.json
```

and submits the staged config.

## Host-aware transfer mode

Set `transfer_enabled: auto` to make the transfer decision from the current hostname.

```yaml
enabled: true
transfer_enabled: auto
cit_hostname_contains: ligo.caltech.edu

# If hostname does not contain ligo.caltech.edu, transfer is enabled automatically.
# If hostname cannot be determined, Purohit refuses to transfer/submit and reports a warning/error.

# If this is true, transfer is also enabled from CIT hosts.
transfer_from_cit: true

target_host: gwave@citlogin5.ligo.caltech.edu
remote_project_dir: /home/gwave/Projects/ligo/rean5

event_subdir: working/{event}
stage_subdir: staged_inputs
rewrite_config_suffix: .gwave.ini

rsync_args:
  - -a
  - --partial
  - --protect-args

copy_roots:
  - /home/vaishak.prasad/Projects/ligo/rean5
  - /home/vaishak.prasad/Projects/ligo/shared_inputs

preserve_roots:
  - /cvmfs
  - /archive
  - /frames
  - /hdfs
```

The effective policy is:

```text
hostname contains ligo.caltech.edu and transfer_from_cit is false:
  stage locally only

hostname contains ligo.caltech.edu and transfer_from_cit is true:
  stage locally, rsync staged files/config/manifest to target_host

hostname does not contain ligo.caltech.edu:
  stage locally, rsync staged files/config/manifest to target_host

hostname cannot be determined:
  refuse transfer/submission and report a warning/error
```

For each event, the remote target is constructed as:

```text
<remote_project_dir>/<event_subdir>/<stage_subdir>/
```

so for `event = S240413p` the default target is:

```text
/home/gwave/Projects/ligo/rean5/working/S240413p/staged_inputs/
```

Purohit also transfers the rewritten config and manifest to:

```text
/home/gwave/Projects/ligo/rean5/working/S240413p/<original>.gwave.ini
/home/gwave/Projects/ligo/rean5/working/S240413p/input_manifest.json
```

The submitted config path is rewritten to the remote path when transfer is enabled.

## Host override for testing

For tests or unusual hosts, you can force hostname classification:

```yaml
hostname_override: citlogin5.ligo.caltech.edu
```

or

```yaml
hostname_override: laptop.example.org
```

## What gets detected

Purohit scans INI keys whose names contain one of:

```text
file, path, psd, calibration, envelope, data, dump, prior, injection, roq, basis, weights, lookup
```

Only values that look path-like and resolve to existing files are copied. Dictionary/list values are parsed when possible.

## Manifest

`input_manifest.json` records:

```json
{
  "event": "S240413p",
  "hostname": "citlogin5.ligo.caltech.edu",
  "transfer_enabled": true,
  "transfer_target": "gwave@citlogin5.ligo.caltech.edu",
  "source_config": "...complete.ini",
  "rewritten_config": "/home/gwave/.../complete.gwave.ini",
  "files": [
    {
      "section": "DEFAULT",
      "key": "psd_dict",
      "source": "/original/H1_psd.dat",
      "staged": "/home/gwave/.../staged_inputs/H1_psd.dat",
      "local_staged": ".../working/S240413p/staged_inputs/H1_psd.dat",
      "remote_staged": "/home/gwave/.../staged_inputs/H1_psd.dat",
      "size_bytes": 12345,
      "sha256": "..."
    }
  ]
}
```

The event `status.yaml` is also updated with `staged_config`, `input_manifest`, and `staged_input_count` after successful submission.

## Safety notes

This is intentionally conservative:

- staging is opt-in;
- missing files are ignored unless `strict_missing: true`;
- global roots like `/cvmfs` are preserved by default;
- automatic transfer requires a known hostname and `target_host`;
- the original config is never modified in place.
