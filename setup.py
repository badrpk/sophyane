from setuptools import find_packages, setup


setup(
    name="sophyane",
    version="17.1.0",
    description=(
        "Repository-aware autonomous coding agent with semantic indexing, "
        "precise patches, batched execution and deterministic verification"
    ),
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    entry_points={
        "console_scripts": [
            "sophyane=sophyane.cli_entry:main",
            "sophyane-web=sophyane.web:main",
            "sophyane-doctor=sophyane.diagnostics:main",
        ]
    },
    python_requires=">=3.10",
)
