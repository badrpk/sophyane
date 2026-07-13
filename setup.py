from setuptools import find_packages, setup


setup(
    name="sophyane",
    version="6.1.0",
    description="Cross-platform multi-provider local agentic AI harness",
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
