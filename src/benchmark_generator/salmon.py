"""Input and job-script generation for SALMON benchmarks."""

JOB_SCRIPT_TEMPLATE = """#!/bin/sh
#PJM -L  "node={node}"
#PJM -L  "rscgrp={rscgrp}"
#PJM -L  "elapse={elapse}"
#PJM --mpi "max-proc-per-node={max_proc_per_node}"
#PJM -g {group}
#PJM -s

source /vol0004/apps/oss/spack/share/spack/setup-env.sh
spack load salmon-tddft@2.2.0
export OMP_NUM_THREADS={omp_num_threads}

mpiexec -stdin {sys_name}.nml salmon
mv data_for_restart restart
mpiexec -stdin {sys_name}-tddft.nml salmon

# copy output needed on Fugaku because we can't redirect
cp "output.$PJM_JOBID"/0/1/stdout.1.0 {sys_name}.gs.out
cp "output.$PJM_JOBID"/0/2/stdout.2.0 {sys_name}.td.out
"""


def create_input(atoms, base, size, tddft=False, spacing=0.33 / 1.88973):
    """
    Create an input file for Salmon based on an ASE Atoms structure and a
    base input template.

    Parameters:
    atoms (Atoms): ASE Atoms object representing the unit cell.
    base (dict): Base input dictionary.
    size (list): Size of the supercell in the form [nx, ny, nz].
    tddft (bool): Whether to use TDDFT settings in the input.
    spacing (float): Grid spacing for the rgrid.

    Returns:
    str: The generated input file content in NML format.
    """
    from f90nml import write
    from math import ceil

    # Replicate the unit cell
    atoms = atoms.repeat(size)
    n_atoms = len(atoms)
    n_electrons = 0
    for at in atoms:
        if at.symbol == "Si":
            n_electrons += 4
        else:
            n_electrons += 6

    # Generate copy of the base input
    inp = base.copy()
    inp["control"]["sysname"] = f"SiO2-{size[0]}x{size[1]}x{size[2]}"

    # Number of Atoms, etc
    inp["system"]["natom"] = n_atoms
    inp["system"]["nelec"] = n_electrons
    inp["system"]["nelem"] = 2
    inp["system"]["nstate"] = n_electrons * 3 // 4

    # Cell Dimension and Grid Spacing
    inp["system"]["al_vec1(1:3)"] = [atoms.cell[0, 0],
                                      atoms.cell[0, 1],
                                      atoms.cell[0, 2]]
    inp["system"]["al_vec2(1:3)"] = [atoms.cell[1, 0],
                                      atoms.cell[1, 1],
                                      atoms.cell[1, 2]]
    inp["system"]["al_vec3(1:3)"] = [atoms.cell[2, 0],
                                      atoms.cell[2, 1],
                                      atoms.cell[2, 2]]
    grid = [ceil(atoms.cell[0, 0] / spacing),
            ceil(atoms.cell[1, 1] / spacing),
            ceil(atoms.cell[2, 2] / spacing)]
    inp["rgrid"]["num_rgrid"] = grid

    # Geometry String
    reduced_positions = atoms.get_scaled_positions()
    symbols = atoms.get_chemical_symbols()
    atomic_red_coor = []
    for symbol, pos in zip(symbols, reduced_positions):
        el = 1 if symbol == "Si" else 2
        line = f"'{symbol}'\t{pos[0]:.6f}\t{pos[1]:.6f}\t{pos[2]:.6f}\t{el}"
        atomic_red_coor.append(line)

    # TDDFT Settings
    if tddft:
        inp["calculation"]["theory"] = "tddft_response"
        inp["emfield"] = {"ae_shape1": "impulse"}

    # Prepare the NML string
    from io import StringIO
    output = StringIO()
    write(inp, output)
    nml_str = output.getvalue()
    nml_str += "\n&atomic_red_coor\n    "
    nml_str += "\n    ".join(atomic_red_coor) + "\n/\n"

    return nml_str


def make_sio2():
    """
    Template base crystal structure of SiO2 from previous input files.

    Returns:
    Atoms: ASE Atoms object representing the SiO2 structure.
    """
    from ase import Atoms

    symbols = [
        'Si', 'Si', 'Si',
        'O', 'O', 'O', 'O', 'O', 'O',
        'Si', 'Si', 'Si',
        'O', 'O', 'O', 'O', 'O', 'O',
    ]

    frac_coords = [
        [0.9701, 0.5000, 0.0000],
        [0.2649, 0.7350, 0.6667],
        [0.2649, 0.2650, 0.3333],
        [0.7798, 0.6338, 0.1191],
        [0.5608, 0.7068, 0.5476],
        [0.1594, 0.5730, 0.7858],
        [0.1594, 0.4270, 0.2142],
        [0.5608, 0.2932, 0.4524],
        [0.7798, 0.3662, 0.8809],
        [0.4701, 0.0000, 0.0000],
        [0.7649, 0.2350, 0.6667],
        [0.7649, 0.7650, 0.3333],
        [0.2798, 0.1338, 0.1191],
        [0.0608, 0.2068, 0.5476],
        [0.6594, 0.0730, 0.7858],
        [0.6594, 0.9270, 0.2142],
        [0.0608, 0.7932, 0.4524],
        [0.2798, 0.8662, 0.8809],
    ]

    cell = [4.913357384280, 8.51018557085248, 5.40515497851379]

    atoms = Atoms(symbols=symbols,
                  scaled_positions=frac_coords,
                  cell=cell,
                  pbc=True)

    return atoms


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
    Create a Fugaku PJM job script that runs the SALMON ground-state and
    TDDFT calculations for the given input files.

    Parameters:
        sys_name (str): Common base name of the .nml files (without
            extension); expects `{sys_name}.nml` and `{sys_name}-tddft.nml`.
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
