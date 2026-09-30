# Adapt unusual repositories and outputs

Start with the user's working command and inspect its real execution unit: snapshot root, working directory, native config precedence, environment, device/process layout and artifact location. Different structure means adaptation is needed, not that the project is incompatible.

| Observed structure | Action | Check without training |
| --- | --- | --- |
| Monorepo / deeply nested script | Snapshot the common source/config root including shared modules; use a relative entrypoint or a wrapper changing cwd within that snapshot. | Probe with explicit --entrypoint; verify shared source/config/import paths resolve. |
| Python module | Preserve -m and package roots; editable packages pointing at the mutable checkout defeat snapshot isolation. | Inspect packaging and composed argv/cwd/import roots. |
| Compiled / R / Julia / shell program | Use the actual executable and its argv, preserving its runtime/build identity. | Inspect executable permissions, version and supplied arguments. |
| Hydra / YAML / TOML / nested config | Use native overrides if compatible, otherwise translate editor JSON scalars using the project's own config API. | Compare generated effective config with source defaults and one numeric, boolean and enum override. |
| CSV/custom JSONL | Convert actual scalar observations into a separate canonical directory. | Compare two source samples, genuine axes, units and missing fields. |
| TensorBoard | Reuse installed event readers or a minimal scalar logging callback, preserving native event files. | Read copied events with the actual parser and check scalar tags/step against source. |
| W&B / MLflow / tracking API | Prefer local/offline scalar artifacts or an authorized export using existing credentials. | Compare selected run/tag samples; do not copy all remote runs or put tokens in config. |
| Prose logs | Use actual stable metric lines; a small callback is preferable to guessed broad regexes. | Test copied full, missing, partial and malformed lines; never fabricate values. |
| No metrics | Configure command/logs, then add an authorized minimal logging adapter. | State that curves need observations rather than pretending empty data passed. |

## Small project-owned adapter

When direct launch cannot faithfully represent the native program, add a focused workbench_adapter.py beside the project manifest. Preserve the original trainer/configs. Use this profile shape:

```json
{
  "version": 1,
  "command": ["{python}", "workbench_adapter.py", "--parameters", "{parameter_file}", "--output", "{run_dir}"],
  "parameter_style": "json",
  "parameters": [{"name":"epochs","type":"integer","default":3}]
}
```

Implement these steps using the inspected project:

1. Read the submitted parameter JSON; validate the exact scalar-to-native-field map, rejecting unknown fields/collisions.
2. Load reviewed native defaults with the project's existing config APIs, merge those scalar overrides, and write a new effective config inside the per-run output. Keep original configs unchanged.
3. Preserve native interpolation/default-group semantics. Do not invent a generic YAML translator or serialize nested objects as strings. Python tomllib reads but does not write TOML; reuse the project's writer.
4. Resolve the actual data/output paths; dependencies and large datasets stay outside code snapshots. If native outputs use nested timestamp directories, preserve them and mirror the canonical files at the declared run root.
5. Compose a child argv list and the required snapshot-relative cwd. Run synchronously with shell=False, preserve stdout/stderr and signal handling, and return the child's true exit code. Child processes should remain in the managed group.
6. Emit canonical numeric JSONL via an existing callback or incremental scalar-file reader. Handle incomplete final lines, emit each complete record once, flush and stop readers when the child ends. normalize_metrics.py converts snapshots; it is not a live reader.
7. Save or mirror actual effective args, metrics and logs. Do not overwrite source artifacts or create fictitious token counts for non-token tasks.

Test translation and lifecycle with an isolated CPU fixture first: source defaults, nested overrides, paths with spaces, two independent outputs, failed child exit propagation and no original file changes. A profile validation alone is not validation of this wrapper.

## Scheduler/container boundary

Follow [cloud-environments.md](cloud-environments.md) for access, inventory and visibility. Preserve provider/site admission rules. Foreground execution inside the user's GPU allocation is simplest.

A submit command returning successfully is not successful training. If wrapping an external scheduler, record its exact job id, wait for that job's real terminal status, propagate its exit code, and cancel only that owned job on signals. Test queued/running/success/failure/cancel with a stub before live submission. Do not launch training on a login node or advertise the whole cluster as locally idle cards. Inspect the installed scheduler's help and official site instructions, for example [Slurm sbatch](https://slurm.schedmd.com/sbatch.html) and [srun](https://slurm.schedmd.com/srun.html).

Use foreground containers with persistent mounts and inspected device remapping; avoid detached -d execution. A host process-group signal may not stop a container: the wrapper must own a recorded container identity and reliably stop/wait for it. Never stop all containers/jobs. Inspect the runtime's documentation, for example [Docker run](https://docs.docker.com/reference/cli/docker/container/run/), and test cancellation with a harmless fixture.

## Acceptance

Verify snapshot imports/configs, actual effective native values, truthful allocation/visibility, faithful numeric samples and child/job lifecycle. Refresh one changed sample and confirm cache invalidation. Inspect and adapt existing strict resume separately using the save/load checklist in project-profile.md; where authorized compare uninterrupted and resumed tiny runs. If one boundary needs more evidence, finish the verified parts and report that exact pending mechanism. Do not claim untested providers/frameworks were exercised.
