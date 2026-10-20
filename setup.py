from setuptools import Extension, find_packages, setup


native_reconciler = Extension(
    "sophyane.native._reconciler",
    sources=["src/sophyane/native/reconciler.cpp"],
    language="c++",
    libraries=["sqlite3"],
    extra_compile_args=["-std=c++17", "-O3", "-pthread"],
    extra_link_args=["-pthread"],
)


setup(
    name="sophyane",
    version="27.0.1",
    description=(
        "Local-first AI software engineering platform with durable execution, "
        "repository intelligence and validator-grounded recovery"
    ),
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    ext_modules=[native_reconciler],
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
