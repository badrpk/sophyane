from setuptools import find_packages, setup


setup(
    name="sophyane",
    version="11.0.0",
    description=(
        "Cross-platform autonomous agentic software harness "
        "with stateful execution graphs"
    ),
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    entry_points={
        "console_scripts": [
            "sophyane=sophyane.main:main",
            "sophyane-web=sophyane.web:main",
            "sophyane-doctor=sophyane.diagnostics:main",
        ],
    },
    python_requires=">=3.10",
)
