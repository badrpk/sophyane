# Remote Docker and QEMU deployment runners

This integration adds two fixed, authenticated execution recipes to Sophyane:

- `docker-compose-deployment` runs the project's Compose stack on a dedicated Docker host, checks API health, verifies PostgreSQL state survives an API restart and a Compose down/up, then removes the job's resources.
- `qemu-fastapi-deployment` boots the project in a pinned Linux guest, installs the declared Python dependencies from an offline wheel cache inside that guest, applies its SQL migration, and checks FastAPI endpoints from the host through a loopback-only port forward.

The endpoint does not accept shell commands. The project is transferred as a deterministic bounded archive; credentials, virtual environments, VCS files, caches, and symlinks are excluded. Sophyane's existing RSI QEMU runner remains unchanged and network-isolated.

## Security and trust boundary

Use a disposable, dedicated Linux VM for each execution host. Docker builds execute project code. The Docker host must use rootless Docker on a dedicated daemon and must not contain unrelated data. The Compose recipe rejects privileged containers, host namespaces, devices, non-loopback ports, external networks or volumes, host bind mounts outside the job directory, and unbounded services. It applies CPU, memory, and PID caps, makes the service network internal, disables network access during builds, and uses `--pull never` during deployment. It requires Docker Compose v2.24 or newer for the safe port override. Keep both runner and client clocks synchronized with NTP; signed API requests have a five-minute freshness window.

The runner binds to loopback. Put it behind an HTTPS reverse proxy; do not expose its HTTP listener directly. Requests use HMAC-SHA256 over method, path, timestamp, nonce, and body digest. The runner stores nonces and job state in SQLite, rejects replay, signs responses and results, and verifies hashes before returning artifacts. Sophyane pins the expected runner ID and the CA chain. Keep the 32-byte-or-longer key in an OS-protected file readable only by the Sophyane client and runner service; do not copy it into a repository, archive, VM image, or guest.

Jobs run in unique mode-0700 workspaces. Archive upload is limited to 128 MiB and extraction to 512 MiB/10,000 files. Subprocesses have wall-time, CPU, memory, file, descriptor, PID, and output caps; QEMU gets a 2 GiB/two-vCPU guest, a disposable qcow2 overlay, and no guest egress. Cancellation terminates process groups. On runner restart, a job that was already executing becomes `INTERRUPTED` and is not replayed; a still-queued idempotent job may resume.

An operator must configure `SOPHYANE_REAL_EXECUTION=1` only on the authorized provisioned host. The default is false. A fixture runner or unconfigured environment can return signed results for integration testing, but Sophyane refuses to translate them into PASS evidence.

## Docker host

Provision a clean Linux VM with Python 3.13, Docker Engine in rootless mode, Docker Compose v2.24+, and Sophyane installed from the reviewed checkout. Install Sophyane into an isolated environment, for example `python3.13 -m venv /opt/sophyane-venv && /opt/sophyane-venv/bin/pip install /path/to/reviewed/sophyane-checkout`. Start the rootless Docker daemon as the dedicated service user and set `DOCKER_HOST` to that user's socket. At startup the runner refuses to run as root, verifies Docker Compose v2.24+, and checks that the daemon reports its rootless security option. Preload reviewed images and build dependencies into the host cache; the job intentionally cannot pull images or use network access during builds.

Create protected state and key files:

```sh
sudo install -d -m 0700 -o sophyane-runner -g sophyane-runner /etc/sophyane-runner /var/lib/sophyane-runner
sudo sh -c 'umask 077; openssl rand 32 > /etc/sophyane-runner/runner.key'
sudo chown sophyane-runner:sophyane-runner /etc/sophyane-runner/runner.key
sudo chmod 0600 /etc/sophyane-runner/runner.key
```

Create `/etc/sophyane-runner/docker.env` readable only by the service account:

```ini
SOPHYANE_RUNNER_ID=inventory-docker-prod-01
SOPHYANE_RUNNER_SECRET_FILE=/etc/sophyane-runner/runner.key
SOPHYANE_REMOTE_JOB_KIND=docker-compose-deployment
SOPHYANE_RUNNER_ROOT=/var/lib/sophyane-runner
SOPHYANE_RUNNER_LISTEN_HOST=127.0.0.1
SOPHYANE_RUNNER_PORT=8765
SOPHYANE_RUNNER_WORKERS=2
SOPHYANE_REAL_EXECUTION=1
DOCKER_HOST=unix:///run/user/UID/docker.sock
```

Replace `UID` with the dedicated user's numeric ID. Install a systemd unit such as:

