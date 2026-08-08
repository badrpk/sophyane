"""Self-hosted email-platform deployment orchestration.

This is intentionally different from configuring a hosted email provider.

Architecture:

    Sophyane / Nifdu control plane
        |
        +-- Nifdu webmail / product layer
        |
        +-- self-hosted SMTP / IMAP mail plane
        |
        +-- user-owned compute and persistent storage
        |
        +-- Namecheap DNS control only

Namecheap is never treated as the mail provider.

Stage 1 builds and validates the deployment bundle. It intentionally does
not mutate DNS or claim that the public email service is live.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
from typing import Callable


Progress = Callable[[str], None]


_DEPLOY_WORDS = (
    "live",
    "deploy",
    "deployment",
    "host",
    "hosting",
    "domain",
    "dns",
    "namecheap",
    "public",
)


_EMAIL_PLATFORM_WORDS = (
    "email service",
    "mail service",
    "email platform",
    "mail platform",
    "email server",
    "mail server",
    "webmail",
)


_CREATE_WORDS = (
    "make",
    "create",
    "build",
    "develop",
    "implement",
    "deploy",
    "launch",
    "host",
    "run",
)


def _normalise(
    value: str,
) -> str:
    return " ".join(
        str(
            value
            or ""
        ).casefold().split()
    )


def is_email_platform_request(
    request: str,
) -> bool:
    """Recognise creation or continuation of a real mail service.

    Browser-only email UI requests remain ``product_app``. Requests that
    explicitly require real mail transport, a deployable mail domain, or
    self-hosted mail infrastructure belong to ``email_platform``.
    """
    text = _normalise(
        request
    )

    has_email = any(
        token in text
        for token in _EMAIL_PLATFORM_WORDS
    )

    has_create = any(
        token in text
        for token in _CREATE_WORDS
    )

    has_continuation = any(
        token in text
        for token in (
            "i want it",
            "want it to",
            "make it able",
            "be able to",
            "add sending",
            "add receiving",
        )
    )

    has_deployment = any(
        token in text
        for token in _DEPLOY_WORDS
    )

    transport_signal = any(
        token in text
        for token in (
            "smtp",
            "imap",
            "send and receive email",
            "receive and send email",
            "send and receive real email",
            "receive and send real email",
            "real email",
            "mailbox",
            "mx record",
            "dkim",
            "dmarc",
            "spf",
        )
    )

    self_hosted_signal = any(
        token in text
        for token in (
            "my domain",
            "own domain",
            "my hardware",
            "own hardware",
            "self hosted",
            "self-hosted",
            "namecheap",
            "through namecheap api",
            "on my domain",
        )
    )

    domain = extract_domain(
        request
    )

    explicit_domain_signal = bool(
        domain
    )

    implementation_intent = (
        has_create
        or has_continuation
    )

    real_mail_intent = (
        transport_signal
        or self_hosted_signal
    )

    deployment_target = (
        has_deployment
        or self_hosted_signal
        or explicit_domain_signal
    )

    return (
        has_email
        and implementation_intent
        and real_mail_intent
        and deployment_target
    )


def extract_domain(
    request: str,
) -> str:
    """Extract a user-supplied DNS domain without interpreting it as a URL."""
    text = str(
        request
        or ""
    )

    candidates = re.findall(
        r"\b(?:https?://)?(?:www\.)?"
        r"([a-zA-Z0-9](?:[a-zA-Z0-9-]{0,62}[a-zA-Z0-9])?"
        r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,62}[a-zA-Z0-9])?)+)"
        r"\b",
        text,
    )

    ignored = {
        "gmail.com",
        "google.com",
        "namecheap.com",
    }

    for candidate in candidates:
        value = candidate.casefold().rstrip(
            "."
        )

        if value in ignored:
            continue

        return value

    return ""


@dataclass(frozen=True)
class EmailPlatformPlan:
    domain: str
    hostname: str
    webmail_hostname: str
    smtp_ports: tuple[int, ...]
    imap_ports: tuple[int, ...]
    public_ipv4: str
    container_runtime: str
    namecheap_credentials_present: bool
    static_ip_present: bool
    deployment_bundle_ready: bool
    live_apply_allowed: bool


def _read_env_file(
    path: Path,
) -> dict[str, str]:
    values: dict[str, str] = {}

    if not path.is_file():
        return values

    for line in path.read_text(
        encoding="utf-8",
    ).splitlines():
        line = line.strip()

        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        key, value = line.split(
            "=",
            1,
        )

        values[
            key.strip()
        ] = value.strip().strip(
            '"'
        ).strip(
            "'"
        )

    return values


def _private_namecheap_state() -> dict[str, object]:
    """Inspect configuration presence without exposing credential values."""
    path = (
        Path.home()
        / ".config"
        / "sophyane"
        / "namecheap.env"
    )

    values = _read_env_file(
        path
    )

    for key in (
        "NAMECHEAP_API_USER",
        "NAMECHEAP_API_KEY",
        "NAMECHEAP_USERNAME",
        "NAMECHEAP_CLIENT_IP",
        "STATIC_IPV4",
        "STATIC_IPV6",
    ):
        env_value = os.environ.get(
            key
        )

        if env_value:
            values[
                key
            ] = env_value.strip()

    credential_names = (
        "NAMECHEAP_API_USER",
        "NAMECHEAP_API_KEY",
        "NAMECHEAP_CLIENT_IP",
    )

    credentials_present = all(
        bool(
            values.get(
                key
            )
        )
        for key in credential_names
    )

    static_ipv4 = str(
        values.get(
            "STATIC_IPV4"
        )
        or ""
    ).strip()

    if static_ipv4:
        try:
            ipaddress.IPv4Address(
                static_ipv4
            )
        except ValueError:
            static_ipv4 = ""

    return {
        "credentials_present":
            credentials_present,

        "static_ipv4":
            static_ipv4,

        "env_file_exists":
            path.is_file(),
    }


def _container_runtime() -> str:
    for command in (
        "docker",
        "podman",
    ):
        if shutil.which(
            command
        ):
            return command

    return ""


def build_plan(
    request: str,
) -> EmailPlatformPlan:
    domain = extract_domain(
        request
    )

    if not domain:
        raise ValueError(
            "No deployment domain was found in the request."
        )

    nc = _private_namecheap_state()

    runtime = _container_runtime()

    live_apply_allowed = str(
        os.environ.get(
            "SOPHYANE_EMAIL_PLATFORM_ALLOW_LIVE",
            ""
        )
    ).strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }

    ipv4 = str(
        nc[
            "static_ipv4"
        ]
        or ""
    )

    return EmailPlatformPlan(
        domain=domain,
        hostname=(
            "mail."
            + domain
        ),
        webmail_hostname=(
            "webmail."
            + domain
        ),
        smtp_ports=(
            25,
            465,
            587,
        ),
        imap_ports=(
            993,
        ),
        public_ipv4=ipv4,
        container_runtime=runtime,
        namecheap_credentials_present=bool(
            nc[
                "credentials_present"
            ]
        ),
        static_ip_present=bool(
            ipv4
        ),
        deployment_bundle_ready=True,
        live_apply_allowed=live_apply_allowed,
    )


def _compose_yaml(
    plan: EmailPlatformPlan,
) -> str:
    """Build user-owned mail infrastructure.

    docker-mailserver supplies the protocol engine.
    Roundcube is initially a reference webmail frontend.

    Nifdu's own webmail can replace Roundcube without changing SMTP/IMAP.
    """
    domain = plan.domain

    return f"""services:

  mailserver:
    image: ghcr.io/docker-mailserver/docker-mailserver:latest
    container_name: nifdu-mailserver
    hostname: mail.{domain}
    env_file:
      - ./mailserver.env
    ports:
      - "25:25"
      - "465:465"
      - "587:587"
      - "993:993"
    volumes:
      - ./data/mail-data:/var/mail
      - ./data/mail-state:/var/mail-state
      - ./data/mail-logs:/var/log/mail
      - ./data/config:/tmp/docker-mailserver
      - /etc/localtime:/etc/localtime:ro
    restart: unless-stopped
    stop_grace_period: 1m

  webmail:
    image: roundcube/roundcubemail:latest
    container_name: nifdu-webmail
    depends_on:
      - mailserver
    environment:
      ROUNDCUBEMAIL_DEFAULT_HOST: "ssl://mail.{domain}"
      ROUNDCUBEMAIL_DEFAULT_PORT: "993"
      ROUNDCUBEMAIL_SMTP_SERVER: "tls://mail.{domain}"
      ROUNDCUBEMAIL_SMTP_PORT: "587"
      ROUNDCUBEMAIL_USERNAME_DOMAIN: "{domain}"
      ROUNDCUBEMAIL_SKIN: "elastic"
    volumes:
      - ./data/roundcube-db:/var/roundcube/db
    ports:
      - "127.0.0.1:8080:80"
    restart: unless-stopped

