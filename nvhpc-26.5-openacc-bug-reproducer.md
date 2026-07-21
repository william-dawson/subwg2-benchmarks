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

Not yet attempted: bisecting which specific OpenACC-offloaded source
file/kernel changed behavior between NVHPC 26.4 and 26.5 (would need
either `compute-sanitizer` on the 26.5 build, or selectively rebuilding
individual translation units with each compiler version). SALMON's
OpenACC/CUDA GPU code lives under `src/`, particularly
`src/common/zpseudo.cu`, `src/common/stencil_current.cu`, and the
`_gpu`-suffixed subroutines in `src/gs/subspace_diagonalization.f90`
(the cuBLAS-backed subspace diagonalization path) are the most likely
candidates given they're the GPU-specific code paths exercised during
ground-state SCF.
