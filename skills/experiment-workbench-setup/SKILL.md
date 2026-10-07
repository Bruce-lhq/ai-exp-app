---
name: experiment-workbench-setup
description: Set up AI Experiment for desktop, CLI or iPhone access to a cloud GPU, from first SSH connection through existing projects and experiments. Configure the project or GPU-hosted mobile backend and verify access without starting training by default.
---

# Set up AI Experiment Workbench

Produce the requested working desktop/CLI or iPhone connection, a usable project when needed, and an imported experiment or a clearly identified next validation step. Reuse already configured projects when adding phone access. Use the user's language. Ask for missing facts; do not ask again for facts already established or available through safe inspection.

This skill ships in the workbench source repository. Its helpers require Python 3.12 locally and use the standard library. They do not require an Agent-specific connector. Paths below are relative to the skill directory unless stated otherwise. Identify the local operating system, architecture, installed app/CLI and active workspace first. Prefer the matching desktop installer or portable CLI from GitHub Releases; do not build a Windows/Linux binary on macOS or assume a POSIX virtualenv path on Windows. CLI packages include the runtime and remote agent. If a helper needs source and only the installed app/CLI is present, obtain the matching source release first (GitHub Release Source code ZIP works without configuring GitHub SSH; keep it in a dedicated local folder); installation and build commands live in the repository README.

## 1. Discover the current stage

Determine whether the user wants desktop/CLI, iPhone, or both; infer this from their request before asking. Read the workbench README and list existing SSH Host aliases, the current workspace settings, and any code or experiment paths the user supplied. Read only relevant SSH configuration; do not display private keys, passwords, tokens, or the full environment.

For iPhone access, read [references/mobile-browser.md](references/mobile-browser.md). Follow its GPU preparation → phone handoff → joint verification phases. Place the full web backend on the GPU and reuse its existing agent state; a desktop-local service or terminal-only agent is insufficient. The Agent performs authorized GPU setup through available terminal tools, then supplies connection-specific iSH commands for the user to run on the phone. Do not claim to have operated or verified an inaccessible phone. Respect an instruction to finish local work first: prepare and test locally without connecting to SSH or deploying until that restriction is lifted.

Ask the smallest useful question at the first missing milestone:

| Missing information | Ask for |
| --- | --- |
| Cloud GPU status unknown | Whether a GPU host has already been provisioned, and its provider or access method. If none exists, establish the intended environment before attempting SSH. |
| No usable SSH alias | Cloud provider connection address, username and port; whether its key is already installed locally. Passwords belong in an interactive SSH prompt, never chat. |
| Phone setup unknown (iPhone mode only) | Whether iSH is installed, phone SSH/network access already works, and a GPU-hosted workbench exists. Reuse supplied acceptance evidence; never ask for passwords or private keys. |
| Code location unknown | Local directory or existing remote absolute directory. |
| Training entrypoint unclear | The command they currently use, or permission to inspect the entrypoint and project instructions. |
| Required input/data unknown | Its existing location or the provider's documented preparation process. |
| Existing experiments unknown | Whether any runs already exist; if so, their directory and whether the user wants one imported. Do not assume a newcomer has a run to import. |
| Potential paid/long-running preparation | Whether to perform that specific transfer, installation, or training test now. |

Do not ask a newcomer about metrics and checkpoint internals before establishing SSH and locating their code. Do not send an experienced user through key setup or upload code already on the GPU.

- For containers, gateways, non-NVIDIA devices or schedulers, read [references/cloud-environments.md](references/cloud-environments.md).
- For missing SSH or local-only code, read [references/new-cloud.md](references/new-cloud.md).
- For any training project, read [references/project-profile.md](references/project-profile.md). For nested repositories, structured configs or noncanonical outputs, follow [references/complex-projects.md](references/complex-projects.md). For provider gateways, container/scheduler execution, GPU vendors or storage lifetime, follow [references/cloud-environments.md](references/cloud-environments.md).
- For workspace settings, registration, import and verification, read [references/workspace.md](references/workspace.md).

## 2. Establish and verify access

When operating from a computer with an existing alias, run `scripts/probe.py ssh --alias ALIAS` first. If the Agent is already running on the target GPU, inspect its interpreter, devices and paths locally instead; do not require SSH back into the same host. This checks Python and GPU inventory in one read-only connection. It requires a previously verified host key and noninteractive authentication. Transport success is not full readiness: verify agent Python 3.8+, Linux /proc, project readability, and the actual device/allocation query. Non-Python training commands still need a Python interpreter for the agent and optional hooks. If it fails, distinguish host verification, authentication, DNS/network and missing Python; follow the matching recovery in `new-cloud.md`. Do not repeatedly retry unchanged failures.