```ini
[Unit]
Description=Sophyane Docker deployment runner
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=sophyane-runner
Group=sophyane-runner
WorkingDirectory=/var/lib/sophyane-runner
EnvironmentFile=/etc/sophyane-runner/docker.env
ExecStart=/opt/sophyane-venv/bin/sophyane-remote-runner
Restart=on-failure
RestartSec=3
UMask=0077
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/lib/sophyane-runner /run/user/UID
NoNewPrivileges=yes
MemoryMax=6G
CPUQuota=300%
TasksMax=1024
LimitNOFILE=4096
KillMode=mixed

[Install]
WantedBy=multi-user.target
```

Allow the service account to access only its rootless Docker socket; do not add it to the rootful `docker` group. Ensure the service user's rootless Docker daemon is enabled with user lingering and that the daemon itself is on this dedicated VM. Limit the daemon's own systemd user service too, since BuildKit work runs in the daemon's cgroup rather than the client process cgroup:

```sh
systemctl --user edit docker.service
```

Add:

```ini
[Service]
CPUQuota=300%
MemoryMax=4G
TasksMax=512
LimitNOFILE=4096
```

Then run `systemctl --user daemon-reload && systemctl --user restart docker.service`. The container limits are applied by the runner's Compose override; the daemon limits bound image builds.

Example Caddy reverse proxy on the same host (configure a real DNS name and trusted certificate):

```caddyfile
runner.example.net {
    reverse_proxy 127.0.0.1:8765
}
```

Firewall the proxy to the Sophyane client network. TLS is mandatory for non-loopback client URLs; HMAC is still required over TLS.

## QEMU host and guest image

Provision a Linux runner with the QEMU system binary and firmware for the guest architecture, `qemu-utils`, Python 3.13, and Sophyane. Use an offline, reviewed Debian/Ubuntu guest image with systemd, PostgreSQL, Python, `python3-venv`, `python3-pip`, `python3-dev`, `libpq-dev`, a compiler toolchain, `runuser`, `mount`, `mountpoint`, `pg_isready`, `psql`, and a working `/dev/null`. The guest kernel must support virtio 9P (`CONFIG_9P_FS`, `CONFIG_9P_VIRTIO`, `CONFIG_NET_9P`). The QEMU job uses TCG, user-mode networking with `restrict=on`, and loopback-only host-forwards for authenticated SSH and FastAPI.

Inside the guest image, create the unprivileged application account and local PostgreSQL role/database. For a Debian-family image:

```sh
sudo useradd --create-home --shell /bin/bash sophyane
sudo -u postgres createuser --login sophyane
sudo -u postgres createdb --owner=sophyane inventory
sudo install -d -m 0755 -o root -g root /opt/sophyane/wheels
sudo install -d -m 0755 -o root -g root /mnt/sophyane-input /mnt/sophyane-output
test -c /dev/null
mount -t 9p -o trans=virtio,version=9p2000.L,ro sophyane /mnt/sophyane-input
```

Populate `/opt/sophyane/wheels` with reviewed binary wheels for the selected Python ABI and every entry in the application's `requirements.txt`. Do this while preparing the image, using an approved package mirror and `pip download --only-binary=:all: --dest /opt/sophyane/wheels -r requirements.txt`; then seal and hash the image. The per-job guest install uses `--no-index` and fails if any dependency is absent. Do not put package credentials or API keys in the image.

Install the files from this repository into the image and enable the guest service:

```sh
sudo install -m 0755 guest/remote-fastapi-start.sh /usr/local/libexec/sophyane-remote-fastapi-start.sh
sudo install -m 0644 guest/remote-fastapi.service /etc/systemd/system/sophyane-remote-fastapi.service
sudo install -m 0644 guest/remote-fastapi-tmpfiles.conf /etc/tmpfiles.d/sophyane-remote-fastapi.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/sophyane-remote-fastapi.conf
sudo systemctl enable postgresql.service sophyane-remote-fastapi.service
sudo systemctl daemon-reload
sudo systemctl is-enabled postgresql.service sophyane-remote-fastapi.service
sudo systemctl poweroff
```

The guest service starts from the multi-user target without ordering after `cloud-final.service`. It installs the per-job SSH key first, then waits for cloud-init and PostgreSQL from its startup script; ordering the service after cloud-final would prevent SSH readiness while cloud-init is still running. Its writable systemd namespace grants `/mnt` as a parent because the startup script creates its mountpoints. Listing a mountpoint child directly in `ReadWritePaths` can fail startup with `226/NAMESPACE` when that path is absent as systemd constructs the namespace, before the key can be installed. The tmpfiles rule also pre-creates the mountpoints.

Copy the powered-off guest image to the runner host, compute `sha256sum`, and configure both values. The guest runs dependency installation as the unprivileged `sophyane` user, applies the project's migration as that database role, writes a bounded execution report to the output share, then starts the actual Uvicorn application. The runner captures the report and checks `/healthz` and the unauthenticated inventory route (which must return HTTP 401) from the host. The guest receives no runner HMAC key.

