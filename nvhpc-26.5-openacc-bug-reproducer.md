# NVHPC 26.5 OpenACC codegen regression — minimal reproducer

## Summary

SALMON (real-time TDDFT code, https://github.com/SALMON-TDDFT/SALMON2)
built with `--arch=nvhpc-openacc` under **NVHPC 26.5** produces a
silently wrong, but fully self-consistent and deterministic, SCF
ground-state energy. Rebuilding the identical source tree with
**NVHPC 26.3** (same node, same GPU, nothing else changed) fixes it.

Confirmed on two different physical machines and two different GPU
architectures:

| Machine | GPU | NVHPC | Result |
|---|---|---|---|
| R-CCS Cloud `qc-gh200` | NVIDIA GH200 (Hopper, cc90) | 26.5 | **Wrong**: `-6112.12922835 eV` |
| Rikyu | NVIDIA GB200 (Blackwell) | 26.5 | **Wrong**: `-6112.12922835 eV` (bit-for-bit identical to the above) |
| Rikyu (same node/GPU as above) | NVIDIA GB200 (Blackwell) | 26.3 | **Correct**: `-6099.94333354 eV` |
| DGX Spark (`ng-dgx-m2`) | NVIDIA GB10 (Blackwell, cc121) | 26.3 (only version available) | **Correct**: `-6099.94333354 eV` |
| Local Mac / R-CCS Cloud `genoa` (CPU-only builds, no NVHPC involved) | — | — | **Correct**: `-6099.94333354 eV` |

The bug is deterministic and bit-for-bit reproducible across completely
different GPU architectures (Hopper vs. Blackwell) — it converges
cleanly through all 100 SCF iterations to a plausible-looking (just
wrong) number rather than diverging or producing NaNs. That pattern is
much more consistent with a specific OpenACC-offloaded routine being
miscompiled by `nvfortran` 26.5 than with a runtime/memory-safety issue
(a race condition or uninitialized buffer would be expected to produce
different wrong answers on different hardware/runs, not the same one).

## Reproduction steps

```sh
git clone https://github.com/SALMON-TDDFT/SALMON2.git
cd SALMON2
git checkout 0663c5d0209d91bb9ff7d4c22aeb42b2cbfd77e8   # commit used for this comparison

# Build A: NVHPC 26.5 (broken)
module load nvhpc/26.5
mkdir build_265 && cd build_265
python3 ../configure.py --arch=nvhpc-openacc --prefix="$(pwd)/install" -r
make -j$(nproc)
cd ..

# Build B: NVHPC 26.3 (correct)
module load nvhpc/26.3
mkdir build_263 && cd build_263
python3 ../configure.py --arch=nvhpc-openacc --prefix="$(pwd)/install" -r
make -j$(nproc)
cd ..
```

Run each binary against the minimal input below (single MPI rank = 1
GPU; needs `Si.psp8`/`O.psp8` pseudopotentials in the working directory
— pseudo-dojo ABINIT-format PSP8 files for Si and O, any recent
pseudo-dojo release works):

```sh
mpirun -n 1 build_265/salmon < Si-1-1-1.nml > gs_265.log
mpirun -n 1 build_263/salmon < Si-1-1-1.nml > gs_263.log
grep "iter=   100" gs_265.log gs_263.log
```

## Minimal input file (`Si-1-1-1.nml`)

18-atom amorphous-quartz-structure SiO2 unit cell, ground-state DFT only
(no TDDFT stage needed to reproduce — the bug is already present in the
ground-state SCF result).

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

## Notes on the missing piece

`method_init_wf = 'random'` means the SCF trajectory (and thus the exact
intermediate energies at early iterations) is sensitive to the initial
random seed — but both builds were run back-to-back on the same node
with the same binary invocation pattern and consistently converge to
their respective (correct/wrong) fixed points, so this doesn't explain
the discrepancy. The final converged **band gap** is identical between
correct and wrong runs (`5.71749793 eV` both times) — only the absolute
**Total Energy** differs, by exactly `12.18589481 eV`
(`-6099.94333354` → `-6112.12922835`), which may be a useful clue for
whoever bisects the actual routine (a fixed offset rather than a
diverging one suggests a single additive/omitted term rather than a
propagating numerical instability).

**Root cause found — see "Pinpointed" section below**: the discrepancy
is entirely in the Ewald ion-ion energy term, not in the Hamiltonian,
diagonalization, or SCF density-update code paths originally suspected
(`zpseudo.cu`, `stencil_current.cu`, `subspace_diagonalization.f90`
GPU path are all now cleared — see below for why).

## Ruled out: `-6112.13 eV` is not just a different (valid) local minimum

One legitimate alternative explanation for the discrepancy: SCF is a
nonlinear fixed-point iteration, so a different initial guess or
algorithm choice could in principle converge to a different, equally
valid, local minimum — in which case the "wrong" NVHPC 26.5 answer
wouldn't be a bug so much as a different (if unlucky) basin of
attraction.

This was tested directly on the trusted CPU (Homebrew/GCC, no NVHPC
involved) local macOS build, using the exact same input above and
varying only `&scf` settings, one axis at a time, all at fixed rank
count (`mpirun -n 4`, which fixes the domain-decomposition-derived
random seed baseline — see `iseed_number_change` below):

| `&scf` variant | Total Energy (eV) |
|---|---|
| baseline (`method_init_wf='random'`, Broyden mixing, subspace diag on) | `-6099.94333354` |
| `method_init_wf='gauss'` | `-6099.94333354` |
| `method_init_wf='gauss10'` | `-6099.94333354` |
| `yn_subspace_diagonalization='n'` | `-6099.61361133` |
| `method_mixing='simple'` | `-6099.94333354` |
| `method_mixing='pulay'` | `-6099.94333354` |
| `iseed_number_change=1000` (different random seed) | `-6099.94333354` |
| `iseed_number_change=5000` (different random seed) | `-6099.94333354` |

Seven of eight variants — including two different random seeds and two
different deterministic (Gaussian) initial guesses — converge to
*exactly* the same energy to 8 decimal places. The lone outlier
(subspace diagonalization disabled) differs by only `0.33 eV`, most
plausibly from orbital reordering near-degeneracies settling slightly
differently, not a distinct basin. None of these get anywhere close to
`-6112.13 eV` (12.19 eV away — ~37x larger than the biggest deviation
any legitimate algorithm variant produced).

**Conclusion**: `-6099.94 eV` is a robust, essentially unique SCF fixed
point for this system, reachable from a wide variety of starting points
and algorithms. `-6112.13 eV` is not a nearby alternative basin that a
different (but still correct) SCF path could plausibly land in — it's
outside the range that legitimate algorithmic variation produces on
known-correct hardware. This corroborates, rather than undermines, the
NVHPC 26.5 compiler-regression conclusion above.

## Pinpointed: the bug is entirely in the Ewald ion-ion energy term

Two further pieces of evidence isolate the bug to one specific term.

**1. The full single-particle eigenvalue spectrum is bit-identical
between builds.** Every SCF iteration's `iter=100` report prints all 72
Kohn-Sham eigenvalues. Comparing the correct build's spectrum against
the `nvhpc/26.5` buggy build's spectrum, all 60 occupied/low-lying
states match to the printed precision (`diff=0.0000`), and even the
highest, least-converged empty conduction states differ by at most
`0.19 eV` — consistent with ordinary numerical noise between different
hardware/convergence paths, not a systematic error. This means the
Hamiltonian construction, pseudopotential application, and
diagonalization — the code paths originally suspected
(`zpseudo.cu`, `stencil_current.cu`, the GPU subspace-diagonalization
path) — are all computing correctly on both builds. The bug cannot be
there.

**2. `total_energy.f90` already has (commented-out) instrumentation for
exactly this.** `SUBROUTINE calc_Total_Energy_periodic` sums six
components into `energy%E_tot`:

```fortran
energy%E_tot = energy%E_kin + energy%E_h + energy%E_ion_loc &
             + energy%E_ion_nloc + energy%E_xc + energy%E_ion_ion
```

immediately followed by a commented-out debug print of all six terms
(`total_energy.f90` around line 503). Uncommenting it (and adding
`use parallelization, only: nproc_id_global`, needed for the print's
`comm_is_root` call but not otherwise imported in this subroutine) and
rebuilding both the correct (local macOS) and buggy (Rikyu
`nvhpc/26.5`) binaries gives the converged (iteration-100) breakdown,
in Hartree:

| Component | Correct build | `nvhpc/26.5` (buggy) | Diff (eV) |
|---|---|---|---|
| `E_kin` | ≈0 (`-1.5e-14`) | ≈0 (`-3.9e-15`) | ~0 |
| `E_h` | `76.59949396424075` | `76.59949396424253` | ~0 |
| `E_ion_loc` | `-218.65215737427528` | `-218.6521573742779` | ~0 |
| `E_ion_nloc` | `116.58824916576496` | `116.5882491657627` | ~0 |
| `E_xc` | `-59.71519942023457` | `-59.71519942023502` | ~0 |
| **`E_ion_ion`** | **`-138.98917900557780`** | **`-139.4370023994977`** | **`-12.1859`** |
| `E_tot` (sum) | `-224.16879267008193` | `-224.6166160640055` | `-12.1859` |

Every term agrees to ~`1e-12` Hartree (floating-point noise) **except
`E_ion_ion`**, which alone accounts for the entire `-12.1859 eV`
discrepancy in `E_tot` to 6 significant figures.

**This makes sense of every other observation in this document**:
`E_ion_ion` (the classical Ewald electrostatic ion-ion energy) depends
*only* on ion positions and species — it's computed once from static
geometry, entirely independent of the electron density, wavefunctions,
or SCF trajectory. That's exactly why the bug is bit-for-bit
deterministic regardless of random seed, MPI rank count, or GPU
architecture (Hopper vs. Blackwell): there's no stochastic or
data-dependent element in this calculation at all, just a fixed
numeric error baked into that one code path's binary.

**Where to look next**: `src/common/total_energy.f90`, inside
`SUBROUTINE calc_Total_Energy_periodic`, the real-space Ewald pair-sum
block (`!$acc kernels copyin(ewald)` / `!$acc loop private(...)
reduction(+:E_tmp)`, roughly lines 327-360) is the direct computation of
`E_ion_ion`. There's also a second Ewald-related OpenACC block in
`init_ewald` (lines ~840-940, pair-list construction) that feeds data
into this sum — worth checking too, since a subtly wrong pair list
(e.g., an off-by-one in the periodic-image cutoff loop) would silently
under/over-count image contributions and produce exactly this kind of
fixed additive error. Reduction-clause codegen bugs combined with
`private`/loop-bound edge cases in nested periodic-image loops are a
plausible fit for what changed in NVHPC 26.5's OpenACC compiler.
