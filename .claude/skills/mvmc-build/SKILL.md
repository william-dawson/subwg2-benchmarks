---
name: mvmc-build
description: Build mVMC (https://github.com/issp-center-dev/mVMC) from source, on the R-CCS Cloud DGX Spark partition (ng-dgx-m[0-3]), the R-CCS Cloud fx700 (Fujitsu A64FX) partition, or locally on macOS via Homebrew. Use whenever the user asks to build, compile, or install mVMC on any of these targets.
---

# Building mVMC

Build mechanics only. For what the code does or how its input/output
files work, see the **mvmc-reference** skill. For generating benchmark
`.inp` files, see **benchmark-generator**. For the empirical
largest-problem-size-per-machine methodology and recorded results, see
**mvmc-benchmarking**.

Both recipes below are independently verified (built, ran, produced
correct output matching `fom`'s expected `zvo_CalcTimer.dat` format) as of
this writing. Both need `--recursive` on the clone — mVMC pulls in
StdFace, blis, and pfapack as git submodules.

```sh
git clone --recursive https://github.com/issp-center-dev/mVMC.git
```

## R-CCS Cloud, DGX Spark (`ng-dgx-m0`-`ng-dgx-m3`)

Pure CPU code — DGX Spark was chosen for queue availability, not GPU need
(see the `rccs-cloud-submitting-jobs` skill for partition/job-submission
mechanics). Grace CPU, aarch64, Ubuntu, 20 cores (10 Cortex-X925 + 10
Cortex-A725) / 121GB per node.

```sh
module load system/ng-dgx nvhpc
cd mVMC && mkdir build && cd build
cmake -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++ -DCMAKE_Fortran_COMPILER=gfortran \
      -DUSE_GEMMT=OFF -DCMAKE_BUILD_TYPE=Release ..
make -j$(nproc)
```

Non-obvious points, in order of how much they'll bite you:

- **Use plain GCC, not NVHPC's `nvc`/`nvc++`/`nvfortran`** (which the
  loaded `nvhpc` module would otherwise put first on `PATH` / in
  `CC`/`CXX`/`FC`), even though you still need the `nvhpc` module loaded
  for MPI. Building with NVHPC's compilers caused a **catastrophic OpenMP
  regression** (2 threads ran 54% slower than 1; 20 threads ran ~70x
  slower) — root cause: the resulting binary mixed NVHPC's own OpenMP
  runtime with NVPL's `_gomp`-suffixed (GNU-OpenMP-ABI) BLAS/LAPACK
  libraries, giving the process two uncoordinated thread pools fighting
  over the same cores. Building with real `gcc`/`g++`/`gfortran` instead
  (still under the `nvhpc` module, which is what makes MPI and the NVPL
  libraries discoverable) eliminates the conflict — confirmed via `ldd`
  showing only one `libgomp.so.1` in the dependency tree afterward.
- **`-DUSE_GEMMT=OFF` is required.** mVMC's default (`ON`) downloads a
  prebuilt BLIS binary — for Cortex-A57, a much older/weaker core than
  this node's actual Cortex-X925/A725. With it off, CMake's normal
  `find_package(BLAS)`/`find_package(LAPACK)` picks up NVHPC's
  `libblas.so`/`liblapack.so`, which are themselves symlinks to
  `libnvpl_blas_lp64_gomp.so`/`libnvpl_lapack_lp64_gomp.so` — NVIDIA's own
  Grace-tuned, GNU-OpenMP-ABI-matched math libraries. Don't pass
  `-DBLAS_LIBRARIES=.../libnvpl_blas_lp64_gomp.so` explicitly instead of
  letting this auto-detect — that was tried and produced link failures
  (`DSO missing from command line`) on some targets (`UHF`, `greenr2k`)
  whose CMakeLists don't consistently pick up a forced cache variable.
- **Don't use `-DCONFIG=gcc`** (one of mVMC's own CMake presets) — it
  forces plain `gcc`/`gfortran` via `CACHE ... FORCE`, which is fine on
  its own, but wasn't the combination actually tested here; the explicit
  `-DCMAKE_*_COMPILER` flags above are what's verified working.
