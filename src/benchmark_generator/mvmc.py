"""Input and job-script generation for mVMC benchmarks."""

JOB_SCRIPT_TEMPLATE = """#!/bin/sh
#PJM -L  "node={node}"
#PJM -L  "rscgrp={rscgrp}"
#PJM -L  "elapse={elapse}"
#PJM --mpi "max-proc-per-node={max_proc_per_node}"
#PJM -g {group}
#PJM -s

source /vol0004/apps/oss/spack/share/spack/setup-env.sh
spack load mvmc@1.3.0%fj@4.12.0 arch=linux-rhel8-a64fx

export OMP_NUM_THREADS={omp_num_threads}

mpiexec vmc.out -s {sys_name}.inp
"""


def create_input(**kwargs):
    """
    Create an input file for mVMC using a template dictionary.
    Any keyword argument will update the default values.
    Mainly you should pass W and L.

    Parameters:
        **kwargs: Arbitrary keyword arguments to update the template.

    Returns:
        str: The formatted input string.
    """
    template = {
        "W": 10,
        "L": 10,
        "Wsub": 1,
        "Lsub": 1,
        "model": "FermionHubbard",
        "lattice": "Tetragonal",
        "t": 1.0,
        "U": 8.0,
        "ncond": 100,
        "NSROptItrStep": 1,
        "NVMCSample": 4000,
        "2Sz": 0,
    }
    # Update with user values
    template.update(kwargs)
    # Format as input string
    lines = [f"{key} = {value}" for key, value in template.items()]
    return "\n".join(lines)


def create_job_script(
    sys_name,
    node=12,
    rscgrp="small",
    elapse="00:30:00",
    max_proc_per_node=4,
    group="ra000009",
    omp_num_threads=12,
):
    """
    Create a Fugaku PJM job script that runs mVMC on the given input file.

    Parameters:
        sys_name (str): Base name of the .inp file (without extension).
        node (int): Number of compute nodes to request.
        rscgrp (str): Resource group to submit to.
        elapse (str): Wall-clock time limit.
        max_proc_per_node (int): MPI processes per node.
        group (str): Accounting group id.
        omp_num_threads (int): Number of OpenMP threads per process.

    Returns:
        str: The job script content.
    """
    return JOB_SCRIPT_TEMPLATE.format(
        node=node,
        rscgrp=rscgrp,
        elapse=elapse,
        max_proc_per_node=max_proc_per_node,
        group=group,
        omp_num_threads=omp_num_threads,
        sys_name=sys_name,
    )