networks:
  default:
    name: nifdu-mail
"""


def _mailserver_env(
    plan: EmailPlatformPlan,
) -> str:
    return f"""# Nifdu self-hosted mail plane
# No credentials belong in this file.

OVERRIDE_HOSTNAME=mail.{plan.domain}

ENABLE_IMAP=1
ENABLE_POP3=0

ENABLE_RSPAMD=1
ENABLE_CLAMAV=0
ENABLE_FAIL2BAN=0

POSTMASTER_ADDRESS=postmaster@{plan.domain}

# Production TLS is installed in a later verified deployment phase.
# Sophyane must not claim the service public/live until trusted TLS,
# DNS and end-to-end protocol checks pass.
SSL_TYPE=
"""


def _dns_plan(
    plan: EmailPlatformPlan,
) -> dict[str, object]:
    ip = (
        plan.public_ipv4
        or "<STATIC_PUBLIC_IPV4_REQUIRED>"
    )

    return {
        "domain":
            plan.domain,

        "provider":
            "namecheap-dns-only",

        "mail_provider":
            "self-hosted-nifdu",

        "records": [
            {
                "host":
                    "mail",
                "type":
                    "A",
                "address":
                    ip,
                "ttl":
                    300,
            },
            {
                "host":
                    "webmail",
                "type":
                    "A",
                "address":
                    ip,
                "ttl":
                    300,
            },
            {
                "host":
                    "@",
                "type":
                    "MX",
                "address":
                    "mail."
                    + plan.domain,
                "priority":
                    10,
                "ttl":
                    300,
            },
            {
                "host":
                    "@",
                "type":
                    "TXT",
                "address":
                    "v=spf1 mx -all",
                "ttl":
                    300,
            },
            {
                "host":
                    "_dmarc",
                "type":
                    "TXT",
                "address":
                    (
                        "v=DMARC1; p=quarantine; "
                        "rua=mailto:postmaster@"
                        + plan.domain
                    ),
                "ttl":
                    300,
            },
            {
                "host":
                    "mail._domainkey",
                "type":
                    "TXT",
                "address":
                    "<GENERATE_DKIM_KEY_AFTER_MAILSERVER_ACCOUNT_SETUP>",
                "ttl":
                    300,
            },
        ],

        "preserve_existing_records":
            True,

        "warning":
            (
                "Namecheap setHosts is replacement-style. "
                "The live phase must first read current DNS and "
                "merge managed mail records into it."
            ),
    }


def _readme(
    plan: EmailPlatformPlan,
) -> str:
    return f"""# Nifdu self-hosted email service

