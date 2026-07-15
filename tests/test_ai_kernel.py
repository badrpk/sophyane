from __future__ import annotations

import json
from pathlib import Path

from sophyane.kernel import boot_kernel
from sophyane.kernel.app_factory import SUPPORTED_TARGETS, create_app
from sophyane.kernel.erp import ERP_CATALOG, list_erp_systems, probe_erp


def test_kernel_boot_and_modules() -> None:
    kernel = boot_kernel()
    status = kernel.status()
    assert status.ok is True
    names = {m["name"] for m in status.modules}
    for required in ("hardware", "software", "app_factory", "erp", "agents", "security"):
        assert required in names
    assert "web" in status.app_targets
    assert "oracle" in status.erp_systems
    payload = json.loads(status.to_json())
    assert payload["version"]


def test_app_factory_web(tmp_path: Path) -> None:
    result = create_app("web", "Exam Web", output_dir=tmp_path / "webapp")
    assert result.ok is True
    root = Path(result.path)
    assert (root / "index.html").exists()
    assert (root / "sophyane-app.json").exists()
    assert set(SUPPORTED_TARGETS) >= {"web", "android", "harmony", "ios"}


def test_app_factory_mobile_targets(tmp_path: Path) -> None:
    for target in ("android", "harmony", "ios"):
        result = create_app(target, f"App {target}", output_dir=tmp_path / target)
        assert result.ok is True, result.message
        assert Path(result.path).exists()


def test_erp_catalog_and_probe() -> None:
    systems = {item["id"] for item in list_erp_systems()}
    for key in ("oracle", "sap", "odoo", "dynamics", "netsuite", "erpnext"):
        assert key in systems
        assert key in ERP_CATALOG
    status = probe_erp("oracle")
    assert status.system == "oracle"
    assert status.configured is False or isinstance(status.base_url, str)
