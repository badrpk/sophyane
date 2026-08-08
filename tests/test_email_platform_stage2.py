from unittest.mock import patch

from sophyane.email_platform_deployment import (
    deployment_preflight,
    extract_domain,
    is_email_platform_request,
    managed_mail_dns_keys,
)


REQUEST = (
    "make nifdu email serviced live on my namecheap "
    "domain www.nifdu.com through namecheap api"
)


def test_request_remains_self_hosted_email_domain() -> None:
    assert is_email_platform_request(
        REQUEST
    )

    assert extract_domain(
        REQUEST
    ) == "nifdu.com"


def test_preflight_never_claims_external_proofs() -> None:
    result = deployment_preflight(
        REQUEST
    )

    proofs = result[
        "external_proofs"
    ]

    assert proofs

    assert all(
        value is False
        for value in proofs.values()
    )


def test_ptr_is_not_treated_as_namecheap_dns() -> None:
    result = deployment_preflight(
        REQUEST
    )

    assert (
        "public-IP provider"
        in result["important"]
    )


def test_managed_dns_scope_is_bounded() -> None:
    keys = managed_mail_dns_keys()

    assert (
        "mail",
        "A",
    ) in keys

    assert (
        "webmail",
        "A",
    ) in keys

    assert (
        "@",
        "MX",
    ) in keys

    assert (
        "_dmarc",
        "TXT",
    ) in keys

    # Existing web service must not be owned/replaced by mail deployment.
    assert (
        "www",
        "A",
    ) not in keys

    assert (
        "www",
        "CNAME",
    ) not in keys


def test_live_preflight_remains_false_without_requirements() -> None:
    result = deployment_preflight(
        REQUEST
    )

    assert (
        result[
            "ready_for_live_mutation"
        ]
        is False
    )
