"""CLI for generating mVMC and SALMON benchmark inputs on Fugaku-like systems."""

import shutil
from pathlib import Path

import typer

from benchmark_generator import fom as fom_lib
from benchmark_generator import mvmc as mvmc_lib
from benchmark_generator import salmon as salmon_lib

# src/benchmark_generator/cli.py -> repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data"

app = typer.Typer(no_args_is_help=True, add_completion=False)
mvmc_app = typer.Typer(no_args_is_help=True, help="Generate mVMC benchmark inputs.")
salmon_app = typer.Typer(no_args_is_help=True, help="Generate SALMON benchmark inputs.")
fom_app = typer.Typer(no_args_is_help=True, help="Compute figures of merit from run output.")
app.add_typer(mvmc_app, name="mvmc")
app.add_typer(salmon_app, name="salmon")
app.add_typer(fom_app, name="fom")


@mvmc_app.command("create")
def mvmc_create(
    w: int = typer.Option(10, "--w", help="Lattice width."),
    l: int = typer.Option(10, "--l", help="Lattice length."),
    wsub: int = typer.Option(1, "--wsub", help="Sublattice width."),
    lsub: int = typer.Option(1, "--lsub", help="Sublattice length."),
    model: str = typer.Option("FermionHubbard", help="mVMC model."),
    lattice: str = typer.Option("Tetragonal", help="mVMC lattice type."),
    t: float = typer.Option(1.0, help="Hopping parameter t."),
    u: float = typer.Option(8.0, "--u", help="On-site interaction U."),
    nsr_opt_itr_step: int = typer.Option(1, help="Number of SR optimization steps."),
    nvmc_sample: int = typer.Option(4000, help="Number of VMC samples."),
    sz2: int = typer.Option(0, "--2sz", help="Total 2*Sz."),
    output_dir: Path = typer.Option(Path("output"), help="Directory to write files into."),
    node: int = typer.Option(12, help="Number of compute nodes for the job script."),
    rscgrp: str = typer.Option("small", help="PJM resource group."),
    elapse: str = typer.Option("00:30:00", help="PJM wall-clock time limit."),
    max_proc_per_node: int = typer.Option(4, help="MPI processes per node."),
    group: str = typer.Option("ra000009", help="PJM accounting group id."),
    omp_num_threads: int = typer.Option(12, help="OpenMP threads per process."),
):
    """Write an mVMC .inp file and a matching Fugaku job script."""
    output_dir.mkdir(parents=True, exist_ok=True)

    sys_name = f"mVMC-{w}-{l}"
    inp = mvmc_lib.create_input(
        W=w,
        L=l,
        Wsub=wsub,
        Lsub=lsub,
        model=model,
        lattice=lattice,
        t=t,
        U=u,
        NSROptItrStep=nsr_opt_itr_step,
        NVMCSample=nvmc_sample,
        **{"2Sz": sz2},
    )
    inp_path = output_dir / f"{sys_name}.inp"
    inp_path.write_text(inp)

    job_script = mvmc_lib.create_job_script(
        sys_name,
        node=node,
        rscgrp=rscgrp,
        elapse=elapse,
        max_proc_per_node=max_proc_per_node,
        group=group,
        omp_num_threads=omp_num_threads,
    )
    sh_path = output_dir / f"{sys_name}.sh"
    sh_path.write_text(job_script)

    typer.echo(f"Wrote {inp_path}")
    typer.echo(f"Wrote {sh_path}")


@salmon_app.command("create")
def salmon_create(
    nx: int = typer.Option(1, help="Supercell repeats along x."),
    ny: int = typer.Option(1, help="Supercell repeats along y."),
    nz: int = typer.Option(1, help="Supercell repeats along z."),
    spacing: float = typer.Option(0.33 / 1.88973, help="Grid spacing (bohr)."),
    base: Path = typer.Option(
        DEFAULT_DATA_DIR / "base.nml", help="Base SALMON &namelist template."
    ),
    pseudo_dir: Path = typer.Option(
        DEFAULT_DATA_DIR, help="Directory containing Si.psp8 and O.psp8."
    ),
    output_dir: Path = typer.Option(Path("output"), help="Directory to write files into."),
    node: int = typer.Option(12, help="Number of compute nodes for the job script."),
    rscgrp: str = typer.Option("small", help="PJM resource group."),
    elapse: str = typer.Option("00:30:00", help="PJM wall-clock time limit."),
    max_proc_per_node: int = typer.Option(4, help="MPI processes per node."),
    group: str = typer.Option("ra000009", help="PJM accounting group id."),
    omp_num_threads: int = typer.Option(12, help="OpenMP threads per process."),
):
    """Write SALMON ground-state + TDDFT .nml files and a matching Fugaku job script."""
    from f90nml import read

    output_dir.mkdir(parents=True, exist_ok=True)
    size = [nx, ny, nz]

    atoms = salmon_lib.make_sio2()
    base_inp = read(base)

    dft = salmon_lib.create_input(atoms, base_inp, size, tddft=False, spacing=spacing)
    tddft = salmon_lib.create_input(atoms, base_inp, size, tddft=True, spacing=spacing)

    sys_name = f"Si-{nx}-{ny}-{nz}"
    dft_path = output_dir / f"{sys_name}.nml"
    tddft_path = output_dir / f"{sys_name}-tddft.nml"
    dft_path.write_text(dft)
    tddft_path.write_text(tddft)

    for psp in ("Si.psp8", "O.psp8"):
        shutil.copy(pseudo_dir / psp, output_dir / psp)

    job_script = salmon_lib.create_job_script(
        sys_name,
        node=node,
        rscgrp=rscgrp,
        elapse=elapse,
        max_proc_per_node=max_proc_per_node,
        group=group,
        omp_num_threads=omp_num_threads,
    )
    sh_path = output_dir / f"{sys_name}.sh"
    sh_path.write_text(job_script)

    typer.echo(f"Wrote {dft_path}")
    typer.echo(f"Wrote {tddft_path}")
    typer.echo(f"Wrote {output_dir / 'Si.psp8'}")
    typer.echo(f"Wrote {output_dir / 'O.psp8'}")
    typer.echo(f"Wrote {sh_path}")


@fom_app.command("mvmc")
def fom_mvmc(
    infile: Path = typer.Argument(..., help="mVMC .inp file."),
    timing_file: Path = typer.Argument(..., help="mVMC timing file (zvo_CalcTimer.dat)."),
):
    """Print the figure of merit for a completed mVMC run."""
    typer.echo(fom_lib.mvmc_fom(infile, timing_file))


@fom_app.command("salmon")
def fom_salmon(
    infile: Path = typer.Argument(..., help="SALMON ground-state .nml file."),
    gs_output: Path = typer.Argument(..., help="Ground-state calculation output."),
    td_output: Path = typer.Argument(..., help="TDDFT calculation output."),
):
    """Print the figure of merit for a completed SALMON run."""
    typer.echo(fom_lib.salmon_fom(infile, gs_output, td_output))


def main():
    app()


if __name__ == "__main__":
    main()
