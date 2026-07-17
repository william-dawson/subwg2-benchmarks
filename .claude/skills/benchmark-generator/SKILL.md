---
name: benchmark-generator
description: Generate mVMC and SALMON benchmark inputs (input files, PJM job scripts) and compute figures of merit from completed runs, using the benchgen CLI in this repo. Use whenever the user asks to create/generate an mVMC or SALMON benchmark case, a Fugaku job script for one, or a figure of merit (FOM) from mVMC/SALMON run output.
---

# Benchmark Generator

This repo is a `uv`-managed Python project with a CLI, `benchgen`, that
generates benchmark inputs for the mVMC and SALMON codes (and computes a
figure of merit from their output). There is no need to write ad-hoc Python
or notebooks for this — always drive it through the CLI.

This skill covers CLI mechanics only — flags, defaults, what gets written
where. For what the physics/algorithm parameters actually mean, what
realistic values look like, or why a default was chosen, see the
**mvmc-reference** skill instead of guessing here.

Run everything with `uv run`, from the repo root (the directory containing
`pyproject.toml`). `uv run` will create the virtualenv and install
dependencies (`ase`, `f90nml`, `typer`) automatically on first use — no
separate install step is needed.

```
uv run benchgen --help
```

## Generating an mVMC case

```
uv run benchgen mvmc create --w 18 --l 18
```

Writes `output/mVMC-{w}-{l}.inp` and `output/mVMC-{w}-{l}.sh` (a PJM job
script that runs `vmc.out` on Fugaku). Key options: `--w`/`--l` (lattice
size), `--wsub`/`--lsub` (sublattice size), `--u` (interaction strength),
`--t` (hopping), `--nvmc-sample`. Job-script options (`--node`, `--rscgrp`,
`--elapse`, `--group`, `--omp-num-threads`, `--max-proc-per-node`) control
the PJM directives — `--group` in particular is a project accounting code
the user will usually need to supply. Run `uv run benchgen mvmc create
--help` for the full list and defaults.

There is **no `--ncond`/`--nelec` option** — electron filling is always
fixed at half filling internally, scaled automatically from `--w`/`--l`;
it's not user-configurable (see mvmc-reference for why).

## Generating a SALMON case

```
uv run benchgen salmon create --nx 2 --ny 2 --nz 2
```

Builds a `size = [nx, ny, nz]` supercell of the built-in SiO2 structure,
and writes to `output/`:
- `Si-{nx}-{ny}-{nz}.nml` — ground-state DFT input
- `Si-{nx}-{ny}-{nz}-tddft.nml` — TDDFT input (impulse excitation)
- `Si.psp8`, `O.psp8` — pseudopotentials (copied from `data/`)
- `Si-{nx}-{ny}-{nz}.sh` — PJM job script that runs the DFT step, then the
  TDDFT step, on Fugaku

The base namelist template is `data/base.nml`; pass `--base` to use a
different one. Same job-script options as the mVMC command apply
(`--node`, `--rscgrp`, `--elapse`, `--group`, etc.) — again `--group` is a
project accounting code the user will usually need to supply.
Run `uv run benchgen salmon create --help` for the full list and defaults.

## Computing a figure of merit

After a job has actually run (on a cluster, not locally), compute its FOM
from the output files it produced:

```
uv run benchgen fom mvmc output/mVMC-18-18.inp path/to/zvo_CalcTimer.dat
uv run benchgen fom salmon output/Si-1-1-1.nml path/to/Si-1-1-1.gs.out path/to/Si-1-1-1.td.out
```

Each prints a single float to stdout: time-to-solution divided by the
problem's expected scaling cost (see `src/benchmark_generator/fom.py` for
the exact formulas if asked to explain the metric).

## Notes

- Output defaults to `output/` in the repo root; pass `--output-dir` to
  write elsewhere. Running the create commands repeatedly overwrites files
  of the same name (same size parameters), which is expected when a user
  is iterating on job-script settings.
- Don't hand-edit generated `.inp`/`.nml`/`.sh` files unless the user
  specifically asks — regenerate via the CLI with different options instead,
  so the input stays reproducible.
