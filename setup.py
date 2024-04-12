#!/usr/bin/env python

# This file is part of connectome-manipulator.
#
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024 Blue Brain Project/EPFL

import importlib.util
from setuptools import setup, find_packages

# read the contents of the README file
with open("README.rst", encoding="utf-8") as f:
    README = f.read()

spec = importlib.util.spec_from_file_location(
    "connectome_manipulator.version",
    "connectome_manipulator/version.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
VERSION = module.__version__


setup(
    name="connectome-manipulator",
    author="Blue Brain Project, EPFL",
    version=VERSION,
    description="A connectome manipulation framework for SONATA circuits",
    long_description=README,
    long_description_content_type="text/x-rst",
    url="https://bbpgitlab.epfl.ch/conn/structural/connectome_manipulator.git",
    project_urls={
        "Tracker": "https://bbpteam.epfl.ch/project/issues/projects/SSCXDIS/issues",
        "Source": "https://bbpgitlab.epfl.ch/conn/structural/connectome_manipulator.git",
    },
    license="Apache-2",
    install_requires=[
        "bluepysnap>=3.0.1",
        "numpy",
        "pandas",
        "progressbar",
        "pyarrow",
        "scipy",
        "scikit-learn",
        "voxcell",
        "pyarrow",
        "scikit-learn",
        "tables",  # Optional dependency of pandas.DataFrame.to_hdf()
        "distributed",  # Dask
        "dask-mpi",
    ],
    packages=find_packages(),
    python_requires=">=3.7",
    extras_require={"docs": ["sphinx", "sphinx-bluebrain-theme"]},
    entry_points={
        "console_scripts": [
            "connectome-manipulator=connectome_manipulator.cli:app",
            "parallel-manipulator=connectome_manipulator.cli_parallel:app",
        ]
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Education",
        "Intended Audience :: Science/Research",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: Scientific/Engineering",
        "Topic :: Scientific/Engineering :: Bio-Informatics",
    ],
)
