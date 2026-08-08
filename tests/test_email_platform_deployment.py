from pathlib import Path
from unittest.mock import patch

from sophyane.email_platform_deployment import (
    build_plan,
    extract_domain,
    is_email_platform_request,
    run_email_platform_deployment,
    write_bundle,
)
from sophyane.sli_graph import (
    SLIState,
    classify,
    run_sli_graph,
)


REQUEST = (
    "make nifdu email serviced live on my "
    "namecheap domain www.nifdu.com through namecheap api"
)


def test_exact_request_is_email_platform() -> None:
    assert is_email_platform_request(
        REQUEST
    )

    state = classify(
        SLIState(
            request=REQUEST,
            workspace=".",
        ),
        lambda _message:
            None,
    )

    assert (
        state.route
        ==
        "email_platform"
    )


def test_browser_only_email_product_remains_product_app() -> None:
    request = (
        "make a website that provides an "
        "email service interface like gmail"
    )

    assert not is_email_platform_request(
        request
    )

    state = classify(
        SLIState(
            request=request,
            workspace=".",
        ),
        lambda _message:
            None,
    )

    assert (
        state.route
        ==
        "product_app"
    )


def test_extract_nifdu_domain() -> None:
    assert (
        extract_domain(
            REQUEST
        )
        ==
        "nifdu.com"
    )


def test_plan_is_self_hosted_not_namecheap_mail(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.email_platform_deployment."
        "_private_namecheap_state",
        lambda: {
            "credentials_present":
                True,
            "static_ipv4":
                "203.0.113.10",
            "env_file_exists":
                True,
        },
    )

    monkeypatch.setattr(
        "sophyane.email_platform_deployment."
        "_container_runtime",
        lambda:
            "docker",
    )

    plan = build_plan(
        REQUEST
    )

    assert plan.domain == "nifdu.com"

    assert (
        plan.hostname
        ==
        "mail.nifdu.com"
    )

    assert 25 in plan.smtp_ports
    assert 587 in plan.smtp_ports
    assert 993 in plan.imap_ports


def test_bundle_contains_real_mail_plane(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.email_platform_deployment."
        "_private_namecheap_state",
        lambda: {
            "credentials_present":
                False,
            "static_ipv4":
                "",
            "env_file_exists":
                False,
        },
    )

    monkeypatch.setattr(
        "sophyane.email_platform_deployment."
        "_container_runtime",
        lambda:
            "",
    )

    _plan, root = write_bundle(
        REQUEST,
        tmp_path,
    )

    compose = (
        root
        / "compose.yaml"
    ).read_text(
        encoding="utf-8",
    )

    dns = (
        root
        / "dns-plan.json"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "docker-mailserver"
        in compose
    )

    assert (
        "roundcube"
        in compose
    )

    assert '"25:25"' in compose
    assert '"587:587"' in compose
    assert '"993:993"' in compose

    assert (
        '"type": "MX"'
        in dns
    )

    assert (
        "mail._domainkey"
        in dns
    )

    assert (
        "v=spf1 mx -all"
        in dns
    )

    assert (
        "_dmarc"
        in dns
    )

    assert (
        "preserve_existing_records"
        in dns
    )


def test_stage1_never_claims_live_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.email_platform_deployment."
        "_private_namecheap_state",
        lambda: {
            "credentials_present":
                True,
            "static_ipv4":
                "203.0.113.10",
            "env_file_exists":
                True,
        },
    )

    monkeypatch.setattr(
        "sophyane.email_platform_deployment."
        "_container_runtime",
        lambda:
            "docker",
    )

    report = run_email_platform_deployment(
        REQUEST,
        tmp_path,
    )

    assert (
        "Architecture: new self-hosted email service"
        in report
    )

    assert (
        "Namecheap role: DNS control only"
        in report
    )

    assert (
        "DNS mutated: False"
        in report
    )

    assert (
        "Mail server launched: False"
        in report
    )

    assert (
        "End-to-end mail verified: False"
        in report
    )

    assert (
        "Success: False"
        in report
    )


def test_graph_does_not_fall_into_harness_or_internet(
    tmp_path: Path,
) -> None:
    with (
        patch(
            "sophyane.sli_graph.try_harness_execution",
            side_effect=AssertionError(
                "harness must not run"
            ),
        ),
        patch(
            "sophyane.sli_graph.try_internet",
            side_effect=AssertionError(
                "internet acquisition must not run"
            ),
        ),
        patch(
            "sophyane.sli_graph.try_memory_router",
            side_effect=AssertionError(
                "generic memory router must not run"
            ),
        ),
    ):
        state = run_sli_graph(
            REQUEST,
            workspace=tmp_path,
            max_retries=1,
        )

    assert (
        state.route
        ==
        "email_platform"
    )

    assert (
        state.meta.get(
            "terminal"
        )
        is True
    )

    assert (
        "Namecheap role: DNS control only"
        in state.report
    )
