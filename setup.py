from setuptools import find_packages, setup


setup(
    name="sophyane",
    version="20.3.1",
    description=(
        "Adaptive local agentic software harness with validator-grounded "
        "execution learning"
    ),
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    entry_points={
        "console_scripts": [
            "sophyane=sophyane.cli_entry:main",
            "sophyane-web=sophyane.web:main",
            "sophyane-doctor=sophyane.diagnostics:main",
            "sophyane-sli=sophyane.sli_cli:main",
            "sophyane-sli-train=sophyane.sli_training_loop:main",
        ]
    },
    python_requires=">=3.10",
)
