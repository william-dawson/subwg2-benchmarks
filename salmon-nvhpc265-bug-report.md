## Summary

SALMON's `nvhpc-openacc` GPU build produces a silently wrong, but fully
self-consistent and deterministic, ground-state total energy when
compiled with **NVIDIA HPC SDK 26.5** (`nvhpc/26.5`). The identical
source tree, rebuilt with **NVIDIA HPC SDK 26.3** and nothing else
changed, gives the correct answer. No crash, no NaN, no warning at
build or run time — the run converges cleanly through all 100 SCF
iterations to a plausible-looking, but incorrect, total energy.

- **Correct** (NVHPC 26.3, and every CPU build we tested): `Total Energy = -6099.94333354 eV`
- **Wrong** (NVHPC 26.5): `Total Energy = -6112.12922835 eV`
- Difference: exactly `12.18589481 eV`, reproduced bit-for-bit across
  two different GPU architectures (NVIDIA GH200/Hopper and
  NVIDIA GB200/Blackwell).

## Environment / build

- Commit: `0663c5d0209d91bb9ff7d4c22aeb42b2cbfd77e8` (branch `develop-2.0.0`)
- Compiler: NVIDIA HPC SDK **26.5** (`module load nvhpc/26.5`)
- Configure/build:
  ```sh
  mkdir build_gpu && cd build_gpu
  python3 ../configure.py --arch=nvhpc-openacc --prefix="$(pwd)/install" -r
  make -j
  ```
- CMake preset used: `platforms/nvhpc-openacc.cmake`, i.e.
  `-acc=strict -gpu=cc80,cc90,cc100,cc120,managed,ptxinfo -cudalib=cublas,cusolver -cuda -Minfo=accel -DUSE_OPENACC`
- Run: single MPI rank, single GPU (`mpirun -n 1 ./salmon < Si-1-1-1.nml`)
- Confirmed on two machines/architectures: an NVIDIA GH200 (Hopper,
  cc90) node and an NVIDIA GB200 (Blackwell) node — identical wrong
  answer on both. 

## Reproduction

Ground-state DFT (`theory='dft'`). 18-atom amorphous-quartz-structure SiO2
unit cell, needs `Si.psp8`/`O.psp8` pseudo-dojo ABINIT-format
pseudopotentials in the working directory (any recent pseudo-dojo
release works).

```sh
mpirun -n 1 ./salmon < Si-1-1-1.nml > gs.log
grep "iter=   100" gs.log
```

`Si-1-1-1.nml`:

```
&calculation
    theory = 'dft'
/

&control
    sysname = 'SiO2-1x1x1'
/

&parallel
/

&rgrid
    num_rgrid = 29, 49, 31
/

&units
    unit_system = 'A_eV_fs'
/

&system
    yn_periodic = 'y'
    natom = 18
    nelec = 96
    nelem = 2
    nstate = 72
    al_vec1(1:3) = 4.91335738428, 0.0, 0.0
    al_vec2(1:3) = 0.0, 8.51018557085248, 0.0
    al_vec3(1:3) = 0.0, 0.0, 5.40515497851379
/

&pseudo
    izatom(1:2) = 14, 8
    file_pseudo(1:2) = './Si.psp8', './O.psp8'
    lloc_ps(1:2) = 4, 4
/

&functional
    xc = 'PZ'
/

&scf
    method_init_wf = 'random'
    ncg = 5
    nscf = 100
    threshold = -1
    alpha_mb = 0.3
/

&tgrid
    nt = 6000
    dt = 0.0005
/

&atomic_red_coor
    'Si'	0.970100	0.500000	0.000000	1
    'Si'	0.264900	0.735000	0.666700	1
    'Si'	0.264900	0.265000	0.333300	1
    'O'	0.779800	0.633800	0.119100	2
    'O'	0.560800	0.706800	0.547600	2
    'O'	0.159400	0.573000	0.785800	2
    'O'	0.159400	0.427000	0.214200	2
    'O'	0.560800	0.293200	0.452400	2
    'O'	0.779800	0.366200	0.880900	2
    'Si'	0.470100	0.000000	0.000000	1
    'Si'	0.764900	0.235000	0.666700	1
    'Si'	0.764900	0.765000	0.333300	1
    'O'	0.279800	0.133800	0.119100	2
    'O'	0.060800	0.206800	0.547600	2
    'O'	0.659400	0.073000	0.785800	2
    'O'	0.659400	0.927000	0.214200	2
    'O'	0.060800	0.793200	0.452400	2
    'O'	0.279800	0.866200	0.880900	2
/
```

## Where we believe the bug is

Comparing the full single-particle Kohn-Sham eigenvalue spectrum
between the correct and wrong runs, all 72 eigenvalues match to
within ordinary numerical noise — the Hamiltonian, pseudopotential
application, and diagonalization are all computing correctly. Breaking
`Total Energy` down into its components (`E_kin`, `E_h`, `E_ion_loc`,
`E_ion_nloc`, `E_xc`, `E_ion_ion`), every term matches the correct
build except **`E_ion_ion`** (the Ewald ion-ion electrostatic energy),
which alone accounts for the full `12.19 eV` discrepancy.

That points at `src/common/total_energy.f90`, subroutine `init_ewald`
(the real-space Ewald pair-list bookkeeping — a max-reduction over a
small, `nion`-sized loop, and the loop that populates
`ewald%bk`/`ewald%npair_bk`) and the real-space Ewald summation in
`SUBROUTINE calc_Total_Energy_periodic` that consumes that pair list.
These are all small (~18-iteration outer loop) `!$acc kernels`/`!$acc
serial` regions with scalar reduction/accumulation into a variable
declared outside the region. We were not able to isolate a
minimal, SALMON-independent reproducer of the underlying compiler
behavior — small standalone Fortran+OpenACC programs mimicking the
same loop shape and reduction pattern compile and run correctly under
`nvhpc/26.5`, so whatever triggers this appears to depend on some
aspect of SALMON's fuller build/runtime context that we haven't
isolated.
