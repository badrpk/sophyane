from setuptools import find_packages, setup

setup(
    name="sophyane",
    version="5.0.0",
    description="Multi-LLM local agentic harness with safe tools and memory",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    entry_points={
        "console_scripts": [
            "sophyane=sophyane.main:main",
        ],
    },
    python_requires=">=3.10",
)
