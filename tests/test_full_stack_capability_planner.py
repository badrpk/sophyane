from sophyane.runtime_sli_capability_planner import (
    classify,
)


def test_project_management_saas_is_full_stack() -> None:
    plan = classify(
        """
        Build a complete local project-management SaaS.

        Requirements:
        - responsive web frontend
        - projects and tasks
        - create/edit/delete tasks
        - persistent local database
        - REST API
        - validation and error handling
        - dashboard statistics
        - automated tests
        - run locally
        """
    )

    assert (
        plan.project_type
        == "full_stack_web_application"
    )

    assert plan.language == "Python"

    assert (
        plan.target
        == "local web application"
    )

    assert (
        plan.builder
        == "FULL_STACK_PROVIDER_BOUNDED"
    )

    assert "responsive_web_frontend" in plan.capabilities
    assert "rest_api" in plan.capabilities
    assert "persistent_database" in plan.capabilities
    assert "crud" in plan.capabilities
    assert "validation" in plan.capabilities
    assert "automated_tests" in plan.capabilities
    assert "dashboard" in plan.capabilities


def test_full_stack_detection_does_not_require_saas_word() -> None:
    plan = classify(
        """
        Build a responsive web application with
        a REST API, SQLite database and automated tests.
        """
    )

    assert (
        plan.project_type
        == "full_stack_web_application"
    )


def test_static_website_is_not_full_stack() -> None:
    plan = classify(
        "Build a simple informational website about dogs."
    )

    assert (
        plan.project_type
        != "full_stack_web_application"
    )


def test_cli_program_is_not_full_stack() -> None:
    plan = classify(
        "Create a Python command line calculator."
    )

    assert (
        plan.project_type
        == "software_project"
    )


def test_explicit_language_is_preserved() -> None:
    plan = classify(
        """
        Build a Node.js SaaS with responsive web frontend,
        REST API, persistent database and automated tests.
        """
    )

    assert (
        plan.project_type
        == "full_stack_web_application"
    )

    assert plan.language == "Node.js"
