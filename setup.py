from setuptools import find_packages, setup


setup(
    name="sophyane",
    version="15.0.0",
    description=(
        "Self-repairing autonomous AI doer with persistent memory, "
        "safe execution and evidence-based verification"
    ),
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    entry_points={
        "console_scripts": [
            "sophyane=sophyane.v13_cli:main",
            "sophyane-web=sophyane.web:main",
            "sophyane-doctor=sophyane.diagnostics:main",
        ],
    },
    python_requires=">=3.10",
)
