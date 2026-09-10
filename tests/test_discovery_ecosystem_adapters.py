from sophyane.discovery_ecosystem_adapters import (
    probe_discovery_ecosystem,
)


def test_probe_never_claims_unverified_adapter():
    probes = probe_discovery_ecosystem()

    assert set(probes) == {
        "neuron",
        "xerus",
        "nifdu",
    }

    for name, probe in probes.items():
        assert probe.repository == name

        if probe.available:
            assert probe.module
            assert probe.callable_name
            assert (
                probe.reason
                == "CALLABLE_CONTRACT_VERIFIED"
            )
        else:
            assert (
                probe.reason
                == "NO_VERIFIED_CALLABLE_CONTRACT"
            )
