# MAVIS snakemake

![PyPi](https://img.shields.io/pypi/v/mavis.svg) ![build](https://github.com/bcgsc/mavis/workflows/build/badge.svg?branch=master) [![codecov](https://codecov.io/gh/bcgsc/mavis/branch/master/graph/badge.svg)](https://codecov.io/gh/bcgsc/mavis) ![ReadTheDocs](https://readthedocs.org/projects/pip/badge/)

## About

This is an adaptation of [MAVIS](http://mavis.bcgsc.ca) using snakemake. Previously MAVIS
incorporated a lot of custom code for creating local and cluster pipelines. This project tests
using snakemake to accomplish this instead. You can see a comparison of the code changes done to the
project for this project by comparing the develop branch of this repository to its master branch

## Getting Started

Install a virtualenv using python3.6 or higher

```bash
python3 -m venv venv
source venv/bin/activate
pip install -U setuptools pip
pip install .
```

The test pipeline which is incorporated here uses mock bam files which are included in the tests
directory of this repository. This is configured by the JSON configuration found at the base
level of this repository

```text
test-mini-tutorial.json
```

Due to the fact that the number of files is dynamic, this snakemake pipeline is done in 2 steps.
The first snakemake file will setup the directory, convert input files, and cluster the initial
inputs into a set of jobs. The example below uses a jobs number of 4 but any number 1 or higher
can be used.

This pipeline is flexible to work with any set of samples, the same setup is configured by
the config file that it is passed

```bash
snakemake --jobs 4 -s Snakefile.cluster --configfile test-mini-tutorial.json
```
