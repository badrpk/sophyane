import json
from pathlib import Path
import sys

from sophyane.edge.routing import (
    routes_from_manifest,
)
from sophyane.service_fabric.manifest import (
    load_manifest,
)


def test_native_mail_manifest_maps_real_protocol_engines(
    tmp_path: Path,
) -> None:
    root = (
        tmp_path
        / "runtime"
    )

    path = (
        tmp_path
        / "native-mail.json"
    )

    path.write_text(
        json.dumps(
            {
                "version":
                    1,

                "name":
                    "nifdu-native-mail",

                "services":
                    [
                        {
                            "name":
                                "smtp",

                            "command":
                                [
                                    sys.executable,
                                    "-m",
                                    "sophyane.mail_engine.smtp_server",
                                    "--root",
                                    str(
                                        root
                                    ),
                                    "--domain",
                                    "nifdu.com",
                                    "--port",
                                    "2525",
                                ],

                            "health":
                                {
                                    "kind":
                                        "tcp",

                                    "port":
                                        2525,
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
                                "submission",

                            "command":
                                [
                                    sys.executable,
                                    "-m",
                                    "sophyane.mail_engine.smtp_server",
                                    "--root",
                                    str(
                                        root
                                    ),
                                    "--domain",
                                    "nifdu.com",
                                    "--port",
                                    "1587",
                                    "--require-auth",
                                ],

                            "health":
                                {
                                    "kind":
                                        "tcp",

                                    "port":
                                        1587,
                                },

                            "publish":
                                [
                                    {
                                        "protocol":
                                            "tcp",

                                        "local_port":
                                            1587,

                                        "public_port":
                                            587,
                                    }
                                ],
                        },

                        {
                            "name":
                                "imap",

                            "command":
                                [
                                    sys.executable,
                                    "-m",
                                    "sophyane.mail_engine.imap_server",
                                    "--root",
                                    str(
                                        root
                                    ),
                                    "--domain",
                                    "nifdu.com",
                                    "--port",
                                    "1993",
                                ],

                            "health":
                                {
                                    "kind":
                                        "tcp",

                                    "port":
                                        1993,
                                },

                            "publish":
                                [
                                    {
                                        "protocol":
                                            "tcp",

                                        "local_port":
                                            1993,

                                        "public_port":
                                            993,
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

    routes = routes_from_manifest(
        manifest
    )

    mapping = {
        (
            route.local_port,
            route.public_port,
        )
        for route in routes
    }

    assert (
        2525,
        25,
    ) in mapping

    assert (
        1587,
        587,
    ) in mapping

    assert (
        1993,
        993,
    ) in mapping