Domain: `{plan.domain}`

This bundle is infrastructure for a **new Nifdu email service**.

Namecheap is used only for DNS direction. It is not the email provider.

## Service boundary

User-owned hardware runs:

- SMTP transfer
- authenticated SMTP submission
- IMAP mail access
- persistent mailbox storage
- spam/authentication pipeline
- DKIM signing
- webmail
- Nifdu account/control plane added in subsequent stages

Namecheap controls only public DNS records.

## Public protocol endpoints

- SMTP transfer: `mail.{plan.domain}:25`
- SMTP submission: `mail.{plan.domain}:465` / `587`
- IMAPS: `mail.{plan.domain}:993`
- Webmail: `https://webmail.{plan.domain}` after reverse proxy/TLS stage

## Before Sophyane may report live success

Every item below must have objective evidence:

1. User-owned host reachable on a static public IP.
2. TCP/25 inbound reachable from the internet.
3. TCP/25 outbound not blocked by the network provider.
4. SMTP submission reachable with TLS.
5. IMAPS reachable with trusted TLS.
6. At least one Nifdu mailbox exists.
7. DKIM key generated and DNS TXT published.
8. SPF published.
9. DMARC published.
10. MX resolves to `mail.{plan.domain}`.
11. PTR/rDNS for the public sending IP points to `mail.{plan.domain}`.
12. Webmail login succeeds.
13. Outbound test email is accepted by a remote MX.
14. Inbound remote email reaches the Nifdu mailbox.