- **Running: use `mpirun`, never `srun`.** This node's bundled OpenMPI
  (under the `nvhpc` module, via `comm_libs/mpi`) was not built with Slurm
  PMI/PMIx support — `srun ./vmc.out` fails immediately ("OMPI was not
  built with SLURM's PMI support"). `mpirun -n <ranks> ./vmc.out -s
  input.inp` works with no extra environment variables needed (an earlier
  `OPAL_PREFIX` workaround for a help-text warning turned out to be
  unnecessary once `mpirun` is used instead of `srun` — the warning and
  the PMI failure are separate issues, only the latter is fatal).
- Binaries land at `build/src/mVMC/vmc.out`, `build/src/mVMC/vmcdry.out`,
  `build/src/ComplexUHF/UHF`.

## R-CCS Cloud, fx700 (Fujitsu A64FX)

Fujitsu A64FX, aarch64, Rocky Linux, 48 cores, InfiniBand EDR, 32GB/node.
Build **natively on an `fx700` node itself** — the docs describe `r340` as
"the cross-compilation environment for fx700", but as of this writing the
Fujitsu toolchain (`FJSVstclanga` module) isn't actually present on `r340`
(the module loads with no error, but the directory it points at doesn't
exist there); it *is* present and working directly on `fx700` nodes, which
have plenty of cores to self-host a build. Worth rechecking if `r340`
ever gets the toolchain installed, since native aarch64 compiles are
slower per-object than x86_64 cross-compiling would be.

```sh
module load system/fx700 FJSVstclanga
cd mVMC && mkdir build && cd build
cmake -DCMAKE_C_COMPILER=mpifcc -DCMAKE_CXX_COMPILER=mpiFCC -DCMAKE_Fortran_COMPILER=mpifrt \
      -DCMAKE_C_FLAGS_RELEASE='-Kfast,parallel -Kmemalias,alias_const' \
      -DCMAKE_Fortran_FLAGS_RELEASE='-DFUJITSU -Kfast,parallel' \
      -DOpenMP_C_FLAGS='-Kopenmp' \
      -DCMAKE_EXE_LINKER_FLAGS='-Kopenmp -Kparallel' \
      -DBLAS_LIBRARIES='-SSL2' -DLAPACK_LIBRARIES='-SSL2' \
      -DUSE_GEMMT=OFF -DCMAKE_BUILD_TYPE=Release ..
make -j$(nproc)
```

- **Compiler names have no `px` suffix here.** mVMC's own `config/fujitsu.cmake`
  and `config/fugaku.cmake` presets use `mpifccpx`/`mpiFCCpx`/`mpifrtpx` —
  that `px` suffix is the Fugaku/K-computer cross-compile naming
  convention (build on an x86_64 front-end, target the A64FX compute
  nodes). Since we're compiling natively on an A64FX node here, the real
  binaries are `mpifcc`/`mpiFCC`/`mpifrt` (no suffix). Don't use either
  preset directly — the explicit flags above adapt `fujitsu.cmake`'s
  settings to the native names, which is what's verified working.
- **`-Kparallel` must be passed at link time too, not just compile time**,
  or the final link of `vmc.out` fails outright: `FCC: fatal: -Kparallel
  option is not specified at linking of object files to which -Kparallel
  applied at compiling.` `fujitsu.cmake` itself only sets `-Kopenmp` on
  `CMAKE_EXE_LINKER_FLAGS`, missing this — add `-Kparallel` there too.
- **`-DUSE_GEMMT=OFF`** avoids the same default-BLIS-download issue as the
  other two platforms, in favor of `-SSL2` (Fujitsu's own vendor BLAS/LAPACK,
  correctly tuned for A64FX) — chosen for consistency with the other two
  recipes, not because it was compared against the alternative. Unlike DGX
  Spark, mVMC's own `fugaku.cmake` preset shows a *correctly*
  microarchitecture-tuned BLIS artifact exists for this hardware
  (`BLIS_ARTIFACT_CONFIG=a64fx`) — `USE_GEMMT=ON` with that setting is an
  untested alternative worth trying if SSL2 turns out to be a bottleneck.
- Confirmed working end-to-end: default `benchgen mvmc create` benchmark
  (`W=10,L=10`) ran via `mpiexec -n 1` in 60.3s wall time (single core) —
  see **mvmc-benchmarking** for the full sizing search on this machine.
- Binaries land at `build/src/mVMC/vmc.out`, `build/src/mVMC/vmcdry.out`.

## Local macOS (Homebrew)

Useful as a fast fallback when the cluster is unreachable, or for quick
local iteration. Requires `brew install gcc open-mpi cmake git`.

```sh
GCC_VER=$(brew list --versions gcc | awk '{print $2}' | cut -d. -f1)
cd mVMC && mkdir build && cd build
cmake -DCMAKE_C_COMPILER=gcc-$GCC_VER -DCMAKE_CXX_COMPILER=g++-$GCC_VER \
      -DCMAKE_Fortran_COMPILER=gfortran-$GCC_VER \
      -DUSE_GEMMT=OFF -DCMAKE_BUILD_TYPE=Release ..
make -j$(sysctl -n hw.ncpu)
```

- **Must use the versioned Homebrew binaries (`gcc-16`, not `gcc`)** —
  plain `gcc`/`cc` on macOS is Apple clang aliased, not GNU GCC, and won't
  give real OpenMP support (needs a separate `libomp` + special flags
  Apple clang requires, which is what mVMC's own `apple.cmake` preset
  works around — untested here since the `gcc-N` approach was simpler and
  already worked). Find the installed version with `brew list --versions
  gcc` rather than hardcoding a number, since it drifts on `brew upgrade`.
- **`-DUSE_GEMMT=OFF` is mandatory here, not just recommended** — the
  default BLIS download is a Linux binary and simply won't run on macOS at
  all (this is exactly the situation mVMC's own `mac_gcc.cmake` preset is
  built to avoid, though the explicit flags above were used directly
  rather than that preset). Without it, the build fails outright.
- BLAS/LAPACK auto-resolve to Apple's **Accelerate** framework — no flags
  needed, and it's fast (this Mac's serial run of the same benchmark input
  finished in ~40% of the DGX Spark node's wall time).
- MPI (`open-mpi` via Homebrew) has `mpicc`/`mpicxx` wrapping Apple clang
  but `mpif90` wrapping Homebrew's `gfortran` — a mixed-compiler MPI
  install. This is normal for Homebrew's `open-mpi` formula and caused no
  problems (the compiled `vmc.out` only links against Open MPI's C ABI,
  which isn't compiler-specific).
- **Known gotcha**: a Homebrew-installed standalone `pmix` package can end
  up ABI-newer than what `open-mpi` was actually linked against, causing
  `mpirun` to fail at `MPI_Init` with "binary incompatible" / PMIx version
  errors that have nothing to do with the mVMC build itself. Fix:
  `brew reinstall open-mpi` (relinks against the current `pmix`) — this
  changes installed packages on the machine, confirm with the user before
  running it.
- `mpirun` works directly, no `srun`-equivalent issue (this is a local
  machine, no Slurm).
