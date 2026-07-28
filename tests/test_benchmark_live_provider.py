from __future__ import annotations

from sophyane.benchmark_cli import ProductBenchmarks


class _Provider:
    def generate(self, prompt: str, system: str) -> str:
        assert "counter app" in prompt
        assert "product engineer" in system
        return (
            "<!doctype html><html><head>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<style>html,body{width:100vw;height:100vh}</style>"
            "</head><body><p>Score: 0</p><button>Count</button>"
            "<script>document.querySelector('button').onclick=()=>1</script>"
            "</body></html>"
        )


def test_live_benchmark_uses_supported_provider_factory(monkeypatch) -> None:
    import sophyane.config
    import sophyane.main

    config = {"provider": "test", "model": "test-model"}
    monkeypatch.setattr(sophyane.config, "load_config", lambda: config)
    monkeypatch.setattr(sophyane.main, "create_provider", lambda value: _Provider())

    benchmark = ProductBenchmarks(live=True)
    benchmark.live_product()

    assert len(benchmark.results) == 1
    result = benchmark.results[0]
    assert result.category == "live"
    assert result.name == "provider creates complete product"
    assert result.ok is True
    assert result.skipped is False
