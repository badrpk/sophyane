import json
from pathlib import Path

import pytest

from sophyane.edge.routing import (
    routes_from_manifest,
)
from sophyane.service_fabric.manifest import (
    load_manifest,
)


def test_manifest_and_edge_routes(
    tmp_path: Path,
) -> None:
    path = (
        tmp_path
        / "service.json"
    )

    path.write_text(
        json.dumps(
            {
                "version":
                    1,

                "name":
                    "nifdu-mail",

                "services":
                    [
                        {
                            "name":
                                "smtp",

                            "command":
                                [
                                    "python",
                                    "-c",
                                    "import time; time.sleep(5)",
                                ],

                            "health":
                                {
                                    "kind":
                                        "process",
                                },

                            "publish":
                                [
                                    {
                                        "protocol":
                                            "tcp",

                                        "local_port":
                                            2525,

                                        "public_port":
                                            25,
                                    }
                                ],
                        },

                        {
                            "name":
                                "webmail",

                            "command":
                                [
                                    "python",
                                    "-c",
                                    "import time; time.sleep(5)",
                                ],

                            "depends_on":
                                [
                                    "smtp",
                                ],

                            "publish":
                                [
                                    {
                                        "protocol":
                                            "https",

                                        "local_port":
                                            8080,

                                        "hostname":
                                            "webmail.nifdu.com",

                                        "tls":
                                            True,
                                    }
                                ],
                        },
                    ],
            }
        ),
        encoding="utf-8",
    )

    manifest = load_manifest(
        path
    )

    assert manifest.name == "nifdu-mail"

    routes = routes_from_manifest(
        manifest
    )

    assert len(
        routes
    ) == 2

    smtp = next(
        route
        for route in routes
        if route.service == "smtp"
    )

    assert smtp.local_port == 2525
    assert smtp.public_port == 25


def test_unknown_dependency_is_rejected(
    tmp_path: Path,
) -> None:
    path = (
        tmp_path
        / "bad.json"
    )

    path.write_text(
        json.dumps(
            {
                "name":
                    "bad",

                "services":
                    [
                        {
                            "name":
                                "api",

                            "command":
                                [
                                    "python",
                                    "-V",
                                ],

                            "depends_on":
                                [
                                    "database",
                                ],
                        }
                    ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="unknown dependencies",
    ):
        load_manifest(
            path
        )
