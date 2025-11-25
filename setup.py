from setuptools import setup, find_packages

setup(
    name="panos-upgrade",
    version="0.1.0",
    description="Advanced PAN-OS device upgrade management system",
    author="Nathan",
    python_requires=">=3.11",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        "pan-python>=0.17.0",
        "click>=8.1.0",
        "pyyaml>=6.0",
        "watchdog>=3.0.0",
    ],
    entry_points={
        "console_scripts": [
            "panos-upgrade=panos_upgrade.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: System Administrators",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
    ],
)