Create `/etc/sophyane-runner/qemu.env` with the same key/identity/listener values as the Docker host plus:

```ini
SOPHYANE_REMOTE_JOB_KIND=qemu-fastapi-deployment
SOPHYANE_QEMU_IMAGE=/var/lib/sophyane-runner/guest-base.qcow2
SOPHYANE_QEMU_IMAGE_SHA256=REPLACE_WITH_PINNED_SHA256
SOPHYANE_QEMU_SSH_HOST_PUBLIC_KEY=/etc/sophyane-runner/guest-ssh-host-ed25519.pub
SOPHYANE_QEMU_BINARY=qemu-system-x86_64
SOPHYANE_QEMU_HEALTH_TIMEOUT_SECONDS=900
```

`SOPHYANE_QEMU_SSH_HOST_PUBLIC_KEY` must name the Ed25519 host public key
independently extracted from and pinned to that exact guest image. The runner
fails closed when it is missing or malformed; it does not trust `ssh-keyscan`
or disable host-key checking. Each job creates a fresh client key pair, shares
only its public key with the guest through the output 9p mount, and authenticates
using that private key with password and SSH-agent authentication disabled.
The guest must report both the read-only source and writable output 9p mounts
before the runner attempts SSH.

For AArch64, set `SOPHYANE_QEMU_BINARY` to `qemu-system-aarch64` and set
`SOPHYANE_QEMU_BIOS` to the installed AArch64 UEFI firmware file. The executor
uses the `virt` machine, Cortex-A72 CPU, virtio block and network devices, and
the configured firmware. Set `SOPHYANE_QEMU_SEED_ISO` to the read-only NoCloud
seed ISO only when the selected guest image requires first-boot NoCloud
provisioning. A prepared image whose cloud-init state is already complete should
not attach the seed again. Verify the disk enumeration and labeled boot
partitions before enabling a seed for a new image; the seed appears as an
additional virtio block device. X86_64 continues to use its default machine
profile.

The QEMU health timeout defaults to 240 seconds and accepts 60–1800 seconds. Set it higher for software-emulated or first-boot guests; the guest service start limit should be at least as long.

Use the systemd unit above, replacing the environment file and ensuring the runner user can read the image and execute QEMU. The executor forwards SSH and the application port on loopback only. Guest build and runtime use no package downloads. Host egress can be firewall-denied; the guest user network is restricted and only the assigned host-forwards are exposed.

## Use the client library

This change supplies the authenticated runner service and a Python client library. Wiring that client into `CodingDoerRuntime` is a separate change and is not included here. For a local loopback-only development runner, load the secret from a protected file and use the client directly:

```python
from pathlib import Path

from sophyane.graph_runtime import DurableStore
from sophyane.remote_runner_client import RemoteRunnerClient

secret = Path.home().joinpath(".config/sophyane-runner/runner.secret").read_bytes()
client = RemoteRunnerClient(
    "http://127.0.0.1:8765", secret, "sophyane-dev-arm64",
    durable_store=DurableStore(Path.home() / ".local/state/sophyane/runner.sqlite"),
    archive_dir=Path.home() / ".local/state/sophyane/runner-archives",
    allow_insecure_loopback=True,
)
submitted = client.submit("dev-run-001", "/path/to/reviewed/project", "qemu-fastapi-deployment")
finished = client.wait(submitted["job_id"], deadline_seconds=1800)
result, artifacts = client.retrieve(submitted["job_id"])
```

The insecure HTTP exception is limited to loopback. Use HTTPS with a trusted CA for a non-loopback endpoint. Keep the secret outside the project, archive, guest image, and command-line arguments. The client verifies signatures and artifact hashes. Results from an untrusted or fixture environment do not qualify as real deployment evidence.

The QEMU recipe expects the complete fixed check set, including the guest's multi-user target, read-only source and writable output 9p mounts, pinned SSH host key, cloud-init completion, guest application health, and database migration checks. The current guest readiness contract requires cloud-init to report `done` with an empty errors list on both guest and host. A `disabled` state fails. There is no generic pass for a guest with cloud-init disabled; an image-bound pre-baked readiness contract would require a separate implementation and review.

## Focused local integration tests

From the repository root, run:

```sh
PYTHONPATH=src ./.venv/bin/python -m pytest -q \
  tests/test_remote_execution_protocol.py \
  tests/test_remote_runner_cli.py \
  tests/test_remote_runner_service.py \
  tests/test_remote_runner_executors.py \
  tests/test_remote_runner_integration.py
```

These tests start a fixture HTTP service on loopback, exercise archive handling and signed artifact retrieval, and replace QEMU process launch with fakes. They do not launch QEMU, execute Docker Compose, or establish host isolation. On Android, skip the optional `qemu-img` address-space test unless deliberately running that separate resource test.
