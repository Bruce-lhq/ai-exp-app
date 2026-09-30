# First SSH connection or local-only code

Read this only when access or code transfer is missing.

## SSH

1. Obtain the provider's connection details from the user or its visible console: host/address, username, port, optional jump host, and its prescribed authentication method. Ask for the provider name only when needed to find its official connection/setup documentation. Do not guess a root username, a port, or a public hostname.
2. Inspect existing public-key filenames and SSH aliases. Reuse a suitable key if the user wants; otherwise create a dedicated key without overwriting an existing file. Never upload or disclose its private half. Give the public half to the provider through the user's authorized console workflow. Never store a password in JSON or a shell command.
3. Add a new alias to `~/.ssh/config` after preserving the previous file. Avoid changing unrelated hosts. Substitute actual supplied values for this example:

```sshconfig
Host my-training-gpu
    HostName gpu.example.com
    User your-user
    Port 22
    IdentityFile ~/.ssh/your-training-key
    IdentitiesOnly yes
    ControlMaster auto
    ControlPersist 10m
    ControlPath ~/.ssh/ai-exp-%C
```

The provider may require `ProxyJump`, a different key type or password login; follow its instructions rather than imposing this example. Ensure `.ssh` is private and key/config files have appropriate permissions.

4. Verify the host-key fingerprint against the provider's console/documentation or another trusted source. The user's first interactive connection may need to accept that verified key and unlock a key/passphrase. Never disable host-key checks, automatically approve an unverified fingerprint, or replace a changed known-host entry without understanding why it changed.
5. Run the read-only probe:

```bash
python3 scripts/probe.py ssh --alias my-training-gpu
```

If `BatchMode` fails but interactive SSH succeeds, the app needs a usable SSH agent or provider-supported key authentication. Explain the authentication step; do not create password automation. `Connection refused` is a host/port/listening problem; `Permission denied` is authentication; a missing `python3` is a remote prerequisite. Resolve one evidenced failure at a time.

## Provider-specific access and storage

Follow the provider's current official documentation and the actual instance console; do not assume the GPU has a public port 22. For an SSH-enabled container, use its published host/port and verify where the connection lands. For a private instance, use its supported jump host, VPN, tunnel or gateway. Preserve the user's existing access mechanism rather than opening a broad inbound firewall rule.

If the user has only a notebook/web terminal and no SSH endpoint, identify the provider-supported way to enable SSH or connect through a gateway. Ask for the console step that cannot be performed with available tools. The workbench's remote transport is SSH; do not pretend a browser terminal is interchangeable. Local history still works while that access step is pending. Never install an unsanctioned public tunnel or expose the local workbench API to the internet as a workaround.

Before choosing directories, distinguish persistent attached/network storage from an ephemeral container disk. Place experiment outputs and workbench state on writable storage that survives the user's intended stop/restart/recreate workflow. Mount paths inside and outside a container may differ; record the mapping. Ask before attaching paid storage or transferring large data. After reconnecting to a recreated instance, reverify the current endpoint and mounts rather than blindly trusting stale paths.

The probe lists NVIDIA/AMD tool availability; absence of `nvidia-smi` does not prove absence of a GPU. Inspect the vendor/runtime actually present and any scheduler allocation. Never install or replace CUDA/ROCm drivers by guessing. Use the provider's compatible image and the project's existing dependencies. On non-NVIDIA or virtualized devices, follow the workbench's configured inventory hook and project-specific visibility variables once their true semantics are known; do not invent idle-device records from total advertised hardware.

## Upload code only when absent remotely

Find a user-owned remote home/work directory from the probe and choose a dedicated destination. Inspect the project's install instructions and ignore rules first. Do not transfer `.env`, private credentials, local environments, downloaded runs, or unrelated data. Preview the proposed files before uploading:

```bash
rsync -an --exclude .git --exclude .env --exclude .venv --exclude venv \
  --exclude __pycache__ --exclude node_modules --exclude .local \
  --exclude gpu_downloads /local/code/ my-training-gpu:/your_exp/projects/example/
```

After checking the file list and creating that dedicated destination, repeat with `-a` to transfer. Do not use `--delete`. Paths with spaces require argument-safe quoting. For a Git repository already accessible from the GPU, an SSH clone is also suitable; do not copy the user's private GitHub key to the server. Non-Git directories can be selected as a working tree.

Locate data separately. Reuse existing data; ask before downloading large datasets, creating resources or running paid preparation. Keep dataset credentials out of the profile and workbench settings.

## Training environment

Choose an existing project environment if available. Inspect the README, lockfiles and provider image before installing anything. Keep training dependencies separate from the standard-library remote agent. For a new environment, use `uv venv` and `uv pip` with the project's own requirements/lockfile; do not replace shared system Python, CUDA or another experiment's environment. Install `uv` following its official instructions if missing, with authorization appropriate to that environment.

Check the selected Python's version and installed-package metadata; do not launch the training entrypoint merely to discover dependencies. The remote agent requires Python 3.8+. The training executable is project-specific and may be Python, a binary, a module, or a distributed launcher. GPU inventory confirms availability, not exclusive ownership; query existing runs before proposing a smoke test.
