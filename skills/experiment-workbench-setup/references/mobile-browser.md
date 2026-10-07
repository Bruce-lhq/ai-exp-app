# GPU-hosted iPhone setup

Use this mode for phone access independent of the user's computer. The short iSH installation and forwarding commands live in the repository [README](../../../README.md#iphone-主屏幕-web-app); GPU packaging, configuration and supervisor details live in [docs/mobile-web.md](../../../docs/mobile-web.md). Use the matching source checkout, not an assumption about a particular Release version.

## Discover and reuse

Establish what already works: phone network/SSH access, iSH installation, GPU web backend and port, existing agent/Python/state directory, and registered projects or runs. Inspect available configuration before asking; accept existing user-confirmed phone tests rather than repeating them. Credentials stay in interactive SSH authentication or the user's key store, never chat, scripts or tracked configuration.

The user establishes their required network access. Do not prescribe a vendor-specific VPN replacement or publish private network details. A working computer SSH connection does not prove that phone SSH works independently.

## 1. Agent prepares the GPU backend

Use authorized terminal access for these steps. If asked to do local work only, prepare the frontend/source bundle and local checks without SSH; report GPU deployment pending.

1. Inspect an existing service and the owner of the selected port before deploying. Reuse a healthy workbench instead of reinstalling it. Never terminate an unknown listener.
2. Reuse the exact existing agent path, Python, state and queue. Preserve its read-only marker and current deployment. Do not create a second scheduler or initialize fresh state for phone access. If no agent exists, follow the normal first-time setup and create one dedicated deployment.
3. Build/upload the source web bundle as needed. Verify GPU OS and CPU architecture; provide a separate Python 3.12+ web environment using the README installation method, without requiring uv. The standard-library agent and training environment may remain older. Do not copy a Mac virtualenv, upgrade training Python or assume an Ubuntu 24.04 desktop binary works on Ubuntu 20.04. For an offline host, prepare matching runtime and dependency wheels.
4. Configure a dedicated GPU workspace with `connection_mode=local`, absolute agent/Python/state paths and a matching host identifier. The backend calls the agent locally, without SSH to itself. Preserve existing workspace data. Register only missing projects or explicitly requested runs.
5. Bind the backend to `127.0.0.1`, normally port 8765. Select a supervisor based on the actual host; use systemd only when available. Verify health and detached survival, and test restart only for the workbench service within authorized scope. Do not restart training or replace its supervisor.
6. Check existing experiments, queue, logs, imported history, curves and table through the backend's loopback API. The skill API helper may run on the GPU or through a computer-side loopback tunnel on an available port; it must not be changed to accept a public remote API address.

GPU-hosted configuration and caches belong to the GPU. A phone's “local directory” browser refers to GPU files, not iPhone storage. Desktop metadata/cache remains separate; both can operate the same agent queue. The phone cannot use the GPU web UI offline.

## 2. Hand off iPhone steps

Generate a short command block from README with the user's confirmed host, port, username and any required SSH jump-host options. Explain which commands run in iSH, not on the GPU or computer. Reuse an existing phone SSH alias where suitable. Do not require Python, Node or uv on the phone.

Ask the user to install iSH if missing, install its OpenSSH client, confirm the host fingerprint, authenticate interactively, and start local forwarding from phone `127.0.0.1:8765` to GPU `127.0.0.1:8765`. If the port differs, update both the command and phone URL consistently. Do not put a password in the command or require a key when password authentication already works.

Have the user check the phone health URL, open the entry in Safari once, and add AI Experiment to the home screen as a Web App. Point to README's optional iSH background instructions when needed; explain its permission requirement. Do not promise indefinite background survival, system notifications or operation after iOS terminates iSH. An already working tunnel should not be started again.

If no phone-control tools are available, the Agent supplies commands and requests only the result needed for the next checkpoint. Do not claim remote desktop tools can operate an iPhone, or report real-device success from viewport tests.

## 3. Verify and diagnose jointly

Track these checkpoints independently, using existing evidence where available:

- GPU loopback health, correct existing agent/queue, and supervised web service.
- Phone health through its own SSH tunnel, independent of the computer.
- Home-screen launch, navigation, history/curves/table, touch interactions and file saving.
- Reconnection and sustained use after switching from iSH to the Web App; computer-off access if independence has not already been demonstrated.

For failures, inspect in order: GPU service → phone forwarding/network → page/assets/API. Use health responses and the actual service logs to locate the failing layer. Do not redeploy a healthy backend to fix a broken phone tunnel, repeat unchanged retries, or request all acceptance checks again after a narrow failure.

Read-only checks come first. Start/pause/stop/queue/strict-resume testing requires an authorized isolated tiny run and real project resume validation. Never pause, adopt or delete an existing formal run as a setup test.

Report local/WebKit tests, GPU observations and user-confirmed real-iPhone results separately. Save non-secret setup facts and completed checkpoints in the private setup report so another Agent can continue. If phone access remains unverified, report that remaining step rather than declaring end-to-end completion.