Until those tests pass:

`Success: False`

is the correct deployment status.

## Secret policy

Do not put:

- Namecheap API key
- mailbox passwords
- TLS private keys
- DKIM private key

inside HTML, Git, deployment reports or prompts.
"""


def write_bundle(
    request: str,
    workspace: Path | str,
    *,
    progress: Progress | None = None,
) -> tuple[
    EmailPlatformPlan,
    Path,
]:
    progress = progress or (
        lambda _message:
            None
    )

    plan = build_plan(
        request
    )

    root = (
        Path(
            workspace
        ).resolve()
        / "nifdu-email-platform"
    )

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        root
        / "data"
        / "config"
    ).mkdir(
        parents=True,
        exist_ok=True,
    )

    for directory in (
        "mail-data",
        "mail-state",
        "mail-logs",
        "roundcube-db",
    ):
        (
            root
            / "data"
            / directory
        ).mkdir(
            parents=True,
            exist_ok=True,
        )

    (
        root
        / "compose.yaml"
    ).write_text(
        _compose_yaml(
            plan
        ),
        encoding="utf-8",
    )

    (
        root
        / "mailserver.env"
    ).write_text(
        _mailserver_env(
            plan
        ),
        encoding="utf-8",
    )

    (
        root
        / "dns-plan.json"
    ).write_text(
        json.dumps(
            _dns_plan(
                plan
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    (
        root
        / "deployment-plan.json"
    ).write_text(
        json.dumps(
            asdict(
                plan
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    (
        root
        / "README.md"
    ).write_text(
        _readme(
            plan
        ),
        encoding="utf-8",
    )

    progress(
        "Nifdu email platform: self-hosted "
        "deployment bundle generated"
    )

    return (
        plan,
        root,
    )



def deployment_preflight(
    request: str,
) -> dict[str, object]:
    """Evaluate whether a real public mail deployment may begin.

    No external mutation is performed here.
    """
    plan = build_plan(
        request
    )

    checks = {
        "domain":
            bool(
                plan.domain
            ),

        "container_runtime":
            bool(
                plan.container_runtime
            ),

        "static_public_ipv4":
            bool(
                plan.static_ip_present
            ),

        "namecheap_credentials":
            bool(
                plan.namecheap_credentials_present
            ),

        "explicit_live_opt_in":
            bool(
                plan.live_apply_allowed
            ),
    }

    blockers: list[str] = []

    if not checks[
        "container_runtime"
    ]:
        blockers.append(
            "deployment host has no Docker/Podman runtime"
        )

    if not checks[
        "static_public_ipv4"
    ]:
        blockers.append(
            "STATIC_IPV4 is not configured"
        )

    if not checks[
        "namecheap_credentials"
    ]:
        blockers.append(
            "Namecheap API configuration is unavailable"
        )

    if not checks[
        "explicit_live_opt_in"
    ]:
        blockers.append(
            "live mutation is not explicitly enabled"
        )

    # These cannot be truthfully considered proven by configuration alone.
    external_proofs = {
        "public_tcp_25":
            False,

        "public_tcp_465":
            False,

        "public_tcp_587":
            False,

        "public_tcp_993":
            False,

        "trusted_tls":
            False,

        "mx_resolves":
            False,

        "spf_resolves":
            False,

        "dkim_resolves":
            False,

        "dmarc_resolves":
            False,

        "ptr_matches_mail_host":
            False,

        "smtp_submission":
            False,

        "imap_login":
            False,

        "external_receive":
            False,

        "external_send":
            False,
    }

    return {
        "ready_for_live_mutation":
            all(
                checks.values()
            ),

        "configuration_checks":
            checks,

        "external_proofs":
            external_proofs,

        "blockers":
            blockers,

        "important":
            (
                "PTR/rDNS is controlled by the public-IP provider, "
                "not by Namecheap DNS."
            ),

        "domain":
            plan.domain,

        "mail_host":
            plan.hostname,

        "webmail_host":
            plan.webmail_hostname,
    }


def managed_mail_dns_records(
    request: str,
) -> list[dict[str, str]]:
    """Return only records owned by the Nifdu mail deployment."""
    plan = build_plan(
        request
    )

    if not plan.public_ipv4:
        raise RuntimeError(
            "STATIC_IPV4 is required before generating live DNS records"
        )

    return [
        {
            "host": "mail",
            "type": "A",
            "address": plan.public_ipv4,
            "ttl": "300",
        },
        {
            "host": "webmail",
            "type": "A",
            "address": plan.public_ipv4,
            "ttl": "300",
        },
        {
            "host": "@",
            "type": "MX",
            "address": plan.hostname,
            "mx_pref": "10",
            "ttl": "300",
        },
        {
            "host": "@",
            "type": "TXT",
            "address": "v=spf1 mx -all",
            "ttl": "300",
        },
        {
            "host": "_dmarc",
            "type": "TXT",
            "address":
                (
                    "v=DMARC1; p=quarantine; "
                    f"rua=mailto:postmaster@{plan.domain}"
                ),
            "ttl": "300",
        },
    ]


def managed_mail_dns_keys() -> set[tuple[str, str]]:
    return {
        ("mail", "A"),
        ("webmail", "A"),
        ("@", "MX"),
        ("@", "TXT"),
        ("_dmarc", "TXT"),
        ("mail._domainkey", "TXT"),
    }


def run_email_platform_deployment(
    request: str,
    workspace: Path | str,
    *,
    progress: Progress | None = None,
) -> str:
    """Prepare the real self-hosted platform without false live claims."""
    progress = progress or (
        lambda _message:
            None
    )

    if not is_email_platform_request(
        request
    ):
        return (
            "Nifdu self-hosted email platform\n"
            "Handled: False\n"
            "Success: False"
        )

    try:
        plan, root = write_bundle(
            request,
            workspace,
            progress=progress,
        )

    except Exception as error:
        return "\n".join(
            [
                "Nifdu self-hosted email platform",
                "Handled: True",
                (
                    "Error: "
                    + f"{type(error).__name__}: {error}"
                ),
                "Success: False",
            ]
        )

    blockers = []

    if not plan.container_runtime:
        blockers.append(
            "container runtime missing on deployment host"
        )

    if not plan.static_ip_present:
        blockers.append(
            "STATIC_IPV4 not configured"
        )

    if not plan.namecheap_credentials_present:
        blockers.append(
            "Namecheap API configuration not present"
        )

    # Even when all current prerequisites exist, Stage 1 deliberately does
    # not modify DNS or launch public infrastructure. Stage 2 will perform
    # those mutations with DNS preservation and protocol verification.
    blockers.append(
        "live apply is intentionally disabled until "
        "DNS-preserving Namecheap mutation + TLS + protocol proof are installed"
    )

    lines = [
        "Nifdu self-hosted email platform",
        f"Request: {request}",
        "Handled: True",
        "Architecture: new self-hosted email service",
        "Mail provider: Nifdu / user-owned hardware",
        "Namecheap role: DNS control only",
        f"Domain: {plan.domain}",
        f"Mail host: {plan.hostname}",
        f"Webmail host: {plan.webmail_hostname}",
        (
            "Container runtime: "
            + (
                plan.container_runtime
                or "missing"
            )
        ),
        (
            "Static public IPv4 configured: "
            + str(
                plan.static_ip_present
            )
        ),
        (
            "Namecheap API configured: "
            + str(
                plan.namecheap_credentials_present
            )
        ),
        f"Deployment bundle: {root}",
        "Files:",
        "  nifdu-email-platform/compose.yaml",
        "  nifdu-email-platform/mailserver.env",
        "  nifdu-email-platform/dns-plan.json",
        "  nifdu-email-platform/deployment-plan.json",
        "  nifdu-email-platform/README.md",
        "Deployment state: planned / not yet live",
        "Blockers:",
    ]

    lines.extend(
        "  - "
        + item
        for item in blockers
    )

    lines.extend(
        [
            "DNS mutated: False",
            "Mail server launched: False",
            "End-to-end mail verified: False",
            "Success: False",
        ]
    )

    return "\n".join(
        lines
    )


__all__ = [
    "EmailPlatformPlan",
    "build_plan",
    "extract_domain",
    "is_email_platform_request",
    "run_email_platform_deployment",
    "write_bundle",
]
