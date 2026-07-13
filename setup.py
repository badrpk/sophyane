from setuptools import find_packages, setup


setup(
    name="sophyane",
    version="6.0.1",
    description=(
        "Multi-provider local agentic harness with persistent "
        "memory, safe tools, plugins and repository awareness"
    ),
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    entry_points={
        "console_scripts": [
            "sophyane=sophyane.main:main",
            "sophyane-doctor=sophyane.diagnostics:run_diagnostics",
        ],
    },
    python_requires=">=3.10",
)
