# MAVIS snakemake

![PyPi](https://img.shields.io/pypi/v/mavis.svg) ![build](https://github.com/bcgsc/mavis/workflows/build/badge.svg?branch=master) [![codecov](https://codecov.io/gh/bcgsc/mavis/branch/master/graph/badge.svg)](https://codecov.io/gh/bcgsc/mavis) ![ReadTheDocs](https://readthedocs.org/projects/pip/badge/)

## About

This is an adaptation of [MAVIS](http://mavis.bcgsc.ca) using snakemake. Previously MAVIS
incorporated a lot of custom code for creating local and cluster pipelines. This project tests
using snakemake to accomplish this instead. You can see a comparison of the code changes done to the
project for this project by comparing the develop branch of this repository to its master branch

## Getting Started

### Set up the Python Virtual Env

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

### Install the Aligner (Blat)

Before the pipeline is run an aligner must be installed. The default aligner to be used is blat,
although bwa mem can also be configured to be used. Instructions on installing blat can be
found here:

If you are using a linux systems the following should work

```bash
mkdir bin
cd bin
wget http://hgdownload.soe.ucsc.edu/admin/exe/linux.x86_64/blat/blat
chmod 777 blat
```

now test that the install worked by running the new executable

```bash
./blat
```

you should see the default help menu

The aligner must be on the default path when the snakemake files are run

```bash
cd ..
export PATH=$(pwd)/bin:$PATH
which blat
```

### Running Snakemake

Due to the fact that the number of files is dynamic, this snakemake pipeline is done in 2 steps.
The first snakemake file will setup the directory, convert input files, and cluster the initial
inputs into a set of jobs. The example below uses a jobs number of 4 but any number 1 or higher
can be used.

This pipeline is flexible to work with any set of samples, the same setup is configured by
the config file that it is passed

```bash
snakemake --jobs 4 -s cluster.snakefile --configfile test-mini-tutorial.json
```

After the first stage is run you should see the following files

```text
output_dir/
|-- converted_outputs
|   |-- mock_converted.tab
|   `-- snakemake.mock_converted.log.txt
|-- mavis.config.json
|-- mock-A36971
|   |-- annotate
|   |-- cluster
|   |   |-- batch-10.tab
|   |   |-- batch-11.tab
|   |   |-- batch-12.tab
|   |   |-- batch-13.tab
|   |   |-- batch-14.tab
|   |   |-- batch-1.tab
|   |   |-- batch-2.tab
|   |   |-- batch-3.tab
|   |   |-- batch-4.tab
|   |   |-- batch-5.tab
|   |   |-- batch-6.tab
|   |   |-- batch-7.tab
|   |   |-- batch-8.tab
|   |   |-- batch-9.tab
|   |   |-- cluster_assignment.tab
|   |   |-- clusters.bed
|   |   |-- filtered_pairs.tab
|   |   `-- MAVIS.COMPLETE
|   |-- SETUP.COMPLETE
|   |-- snakemake.cluster.log.txt
|   `-- validate
|-- mock-A47933
|   |-- annotate
|   |-- cluster
|   |   |-- batch-1.tab
|   |   |-- cluster_assignment.tab
|   |   |-- clusters.bed
|   |   |-- filtered_pairs.tab
|   |   `-- MAVIS.COMPLETE
|   |-- SETUP.COMPLETE
|   |-- snakemake.cluster.log.txt
|   `-- validate
|-- pairing
|-- SETUP.COMPLETE
`-- summary
```

The next pipeline file runs the validate, annotate, pairing, and summary stages of the MAVIS
pipelines.

```bash
snakemake --jobs 4 -s validate.snakefile --configfile test-mini-tutorial.json
```

Once this is complete the file structural variant calls will be in this file

```text
output_dir/summary/mavis_summary_all_mock-A36971_mock-A47933.tab
```
