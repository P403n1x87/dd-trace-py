import os

from setuptools import setup, find_packages

HERE = os.path.dirname(os.path.abspath(__file__))


long_description = open(os.path.join(HERE, "README.md")).read()


# Base `setup()` kwargs without any C-extension registering
setup(
    name="scenarios",
    description="Benchmark utility",
    url="https://github.com/DataDog/???",
    author="Datadog, Inc.",
    author_email="dev@datadoghq.com",
    long_description=long_description,
    long_description_content_type="text/markdown",
    license="BSD",
    packages=find_packages(exclude=["tests*"]),
    python_requires=">=3.7",
    install_requires=["click", "docker", "rich", "seaborn", "semver", "toml"],
    # plugin tox
    tests_require=["tox", "flake8", "pytest"],
    extras_require={
        "tests": [
            "tox",
            "flake8",
            "pytest",
        ],
    },
    entry_points={
        "console_scripts": ["scenario = scenarios.__main__:main"],
    },
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
    ],
    # use_scm_version=True,
    # setup_requires=["setuptools_scm[toml]>=4"],
)
