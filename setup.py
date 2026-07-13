from setuptools import setup, find_packages

setup(
    name="sophyane",
    version="4.0.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=["requests"],
    entry_points={
        'console_scripts': [
            'sophyane = sophyane.main:main',
        ],
    },
    python_requires='>=3.8',
    description="Local Agentic AI Harness",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
)
