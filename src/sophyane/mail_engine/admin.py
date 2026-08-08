"""Administration CLI for PostgreSQL-backed Nifdu mail accounts."""
from __future__ import annotations

import argparse
import getpass

from .accounts import AccountStore


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--root",
        default="",
        help=(
            "Deprecated compatibility argument. "
            "Mail durability is PostgreSQL-only."
        ),
    )

    parser.add_argument(
        "--domain",
        required=True,
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    create = sub.add_parser(
        "create"
    )

    create.add_argument(
        "address"
    )

    create.add_argument(
        "--password",
        default="",
    )

    sub.add_parser(
        "list"
    )

    args = parser.parse_args()

    accounts = AccountStore(
        domain=args.domain,
    )

    if args.command == "create":
        password = (
            args.password
            or getpass.getpass(
                "Mail password: "
            )
        )

        address = accounts.create(
            args.address,
            password,
        )

        print(
            "Created:",
            address,
        )

        return 0

    for address in accounts.list_accounts():
        print(
            address
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
