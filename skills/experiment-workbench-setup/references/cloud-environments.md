# Cloud GPU and execution environment branches

Do not assume a provider, GPU vendor, root user, port 22, persistent disk or direct public SSH. Obtain current connection instructions from the user's provider console or its official documentation. Ask only facts that inspection cannot establish.

## Connection and lifetime

| Observed situation | Next action |
| --- | --- |
| Direct SSH | Configure the supplied host/user/port/key, verify fingerprint and run the read-only probe. |
| Jump host, VPN or tunnel | Reuse provider-documented ProxyJump/ProxyCommand or the existing tunnel. Test the final Host alias that the workbench will use. |
| Container with exposed SSH | Confirm the SSH server runs in the same filesystem/device namespace as training. Record mounted persistent code/runs volumes and reboot/stop behavior. |
| Jupyter/web terminal only | Check whether the provider offers a supported SSH endpoint/gateway or authorized port exposure. Configure that first. Do not claim success by opening a browser terminal; the current workbench transport requires SSH. |
| Batch scheduler or shared cluster | Keep the allocation constraints. Select an SSH-accessible execution environment/allocation, or create a project launcher that synchronously waits for and cancels its scheduler job. Never bypass the scheduler by launching on a login node. |
| Managed service with no SSH facility | Use the provider's supported SSH-accessible compute option/gateway if the user wants this workbench. If none exists, state the exact missing transport and provide a concrete alternative; do not fabricate a connection. A new service API transport is separate integration work. |

Confirm persistent runs/cache/checkpoints before selecting paths. Provider scratch disks may disappear when stopping a rented instance. Do not create paid resources, change network rules or replace drivers without explicit authorization for that action. Routine read-only probes and workbench configuration do not require repeated permission.

## GPU discovery and allocation

Default inventory uses nvidia-smi. The `probe.py ssh` helper reports that result as an observation, not a compatibility verdict. If unavailable, inspect the actual vendor tools, device permissions, container mounts and allocation environment. Check whether the program currently sees its devices. Do not install NVIDIA tooling on another vendor's GPU.

For another GPU vendor or provider-specific allocation, write a dedicated standard-library Python inventory script based on the host's actual supported queries. Configure its absolute path as `remote_gpu_probe` in the local runtime config and redeploy the agent config. The remote agent executes it with the selected `remote_python` and expects stdout to contain a JSON array:

```json
[
  {"index": 0, "available": true, "name": "allocated device"},
  {"index": 1, "available": false, "name": "busy device"}
]
```

Indices are unique nonnegative integers, stable in the execution namespace. `available` must be based on actual permitted allocation/occupancy; unknown occupancy is not free capacity. Optional memory/utilization fields are informational. The core reserves devices used by its active tasks in addition to this inventory. A probe failure stops allocation rather than treating every GPU as free. Do not use a fixed invented list on shared hardware.

Map allocated indices to the training runtime's visibility variables in the project `environment`, using its vendor's documented conventions. For example a ROCm project may require HIP_VISIBLE_DEVICES or ROCR_VISIBLE_DEVICES with `{gpu_ids}`; determine which one its actual runtime honors, including any container remapping. The core provides CUDA_VISIBLE_DEVICES by default, which does not prove non-CUDA visibility. If provider ids differ from process-visible ids, the project adapter must translate them consistently and the inventory must report the same namespace.

`runtime.workers_parameter` is optional and means GPU process count only when explicitly declared. Ordinary data-loader workers do not control GPU count. Match the actual distributed launcher; allocated cards alone do not launch processes.

For schedulers, the inventory/launcher pair must represent permitted resources and own the job lifecycle, not advertise the entire cluster as locally free GPUs. If that cannot be verified, finish configuration of logs/history and report the exact pending execution integration. Do not start a workload under guessed admission rules.

## Final checks

Verify SSH, the agent's Python, the training executable, source/data permissions, the actual device-query result and visibility mapping. If authorized, run a tiny isolated project test on the permitted resources and inspect its own device report. Verify lifecycle, output and cache refresh. A successful inventory schema or SSH connection alone is not a passed GPU training test.
