# Configure, register and verify the workspace

Use the repository root for repository scripts, and the skill directory for its `scripts/api.py`, `probe.py`, `check_profile.py` helpers. Do not confuse the training project's root with the workbench source root.

## Local service and settings

Launch the installed desktop app on the actual OS, or use `ai-experiment service start`, or follow the README's localhost installation/start commands. Check `http://127.0.0.1:8765/api/health` without triggering any cloud operation. If the user selected another port, use that port in every helper call.

Read settings first:

```bash
python3 scripts/api.py --path /api/settings/local
```

Write only the missing/revised fields, preserving their existing workspace. Example request JSON, with actual user-owned absolute paths substituted:

```json
{
  "ssh_alias": "my-training-gpu",
  "remote_root": "/your_exp/workbench",
  "remote_agent": "/your_exp/workbench/agent.pyz",
  "remote_python": "/your_exp/venvs/train/bin/python",
  "remote_runs_root": "/your_exp/runs",
  "remote_projects_root": "/your_exp/projects/",
  "remote_import_root": "/your_exp/runs/",
  "local_import_root": "~/gpu_downloads/"
}
```

`remote_data_root` is optional; fill it only if applicable. A program's data path belongs in its actual parameter/profile. Choose a dedicated runs directory, never `/`. `remote_python` is the Python interpreter for Python launchers, validators and inventory hooks; for R/Julia/compiled trainers put their actual executable in the profile command instead. the installer uses the configured remote Python for its standard-library agent. Existing GPU setups may already have distinct environments; retain them.

`remote_gpu_probe` optionally points to a user-owned absolute Python script for truthful nondefault device/allocation inventory. Its exact JSON contract and visibility mapping are in [cloud-environments.md](cloud-environments.md). Leaving it empty uses the default NVIDIA query; missing NVIDIA tooling is a prompt to inspect the actual environment, not a reason to install unrelated drivers.

```bash
python3 scripts/api.py --method PUT --path /api/settings/local --json-file /path/to/settings-request.json
```

This writes the app's runtime `config.local.json`. Ask `ai-experiment config show --json` for the actual path. New defaults are macOS `~/Library/Application Support/AI Experiment`, Windows `%LOCALAPPDATA%/AI Experiment`, Linux `$XDG_DATA_HOME/ai-exp-app` (or `~/.local/share/ai-exp-app`). Existing source workspaces and environment overrides may change it. Read the actual startup settings before using an installer; do not edit a guessed second file. Credentials and private keys do not belong in this JSON.

## Agent deployment

Use the same workspace settings the service just saved. The installed/portable CLI includes the agent:

```bash
ai-experiment install-agent --read-only
ai-experiment install-agent
```

Both commands connect and deploy the agent. `--read-only` installs it in read-only mode for inspection; rerun without it to enable training/control operations. For source installations, use `.venv/bin/ai-experiment` on macOS/Linux, `.venv/Scripts/ai-experiment.exe` on Windows. If `AI_EXP_DATA_DIR` or `AI_EXP_CONFIG_FILE` selected a workspace, retain those values for deployment. Do not make a second guessed configuration file.

This deploys a zipapp and remote configuration atomically into the dedicated workbench directory. It does not install training dependencies or copy datasets. Do not replace a shared existing agent blindly; inspect which workspace uses it. Separate workspaces should use separate remote roots. If installation fails, show the specific SSH/Python/path error and preserve existing training state.

## Project registration and schema

Retrieve `/api/projects` and reuse an entry with the same SSH alias and remote code directory. Create one only if absent, or update its integration deliberately. The POST body is:

```json
{
  "name": "Image experiment",
  "ssh_alias": "my-training-gpu",
  "remote_path": "/your_exp/projects/image-example",
  "config": {"python": "/your_exp/venvs/train/bin/python"}
}
```

`config.integration` can carry the validated profile instead of a project-root file; normally use `workbench.project.json` so the project documents its integration. `config.runs_root` optionally overrides the workspace runs directory. Do not copy absolute machine paths into tracked profile defaults when a runtime setting or parameter suffices.

```bash
python3 scripts/api.py --method POST --path /api/projects --json-file /path/to/project-request.json
```

Take the returned `id` and inspect/schema-check it:

```bash
python3 scripts/api.py --method POST --path /api/projects/PROJECT_ID/inspect --json-file /path/to/empty-object.json
python3 scripts/api.py --method POST --path /api/projects/PROJECT_ID/schema --json-file /path/to/schema-request.json
python3 scripts/api.py --path /api/projects/PROJECT_ID/editor-initial
```

`empty-object.json` contains `{}`. `schema-request.json` can be `{"code":{"kind":"working_tree"},"refresh":true}`. A pinned Git branch/ref must contain the profile or receive its explicit override. Review returned fields, defaults and warnings against the source; fix the integration rather than suppressing warnings indiscriminately. Do not call any run-submit endpoint until a GPU test is authorized.

## Import and inspect existing experiments

Use the history UI, or POST `/api/history/import` with one of these documents:

```json
{"source":{"kind":"remote","ssh_alias":"my-training-gpu","path":"/your_exp/runs/example-run"},"name":"Example run"}
```

```json
{"source":{"kind":"local","path":"/path/to/normalized-run"},"name":"Example run"}
```

Import only the chosen run, not every folder automatically. Missing args/metrics/logs can be surfaced as warnings; preserve these facts. Running experiments can be imported without pausing them. View a known numeric sample in the curve and table, using `step` when token counts do not exist. A renamed run should use that display name.

The analysis page reads cached files; to test offline behavior, close the SSH connection or disconnect an isolated test environment without changing production credentials/firewall settings. Do not require a new cloud call for cached plots. Update files from history management's refresh action, then confirm an actually changed sample appears. Removing a history entry is distinct from permanent deletion; no setup step requires deleting original files.

## Outcome record

Record the actual config path, SSH alias, code/profile/run directories, selected Python, profile validation result, schema result, imported run, metrics discovered, resume evidence and unresolved checks. Keep this in ignored local workspace storage. Report only checks actually performed. For a user without prior experiments, a configured schema is a legitimate endpoint until an explicitly authorized tiny training run supplies data; do not fabricate an experiment or claim that training has passed.
