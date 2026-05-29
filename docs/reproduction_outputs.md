# Reproduction Outputs

This note explains what gets written after running the public starters.

This repository can also keep a small number of public live-run examples under the same `outputs/` roots.

## Output Roots

- BrowserUse:
  - `outputs/browseruse/`
- Agent-E overlay:
  - `outputs/agente/`
- Website-only manual runs:
  - `outputs/manual/`

Each execution creates a timestamped run folder.

If sample outputs are already present in the repository, you can inspect them directly as concrete examples of the same structure.

## BrowserUse Output Files

Typical files:

- `summary.md`
  - human-readable task success and metric summary
- `result.json`
  - compact machine-readable task success and metric summary
- `prompt.txt`
  - the exact prompt sent to BrowserUse
- `config.json`
  - scene, mode, model, and wrapper settings
- `browseruse_history.json`
  - compact BrowserUse trace summary
- `run_detail.json`
  - main per-run record
- `admin_summary.json`
  - scenes 2 to 4 only

## Agent-E Overlay Output Files

Typical files:

- `summary.md`
  - human-readable task success and metric summary
- `result.json`
  - compact machine-readable task success and metric summary
- `prompt.txt`
  - the exact prompt prepared for the run
- `config.json`
  - scene, mode, model, and wrapper settings
- `overlay_runtime.json`
  - overlay bridge status, elapsed time, and any overlay error
- `run_detail.json`
  - main per-run record
- `admin_summary.json`
  - scenes 2 to 4 only

## Scenario-Native Logs

Scenes 2 to 4 also write native run logs under:

- `lab/`

That directory contains:

- `events.jsonl`
- `runs.jsonl`
- `*.sqlite3`

Scene-specific SQLite files:

- scene 2: `support_runs.sqlite3`
- scene 3: `travel_runs.sqlite3`
- scene 4: `health_runs.sqlite3`

## Scene 1

Scene 1 does not use the same SQLite store as scenes 2 to 4.

For scene 1, the main file to inspect is:

- `run_detail.json`

It contains:

- task success
- submission content
- step records
- accessed vault assets
- calendar snapshot access
- computed metrics

## What to Inspect First

For most runs, start with:

- `summary.md`
- `result.json`
- `run_detail.json`

Then inspect:

- `browseruse_history.json` for BrowserUse
- `overlay_runtime.json` for Agent-E overlay
- `admin_summary.json` for scenes 2 to 4

## Cleanup

The public starters automatically remove:

- temporary browser profiles
- temporary BrowserUse download directories

The persisted run folder only keeps the trace and metric artifacts.