For a local code directory, run `scripts/probe.py local PATH`. It discovers files and literal argparse defaults without importing or executing project code. For a deeper monorepo path, pass `--entrypoint packages/task/bin/fit.py`; its default scan is intentionally shallow, so an empty result is not evidence that no trainer exists. Review the actual source around the chosen entrypoint; static discovery is a hint, not proof of compatibility. For remote-only code, read relevant files over SSH or copy only the selected source files into an isolated local inspection directory. Do not import unknown project modules for discovery.

## 3. Describe the training project

Create `workbench.project.json` in the project root using the inspected command and explicit typed parameter definitions. Prefer this declarative path over parser discovery. Check argument spelling, output handling, required values, booleans, choices and GPU launch behavior against the project's existing command. The launcher uses an argv array, never a shell command string. When the native config/outputs/lifecycle differ, create the smallest project-owned wrapper described in `complex-projects.md`, preserving the original entrypoint and artifacts. Do not claim native support until that adaptation passes its checkpoints.

Run `scripts/check_profile.py PATH/workbench.project.json --repo /path/to/ai-exp-app`. It uses the same validator as the remote agent and validates explicit parameter fields without executing project code. The checkout can also be discovered from the current directory or `AI_EXP_REPO`; an installed copy of this skill still needs the matching workbench source. A successful profile check does not prove the training command or dependencies work.

Inspect the project's existing checkpoint save and restore code, then determine whether it supports strict resume. An absent workbench profile is not evidence that resume is unsupported. Reuse real project validation functions or write a project-owned verifier for its actual checkpoint format, following `project-profile.md`. Distinguish verified support, more evidence needed, and a demonstrated missing state. Do not infer complete state from a weights file or write a fake validator returning unconditional `strict: true`.

## 4. Configure and register

For desktop/CLI, follow `workspace.md` to write settings through the local API, deploy the remote agent to a dedicated directory, add the project, retrieve its schema, and import a representative run. For iPhone, use `mobile-browser.md` to prepare the GPU-hosted workspace and register only projects or runs that are not already configured; do not overwrite an existing workspace to add phone access. Use `scripts/api.py` for reproducible local API calls; it handles cookies and same-origin checks. It refuses remote API hosts. In GPU-hosted mode, run it against loopback on the GPU with a suitable interpreter, or use a verified computer-side SSH tunnel to a distinct local port; never relax that restriction or expose the API publicly.

Keep machine details only in ignored runtime configuration and a private setup report. Do not hardcode them into tracked defaults or public documentation. Do not rewrite existing experiment artifacts to make them fit. If conversion is needed, create a separate normalized copy using `scripts/normalize_metrics.py` and preserve the source.

## 5. Verify the outcome

Pass each applicable checkpoint before reporting it complete:

1. When using computer-side SSH, repeat `scripts/probe.py ssh --alias ALIAS --project REMOTE_CODE_DIR --python TRAINING_PYTHON` after locating the code. On the GPU itself, verify the same environment and readable project directory locally.
2. The backend on the intended host reports healthy; workspace settings show configured. In iPhone mode, pass the GPU and phone checkpoints in `mobile-browser.md`.
3. Project inspection succeeds; schema defaults and argument flags match the source.
4. An imported run shows the expected numeric samples and metric names. Missing metrics warn and remain missing, never zero-filled.
5. Desktop curves and tables render from cache after closing the SSH connection. In iPhone mode, cached analysis must not require additional SSH from the GPU backend, but the phone still needs its tunnel to reach that backend. Refresh happens in history management.
6. Before seeking authorization for a training smoke test, explain its tiny configuration, GPU count, expected duration or uncertainty, and dedicated output location. Reuse existing authorization when it covers this test. Once authorized, confirm queued → running → terminal, artifacts and caching. Never pause, adopt or delete their existing runs as a setup test.

When a check fails, pause dependent steps, inspect the evidence, fix issues within the authorized setup scope, and rerun the failed check before proceeding. Do not repeat unchanged failures or skip a check and declare success. If progress requires missing user information, authorization, or an external change, explain the specific blocker and ask only for what is needed; continue useful independent work. Never claim a GPU test or strict-resume test was completed based on a profile validator alone.

Finish with the selected access mode, SSH alias, code directory, profile and workspace locations, imported run name, passed checks, and any remaining limitation. For iPhone, include the phone entry URL, GPU service management method and completed user handoff; distinguish Agent-observed checks from user-confirmed phone acceptance. Offer a tiny training validation only if it has not already been authorized. Store these non-secret facts in an ignored `.local/setup-report.json` if working from a source checkout so a later Agent can continue without repeating questions.
