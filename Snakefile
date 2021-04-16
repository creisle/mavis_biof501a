from snakemake.utils import validate
from snakemake import WorkflowError
import os
from typing import List
import re
import json

from mavis import util as _util
from mavis.constants import SUBCOMMAND


CONTAINER = 'creisle/mavis:latest'


try:
    validate(
        config,
        os.path.join(os.getcwd(), 'mavis/config-schema.json')
    )
except Exception as err:
    short_msg = ' '.join(str(err).split('\n')[:2]) # these can get super long
    raise WorkflowError(short_msg)


def get_cluster_inputs(w):
    conversions = config['convert']
    inputs = []
    for assignment in config['libraries'][w.library]['assign']:
        if assignment in conversions:
            inputs.extend(expand(rules.convert.output, alias=assignment))
        else:
            inputs.append(assignment)

    print('cluster inupts:', inputs)
    return inputs



def skip_validate(config):
    return 'validate' in config.get('skip_stage', [])


def output_dir(*paths):
    return os.path.join(config['output_dir'], *paths)


libraries = sorted(list(config['libraries']))


rule all:
    input: output_dir('summary/MAVIS.COMPLETE')


rule copy_config:
    output: output_dir('config.raw.json')
    run:
        with open(output_dir('config.raw.json'), 'w') as fh:
            fh.write(json.dumps(config, sort_keys=True, indent='  '))


rule init_config:
    input: rules.copy_config.output
    output: output_dir('config.json')
    log: output_dir('init_config.log.txt')
    container: CONTAINER
    shell: 'mavis setup --config {input} --outputfile {output} &> {log}'


rule convert:
    output: output_dir('converted_outputs/{alias}.tab')
    input: rules.init_config.output
    log: output_dir('converted_outputs/snakemake.{alias}.log.txt')
    params:
        file_type=lambda w: config['convert'][w.alias]['file_type'],
        strand_specific=lambda w: config['convert'][w.alias]['strand_specific'],
        assume_no_untemplated=lambda w: config['convert'][w.alias]['assume_no_untemplated'],
        input_files=lambda w: config['convert'][w.alias]['inputs']
    container: CONTAINER
    shell:
        'mavis convert --file_type {params.file_type}'
            + ' --strand_specific {params.strand_specific}'
            + ' --assume_no_untemplated {params.assume_no_untemplated}'
            + ' --inputs {params.input_files}'
            + ' --outputfile {output}'
            + ' &> {log}'


checkpoint cluster:
    input: files=get_cluster_inputs,
        config=rules.init_config.output
    output: directory(output_dir('{library}/cluster'))
    log: output_dir('snakemake.cluster.{library}.log.txt')
    container: CONTAINER
    shell:
        'mavis cluster --config {input.config}'
            + ' --library {wildcards.library}'
            + ' --inputs {input.files}'
            + ' --output {output}'
            + ' &> {log}'


if 'validate' not in config.get('skip_stage'):
    rule validate:
        input: output_dir('{library}/cluster/batch-{job_id}.tab')
        params:
            dirname=lambda w: output_dir(f'{w.library}/validate/batch-{w.job_id}')
        output: output_dir('{library}/validate/batch-{job_id}/validation-passed.tab')
        log: output_dir('{library}/validate/snakemake.batch-{job_id}.log.txt')
        shell:
            'mavis validate --config {rules.init_config.output}'
                + ' --library {wildcards.library}'
                + ' --inputs {input}'
                + ' --output {params.dirname}'
                + ' &> {log}'


rule annotate:
    input: output_dir('{library}/validate/batch-{job_id}/validation-passed.tab')
    output: stamp=output_dir('{library}/annotate/batch-{job_id}/MAVIS.COMPLETE'),
        result=output_dir('{library}/annotate/batch-{job_id}/annotations.tab')
    log: output_dir('{library}/annotate/snakemake.batch-{job_id}.log.txt')
    shell:
        'mavis annotate --config {rules.init_config.output}'
            + ' --library {wildcards.library}'
            + ' --inputs {input}'
            + ' --output ' + output_dir('{wildcards.library}/annotate/batch-{wildcards.job_id}')
            + ' &> {log}'


def get_pairing_inputs(wildcards):
    for library in libraries:
        checkpoint_output = checkpoints.cluster.get(library=library).output[0]
        inputs = []
        for library in libraries:
            batch = os.path.join(checkpoint_output, 'batch-{job_id}.tab')
            inputs.extend(expand(
                rules.annotate.output.result,
                library=library,
                job_id=glob_wildcards(batch).job_id
            ))
    return inputs


rule pairing:
    input: get_pairing_inputs
    output: stamp=output_dir('pairing/MAVIS.COMPLETE'),
        result=output_dir('pairing/mavis_paired.tab')
    params:
        dirname=output_dir('pairing')
    shell:
        'mavis pairing --config {rules.init_config.output}'
            + ' --inputs {input}'
            + ' --output {params.dirname}'
            + ' &> ' + output_dir('snakemake.pairing.log.txt')

rule summary:
    input: rules.pairing.output.result,
    output: stamp=output_dir('summary/MAVIS.COMPLETE')
    params:
        dirname=output_dir('summary')
    shell:
        'mavis summary --config {rules.init_config.output}'
            + ' --inputs {input}'
            + ' --output {params.dirname}'
            + ' &> ' + output_dir('snakemake.summary.log.txt')
