from sophyane import adaptive_execution


def test_plain_topic_website_remains_browser_route() -> None:
    assert adaptive_execution._browser_request(
        "make website on dogs"
    )


def test_explicit_html_remains_browser_route() -> None:
    assert adaptive_execution._browser_request(
        "create index.html portfolio"
    )


def test_browser_game_remains_browser_route() -> None:
    assert adaptive_execution._browser_request(
        "build browser game with touch controls"
    )


def test_full_stack_saas_bypasses_browser_one_shot() -> None:
    request = """
    Build a complete local project-management SaaS.

    Requirements:
    - responsive web frontend
    - projects and tasks
    - persistent local database
    - REST API
    - automated tests
    - verify frontend and API behavior mechanically
    - do not satisfy this with only index.html
    """

    assert not adaptive_execution._browser_request(
        request
    )


def test_rest_plus_sqlite_web_app_bypasses_one_shot() -> None:
    assert not adaptive_execution._browser_request(
        """
        Build a web app with HTML frontend,
        REST API,
        persistent SQLite database,
        tests and browser verification.
        """
    )


def test_full_stack_contract_is_authoritative() -> None:
    assert not adaptive_execution._browser_request(
        """
        === SOPHYANE FULL-STACK ARCHITECTURE CONTRACT ===
        Python sqlite3 persistent storage.
        REST-style JSON endpoints.
        HTML/CSS/vanilla JavaScript browser frontend.
        === END FULL-STACK ARCHITECTURE CONTRACT ===
        """
    )


def test_api_without_persistence_does_not_accidentally_define_full_stack() -> None:
    assert adaptive_execution._browser_request(
        """
        Build a browser dashboard that displays
        data from a REST API.
        """
    )


def test_database_without_api_does_not_accidentally_define_full_stack() -> None:
    assert adaptive_execution._browser_request(
        """
        Build an HTML website describing
        a SQLite database schema.
        """
    )
