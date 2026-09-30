# Describe any training entrypoint

The project root contains `workbench.project.json`. A file in the working tree is used for working-tree selection; commit it before selecting a Git revision that must contain it. Alternatively a project can supply `config.integration` through the local API. A submitted run keeps its selected code snapshot, parameters and profile.

## Minimal explicit profile

Translate the project's real invocation into tokens. This example is for a hypothetical program, not a required file name or framework:

```json
{
  "version": 1,
  "command": ["{python}", "optimize_image.py", "--output-dir", "{run_dir}"],
  "parameters": [
    {"name": "image_width", "type": "integer", "default": 16, "flag": "--image-width"},
    {"name": "learning_rate", "type": "number", "default": 0.001, "flag": "--learning-rate"},
    {"name": "method", "type": "string", "default": "adam", "flag": "--method", "choices": ["adam", "sgd"]},
    {"name": "augment", "type": "boolean", "default": false, "flag": "--augment", "action": "store_true"}
  ],
  "environment": {}
}
```

Read the actual output argument or environment variable from source. Do not invent `--output-dir`, `--run-dir`, or a required data directory. A program without CLI parameters can declare `"parameters": []`. An executable or module invocation is also valid. A distributed project can use a command such as `[{python}, -m, torch.distributed.run, --standalone, --nproc-per-node={gpu_count}, entry.py]`, with every item represented as a JSON string; only use it when the project supports distributed launch.

The profile supports:

| Field | Meaning |
| --- | --- |
| `command` | Nonempty argv array; the executable must exist in the selected environment. No pipes, redirects, shell expansion or shell command strings. |
| `parameters` | Explicit definitions with `name`, `type`, `flag` or `flags`, and optional `default`, `choices`, `nullable`, `required`, `group`, `help`, `constraints`, `action`. Types are `integer`, `number`, `boolean`, `string`, or `number_or_choice` (arbitrary finite numbers plus listed string choices); actions are `store`, `store_true`, `store_false`. |
| `parameter_style` | `cli` by default; `json` writes the training parameter object to `{parameter_file}` instead of appending flags. |
| `environment` | String-to-string variables for this command. No credentials; use the host's existing authentication mechanisms. |
| `controlled_parameters` | Names supplied by the profile's command and excluded from the editor, preventing duplicate output/resume arguments. |
| `entrypoint`, `parser_function` | Optional isolated argparse discovery when explicit parameters are omitted. Use only a reviewed parser; prefer explicit definitions for a newcomer. |
| `runtime.workers_parameter` | Optional GPU process-count parameter name, only when the project's actual semantics match; a data-loader worker count is not a GPU count. |

Command/environment placeholders are `{python}`, `{run_dir}`, `{gpu_count}`, `{gpu_ids}`, `{project_dir}` and `{parameter_file}`. `{project_dir}` points to the selected code snapshot; dependency environments and datasets should live outside snapshots. Literal braces must be doubled. Other placeholders fail validation at launch. Do not put `{resume}` in a fresh-run command.

For JSON config programs:

```json
{
  "version": 1,
  "command": ["{python}", "entry.py", "--config", "{parameter_file}", "--results", "{run_dir}"],
  "parameter_style": "json",
  "parameters": [{"name": "epochs", "type": "integer", "default": 3}]
}
```

## Metrics and files

The canonical run directory contains `args.json`, `metrics.jsonl`, and `train.log`. Metrics may use any finite numeric metric name. Emit one JSON object per line, preferably with an explicit axis, for example:

```json
{"step": 1, "tokens_seen": 1000000, "elapsed_s": 2.5, "loss": 0.8, "accuracy": 0.73}
```

Use `tokens_seen` only for genuine token counts, never rename image/example counts into tokens. Choose `step` for those projects. Do not synthesize unsupported metrics or treat a missing metric as zero. The workbench captures command output and records submitted arguments; to show live curves the training program must emit readable numeric observations into the run directory. Minimal project-owned logging integration is preferable to parsing arbitrary prose.

For existing CSV/nested JSONL, create a separate normalized import directory. Copy relevant non-secret `args.json` and log files if available; do not alter originals. Create a field-map JSON, such as `{"step":"iteration","loss":"train.loss"}`, and run:

```bash
python3 scripts/normalize_metrics.py --input /path/to/original.jsonl \
  --output /path/to/normalized-run/metrics.jsonl --map /path/to/field-map.json
```

CSV uses its column names in the field map. Numeric strings are accepted; invalid/nonfinite values are reported and omitted. Existing output is refused unless `--overwrite` is explicit. Unit changes require an inspected conversion rather than a misleading rename. This helper converts a snapshot; it does not add live logging to the trainer.

## Inspect and integrate strict resume

Review checkpoint writing and reading, not merely the presence of `latest.pt`. Locate which functions restore:

- Model parameters and buffers.
- Optimizer state, including momentum/adaptive accumulators and optimizer-step counters.
- Scheduler state and learning-rate position.
- Random-number generators used by the project, including relevant CPU/GPU generators.
- Data iteration/sample cursor, sampler state, or another mechanism reproducing the training position.
- Code/model/data configuration and GPU/world-size compatibility requirements.

Account for the actual project: an explicit constant learning rate may have no scheduler object but still requires proof that its schedule/position is unchanged; deterministic replay can replace a stored cursor only when that behavior is demonstrated. Reuse existing strict validation routines where possible. If the save path lacks required state, report exactly what is missing. If source inspection is inconclusive, report “needs verification”, not “unsupported”. A complete existing implementation should be connected instead of disabled because its format differs from another project.

The workbench's declarative resume profile is:

```json
{
  "checkpoint": "checkpoints/latest.bin",
  "flag": "--checkpoint",
  "validator": ["{python}", "verify_resume.py", "{checkpoint}", "{request}"]
}
```

Put this object under top-level `resume`. Paths are examples. `checkpoint` is a relative file under the run directory. `flag` appends the pinned checkpoint to the base argv; alternatively `resume.command` can provide a full resume argv with `{resume}`. The validator receives a checkpoint and request JSON. Both phases include `checkpoint_path`, `phase` and `snapshot`; only the `validate` phase contains proposed `training` and `runtime`. In `preview`, recover those values from the checkpoint rather than requiring missing request fields. Read the implementation's `remote/ai_exp_remote/resume.py` before writing a verifier to keep its exact request/response contract aligned.

The verifier must return a JSON object on stdout, including `strict`, `compatible`, `verified_state` with `model`, `optimizer`, `scheduler`, `rng`, `data_position`, restored `training`, `runtime.gpu_count`, and `errors`. Include `tokens_seen` only if the project tracks tokens; a non-token project may return `step` for its genuine training position. Do not invent token counts from samples, epochs or steps. These are evidence-backed conclusions, not constants. Inspect the actual trusted checkpoint and proposed configuration; fail with useful errors when state is missing or incompatible. Keep diagnostic messages on stderr. Do not deserialize checkpoints from untrusted sources.

Where authorized, verify by a tiny uninterrupted run versus a stopped-and-resumed run using identical seeds/configuration. Compare training counters, optimizer/scheduler state and next-step results according to the project's determinism guarantees. Use dedicated outputs and available resources, leaving existing work untouched. If resources are not authorized, retain the project-specific verifier and clearly distinguish source-verified capability from a runtime test still pending.
