from setuptools import find_packages, setup


setup(
    name="sophyane",
    version="13.0.0",
    description=(
        "Cross-platform autonomous multi-agent AI runtime "
        "with durable stateful execution graphs"
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
