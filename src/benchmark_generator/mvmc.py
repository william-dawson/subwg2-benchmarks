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


# Models with no itinerant-electron sector: StdFace hard-errors
# (StdFace_exit) if ncond/nelec is specified for these.
_SPIN_ONLY_MODELS = {"spin", "spingc", "spingcboost"}


def create_input(**kwargs):
    """
    Create an input file for mVMC using a template dictionary.
    Any keyword argument will update the default values.
    Mainly you should pass W and L.

    Electron filling is always fixed at half filling (ncond = W*L, rounded
    down to an even number) for itinerant-electron models -- this is not
    overridable, so the linear-algebra problem size (Nsize = ncond) always
    scales predictably with the lattice, and the FOM formula in fom.py can
    derive it from W*L alone. ncond is omitted entirely for Spin-family
    models, which don't have an itinerant-electron sector and error out if
    it's specified at all.

    Parameters:
        **kwargs: Arbitrary keyword arguments to update the template.
            ncond may not be passed; pass a different W/L to change filling.

    Returns:
        str: The formatted input string.
    """
    if "ncond" in kwargs:
        raise TypeError(
            "ncond is not configurable: filling is fixed at half filling "
            "(ncond = W*L, rounded down to even). Change W/L instead."
        )

    W = kwargs.get("W", 10)
    L = kwargs.get("L", 10)
    model = kwargs.get("model", "FermionHubbard")
    nsite = W * L
    half_filling_ncond = nsite - (nsite % 2)

    template = {
        "W": 10,
        "L": 10,
        "Wsub": 1,
        "Lsub": 1,
        "model": "FermionHubbard",
        "lattice": "Tetragonal",
        "t": 1.0,
        "U": 8.0,
        "ncond": half_filling_ncond,
        "NSROptItrStep": 1,
        "NVMCSample": 4000,
        "2Sz": 0,
    }
    if model.lower() in _SPIN_ONLY_MODELS:
        del template["ncond"]
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
