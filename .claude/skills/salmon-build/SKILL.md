---
name: salmon-build
description: Build SALMON (https://github.com/SALMON-TDDFT/SALMON2) from source, currently verified locally on macOS via Homebrew. Use whenever the user asks to build, compile, or install SALMON on any target machine.
---

# Building SALMON

Build mechanics only. For what the code does or how its input/output
files work, see the **salmon-reference** skill. For generating benchmark
`.nml` files, see **benchmark-generator**. For the empirical
problem-size-per-machine methodology and recorded results, see
**salmon-benchmarking**.

**Status**: local macOS and `genoa` are fully verified (built, ran a full
GS+TDDFT SiO2 calculation end-to-end, correct physics/output — see
`salmon-benchmarking`'s Recorded results). `fx700` also works, but **only
with a GCC+MPICH toolchain, not the Fujitsu-compiler build** — the
Fujitsu-compiler+Open-MPI build compiles fine but reliably crashes on
multi-rank execution; see that section below for the full diagnostic
trail (root-caused to Fujitsu's own stack, not SALMON) and use the
GCC+MPICH recipe for any real `fx700` benchmarking. `qc-gh200`'s CPU-only
build (`nvhpc-openmp`) works correctly, but its **GPU build
(`nvhpc-openacc`) has a real, unresolved silent correctness bug** — wrong
Total Energy, reproduces even at 1 rank/1 GPU (so it's not an MPI/UCX
issue despite early appearances — see that section for the full,
corrected diagnostic trail). **DGX Spark's GPU build (same
`nvhpc-openacc` preset, different GPU generation — GB10/Blackwell vs.
GH200/Hopper) gives the *correct* answer** — it's the machine to use for
actual GPU-accelerated SALMON work right now. Rikyu not yet attempted —
unlike `mvmc-build`, this skill does not yet have a working recipe for
every machine. Add sections here as each one is actually built, following
the
same pattern.

```sh
git clone https://github.com/SALMON-TDDFT/SALMON2.git
cd SALMON2
git checkout develop-2.0.0   # already the default branch/HEAD as of this writing
```

Build system: CMake (≥3.14) driven by `configure.py`, a thin wrapper that
just constructs and runs a `cmake` command — see `configure.py --help`
for the full flag list. No C++ dependency (project is `LANGUAGES Fortran
C` only) and FFT is bundled internally (`src/ext/FFTE`), so a minimal
build needs no external libraries beyond MPI and LAPACK/BLAS.

## Local macOS (Homebrew)

Requires `brew install gcc open-mpi cmake git`. Verified with Homebrew
GCC 16.1.0 and Open MPI 5.0.9 on Apple Silicon (M4).

Two real, build-blocking issues were found on this branch/toolchain
combination — both are genuine upstream portability gaps (a Darwin libc
quirk and a modern-GCC strictness change), not local build-system
mistakes. Apply both before building:

**1. Darwin-only: patch `src/io/posix.c`.** On Darwin's SDK headers,
`#define _XOPEN_SOURCE 500` (already present in the file, needed for
`nftw`) has the side effect of hiding `<stdio.h>`'s `snprintf`
declaration — confirmed directly with a 5-line reproduction outside the
SALMON tree. GCC 16 treats the resulting implicit-declaration as a hard
error (older GCC only warned), so the build fails outright without this.
Bumping to `600` fixes it with no other effect (verified: `_XOPEN_SOURCE
600`/`700`/`800` all compile clean against the same test case, and 600+
still provides every POSIX feature this file uses — `mkdir`, `stat`,
`access`, `nftw`, all present since well before 500):

```sh
sed -i '' 's/#define _XOPEN_SOURCE    500/#define _XOPEN_SOURCE    600/' src/io/posix.c
```

Not expected to be needed on Linux — glibc's `snprintf` visibility isn't
gated the same way `_XOPEN_SOURCE` gates it on Darwin. Re-check on the
first Linux build rather than assuming; don't apply pre-emptively there.

**2. Any sufficiently new GCC (confirmed with GCC 16, likely needed with
GCC 10+): `-fallow-argument-mismatch`.** `src/parallel/communication.f90`
calls `MPI_Send`/`MPI_Recv`/`MPI_Irecv`/`MPI_Allreduce`/etc. relying on
Open MPI's classic `mpi` Fortran module generic interface, and modern
GCC's Fortran front end does stricter TKR (type/kind/rank) consistency
checking across that generic's specific bindings than older GCC did —
without the flag, the build fails with `Error: Type mismatch between
actual argument at (1) and actual argument at (2)` across dozens of call
sites (confirmed harmless: downgrading to a warning via the flag lets
every one of these compile and run correctly — this is the standard,
widely-documented fix for old-style MPI Fortran code hitting newer GCC,
not a SALMON-specific bug). Pass as `FFLAGS`, picked up automatically by
CMake as the initial `CMAKE_Fortran_FLAGS` value on first configure.

**3. `OMPI_CC=gcc-16 OMPI_FC=gfortran-16` — same mixed-compiler issue
`mvmc-build` documents for this Mac.** Homebrew's `mpicc`/`mpif90` wrap
Apple clang and Homebrew's `gfortran` respectively by default (`mpicc
-show` / `mpif90 -show` reveals this). SALMON's `CMakeLists.txt`
unconditionally overrides `CMAKE_C_COMPILER`/`CMAKE_Fortran_COMPILER` to
whatever `find_package(MPI)` resolves once `USE_MPI=on` (see
`cmakefiles/check_build_environments.cmake`), so without this override
the C compilation step silently becomes Apple clang, which doesn't
support the `-fopenmp` flag SALMON always passes — hard error (`clang:
error: unsupported option '-fopenmp'`), not silently dropped OpenMP.
`OMPI_CC`/`OMPI_FC` make Open MPI's wrapper compilers swap in GCC at
invocation time instead — confirmed via `mpicc -show` before/after.
Needed both at configure time (for the initial compiler-detection probes)
and at `make` time (each individual compile re-invokes the wrapper, which
re-reads the environment fresh).

Full build:

```sh
mkdir build_temp && cd build_temp
OMPI_CC=gcc-16 OMPI_FC=gfortran-16 FC=gfortran-16 CC=gcc-16 \
  FFLAGS=-fallow-argument-mismatch \
  python3 ../configure.py --enable-mpi \
  --disable-scalapack --disable-eigenexa --disable-libxc --disable-fftw \
  --prefix="$(pwd)/install" -r
OMPI_CC=gcc-16 OMPI_FC=gfortran-16 make -j$(sysctl -n hw.ncpu)
```

- LAPACK/BLAS auto-resolve to Apple's **Accelerate** framework — no flags
  needed (`-- LAPACK library found.` in the configure log), same as
  mVMC's macOS recipe.
- MPI (`find_package(MPI)`) auto-detects Open MPI 5.0.9 via `mpicc`/
  `mpif90` on `PATH` — no explicit `MPI_HOME` or similar needed.
- ScaLAPACK/EigenExa/Libxc/FFTW all disabled for this first build to
  minimize dependencies — SALMON's bundled FFTE (internal, no external
  library) handles FFT with these off. Revisit if a future benchmark
  specifically needs one of these (e.g. `--enable-scalapack` at large
  `nproc_ob` for the SCF subspace diagonalization, per
  `salmon-reference`'s `&parallel` notes).
- Output binary: `build_temp/salmon` (not `salmon.cpu` — that naming is
  from the older `configure.py --arch=...` cross-compile path per the
  CPC2019 paper; a plain host build without `--arch` just produces
  `salmon`).
- Run: `mpirun -n <N> ./salmon < input.nml > output.log` (the
  pseudopotential `file_pseudo` paths in a generated `.nml` are relative,
  so `cwd` must contain the `.psp8` files — same convention as
  `benchgen salmon create`'s output directory). Requires
  `OMPI_CC=gcc-16 OMPI_FC=gfortran-16` at run time too, since `mpirun`
  itself is one of the Homebrew Open MPI wrapper-adjacent tools reading
  that environment.
- Confirmed working end-to-end on the smallest possible `benchgen salmon
  create` output (1×1×1 SiO2, 18 atoms): ground-state SCF converged
  correctly (Total Energy -6099.943 eV, gap 5.717 eV, matches
  known-reasonable SiO2 band gap physics), and the following TDDFT
  `tddft_response` run completed all steps with electron count conserved
  to ~1e-6 and produced correct `_response.data`/`_rt.data`/
  `_rt_energy.data` output — see `salmon-benchmarking` for full timing.

## R-CCS Cloud, fx700 (Fujitsu A64FX)

**Build succeeds; multi-rank execution does not (yet) — unresolved, see
below.** As with mVMC, the compiler toolchain (`FJSVstclanga` module)
only exists on actual `fx700` compute nodes, not the shared login node —
`module load` succeeds silently there but the directory it points at
doesn't exist, so build/run must go through a submitted job (`submit_job`
with `queue_name: "fx700"`), not `run_command_on_cluster` directly.

SALMON's own `platforms/fujitsu-a64fx-ea.cmake` preset (documented as
covering Fugaku/FX1000/FX700) hardcodes the cross-compile `px`-suffixed
compiler names (`mpifrtpx`/`mpifccpx`) — per mVMC's own finding on this
exact partition, those don't exist here (native node, not a cross-compile
front-end); use the native names (`mpifrt`/`mpifcc`) directly instead of
`configure.py --arch=fujitsu-a64fx-ea`:

```sh
module load system/fx700 FJSVstclanga
cd SALMON2 && mkdir build_fx700 && cd build_fx700
cmake \
  -D CMAKE_C_COMPILER=mpifcc \
  -D CMAKE_Fortran_COMPILER=mpifrt \
  -D OPENMP_FLAGS="-Kopenmp" \
  -D CMAKE_Fortran_FLAGS_RELEASE="-Kfast -Kocl -Nlst=t -Koptmsg=2 -Ncheck_std=03s" \
  -D CMAKE_C_FLAGS_RELEASE="-Kfast -Kocl -Nlst=t -Koptmsg=2 -Xg -std=gnu99" \
  -D LAPACK_VENDOR_FLAGS="-SSL2BLAMP" \
  -D USE_MPI=on -D USE_SCALAPACK=off -D USE_EIGENEXA=off -D USE_LIBXC=off -D USE_FFTW=off \
  -D CMAKE_BUILD_TYPE=Release \
  ..
make -j48
```

- **Do not add `-Nfjomplib`** even though it's in the upstream preset
  (`"-Kopenmp -Nfjomplib"`, "use Fujitsu OpenMP library"). It made the
  very first MPI collective call fail with `jwe0002i stop logical error:
  get # of process/node` — this flag's node/process-topology
  auto-detection appears to depend on environment variables only present
  under Fujitsu's proprietary PJM launcher on real Fugaku, not under this
  testbed's plain Slurm + bundled Open MPI. Plain `-Kopenmp` alone
  compiles and links fine; no other change was needed to fix this
  specific symptom.
- Build itself succeeds cleanly with no source patches needed (unlike the
  two required on macOS) — confirms those two Mac fixes really were
  Darwin/newer-GCC-specific, not general SALMON portability bugs. Build
  time ~17.5 min on a single node (48 cores, `make -j48`), both with and
  without `-Nfjomplib`.
- Binary lands at `build_fx700/salmon` (aarch64 ELF, confirmed via `file`).

### Unresolved: multi-rank MPI crashes at startup

**Single-rank execution works perfectly** — `mpirun -n 1 ./salmon <
input.nml` on the smallest smoke-test input (18-atom SiO2, same input
used for the Mac verification) converges cleanly and prints `end SALMON`,
confirming the binary itself is sound.

**4-rank execution crashes during the very first `MPI_Bcast`** (the
initial namelist broadcast from rank 0), in one of two ways depending on
whether any Open MPI collective/BTL setting is touched at all:

- **Completely bare `mpirun -n 4 ./salmon < input.nml`** (no `--mca`
  flags, nothing): crashes with a real `SIGBUS` ("Bus error... Non-existant
  physical address") inside `libmpi.so`'s
  `ompi_coll_base_bcast_intra_generic`, i.e. inside Open MPI's own bcast
  implementation, not SALMON's code.
- **Any deviation from bare defaults** — tried, independently, all
  failing identically with `jwe0002i stop logical error: get # of
  process/node` instead of the SIGBUS: disabling vader (`--mca btl
  ^vader`), forcing the basic linear bcast algorithm
  (`--mca coll_tuned_bcast_algorithm 1`), disabling vader's CMA/XPMEM
  zero-copy path only (`--mca btl_vader_single_copy_mechanism none`), and
  setting the same algorithm override via `OMPI_MCA_*` environment
  variables instead of command-line flags (ruling out "it's specifically
  about `--mca` on the command line"). `--bind-to core --map-by core`
  (needed for mVMC's own fx700 performance, see `mvmc-build`) makes no
  difference to any of this either way.
- Confirmed this is **genuinely Fujitsu's own Open MPI**, not a generic
  build: `ompi_info` reports `Ident string: 4.0.1fj4.0.0`, `Prefix:
  /opt/FJSVstclanga/cp-1.0.30.01`, configured
  `--with-platform=fujitsu/FX700-optimized`. So this isn't a
  build-configuration mistake on our end — it's a real incompatibility
  between Fujitsu's FX700-tuned Open MPI patches and this specific
  launch environment (plain Slurm + `mpirun`, not their PJM scheduler).
- mVMC runs multi-rank MPI collectives (`MPI_Allreduce` for the SR solve)
  successfully on this exact partition/module with this same bundled
  Open MPI (see `mvmc-benchmarking`'s fx700 row) — so basic multi-rank
  MPI is not broken wholesale here; whatever's wrong is specific to
  SALMON's exact early-startup broadcast (possibly a derived-type or
  unusually-shaped buffer, or interaction with SALMON's own automatic
  `&parallel` process-decomposition logic — see next point).
- **Tried and ruled out: missing PMI/PMIx support.** The login node's
  `module avail` misses architecture-specific modules — on an actual
  `fx700` node, `/usr/share/modulefiles` (aarch64-specific, not visible
  from the x86_64 login node) has `pmi/pmix-aarch64`. Loading it and
  retrying both launchers:
  - `srun -n 4 --mpi=pmix "$BIN" < input.nml` — got *further* than any
    bare `mpirun` attempt (printed the theory/orbital banner, only 3-of-4
    ranks logged `jwe0002i` instead of 4-of-4), but still ultimately hit
    the identical SIGBUS inside `ompi_coll_base_bcast_intra_generic`.
  - `mpirun` with the same module loaded (`--bind-to core --map-by
    core`): one `jwe0002i`, then the same SIGBUS.

  So PMI/PMIx availability measurably changes how much topology-detection
  noise (`jwe0002i`) happens, but not the actual crash — confirming this
  is a real memory bug in Open MPI's own bcast implementation on this
  hardware/build, independent of launcher or PMI support. Don't spend
  more time on launcher choice; the crash is inside `libmpi.so` itself
  either way.
- **Resolved: root-caused to Fujitsu's own compiler+MPI stack, not
  SALMON, not the hardware.** Built SALMON a second time on the exact
  same `fx700` node using an entirely independent toolchain — plain
  system GCC 8.5.0 (`gcc`/`gfortran`, no module needed, already on
  `PATH`) plus a separate, architecture-specific MPICH module
  (`module load mpi/mpich-aarch64`, found in `/usr/share/modulefiles` —
  invisible from the shared x86_64 login node's own `module avail`,
  since it's aarch64-only; look on the actual compute node, not the
  login node, when hunting for alternatives like this). No `use mpi`
  compatibility issue this way — MPICH's Fortran module is its own,
  independent of Fujitsu's:
  ```sh
  module load mpi/mpich-aarch64
  cd SALMON2 && mkdir build_gccmpich && cd build_gccmpich
  cmake -D CMAKE_C_COMPILER=gcc -D CMAKE_Fortran_COMPILER=gfortran \
        -D USE_MPI=on -D USE_SCALAPACK=off -D USE_EIGENEXA=off -D USE_LIBXC=off -D USE_FFTW=off \
        -D CMAKE_BUILD_TYPE=Release ..
  make -j$(nproc)
  ```
  - **No `-fallow-argument-mismatch` needed** — GCC 8.5.0 (this node's
    system compiler) predates GCC 10's stricter generic-interface
    argument checking that required the flag on Mac/`genoa`.
  - **No vendor BLAS/LAPACK on this node at all** outside Fujitsu's own
    SSL2 — `find_package(LAPACK)` found nothing, so the build downloaded
    and compiled Netlib LAPACK 3.12.1 from source automatically
    (confirms this compute node has outbound internet access; took a few
    extra minutes, otherwise no issues).
  - **The exact same 4-rank GS run that reliably crashed under every
    Fujitsu-stack configuration (bare `mpirun`, every `--mca` variant,
    `srun --mpi=pmix`) completed perfectly** with this GCC+MPICH build:
    135.87s total, converged to `Total Energy -6099.94333354 eV, gap
    5.71749793 eV` — bit-for-bit the same physics every other machine
    gets. No `jwe0002i`, no `SIGBUS`, nothing.
  - **This conclusively narrows the bug to Fujitsu's own
    compiler-and/or-MPI stack** (`FJSVstclanga`/`cp-1.0.30.01`) —
    ruled out: SALMON's own code (works fine under a different
    toolchain), this specific hardware (same physical node both times),
    and PMI/launcher choice (already separately ruled out above). Since
    the crash trace lives entirely inside Fujitsu's precompiled
    `libmpi.so`, and a Fortran ABI mismatch between `frt`'s calling
    convention and that library's expectations is a real, known category
    of bug, this is most likely a genuine defect (or at least a real
    incompatibility) in Fujitsu's Open MPI 4.0.1 (`fj4.0.0`) build itself
    when driven outside Fujitsu's own PJM-based launch environment —
    not something fixable from our side without vendor support.
  - **Practical takeaway**: for benchmarking `fx700` going forward,
    **use this GCC+MPICH build**, not the Fujitsu-compiler build — it's
    the one that actually runs multi-rank. Revisit `-SSL2BLAMP`/vendor
    BLAS only if this reference-LAPACK build's performance turns out to
    be a bottleneck worth chasing (unlikely to matter much for TDDFT,
    which is dominated by the stencil/Hamiltonian, not dense linear
    algebra, per `salmon-reference`'s roofline note).
  - **Not tried, and no longer necessary**: explicitly setting
    `nproc_rgrid`/`nproc_ob` in `&parallel` to bypass SALMON's automatic
    process-decomposition logic. That would have been the next lever if
    the Fujitsu stack were still in play, but is moot now that a working
    toolchain exists — SALMON's own `&parallel` logic was never
    confirmed to be involved in the original crash in the first place.

## R-CCS Cloud, qc-gh200 (NVIDIA Grace Hopper, GPU build)

GH200 480GB (compute capability 9.0), aarch64 Grace CPU + Hopper GPU,
NVIDIA HPC SDK 26.5 (`module load system/qc-gh200 nvhpc`). Build succeeds
cleanly on the first attempt via SALMON's own `nvhpc-openacc` preset —
unlike Fujitsu's presets, NVHPC's compiler names have no cross-compile
suffix issue, so `configure.py --arch=...` works directly, no manual
compiler substitution needed:

```sh
module load system/qc-gh200 nvhpc
cd SALMON2 && mkdir build_temp && cd build_temp
python3 ../configure.py --arch=nvhpc-openacc --prefix="$(pwd)/install" -r
make -j$(nproc)
```

- `mpicc`/`mpif90` (`find_package(MPI)`) and LAPACK/BLAS
  (`libnvpl_lapack_core.so`/`libnvpl_blas_core.so`, NVIDIA's own
  Grace-tuned libraries) both auto-resolve with zero extra flags, same
  as mVMC's `qc-gh200` build.
- Confirmed genuinely GPU-enabled, not just accepting-but-ignoring the
  flags: build log has hundreds of `Generating acc routine seq` lines
  (real OpenACC codegen), and the linked binary (`ldd`) pulls in
  `libcudart.so`, `libcublasLt.so`, `libcusparse.so`,
  `libacchost.so`/`libaccdevice.so` (OpenACC runtime).
- **Correctness bug found, unresolved**: a 4-rank GS smoke test (same
  18-atom SiO2 input verified correct on every other machine) completed
  without crashing (`exit 0`, `end SALMON` printed) but converged to the
  **wrong** Total Energy — `-6112.12922835 eV` vs. the correct
  `-6099.94333354 eV` every other machine gets (~12 eV off, far beyond
  numerical noise). The band gap alone still matched
  (`5.71749793 eV`), plausibly because it's an eigenvalue *difference*
  where a systematic error partially cancels while the absolute energy
  does not. The run log is flooded with 288 occurrences of
  `[qc-gh200-...] allreduce.c:56/42 TL_UCP ERROR asymmetric src/dst
  memory types are not supported yet` — NVIDIA's HPC-X UCX transport
  rejecting an `MPI_Allreduce` that mixes GPU-resident (OpenACC device)
  and host-memory buffers. **This is a genuinely silent failure mode**:
  no crash, a clean-looking exit code, `end SALMON` printed — the wrong
  answer is only visible if you actually check the converged number
  against a known-good reference, exactly the class of bug this repo's
  methodology has been burned by before (mVMC's `qc-gh200` rank-
  fragmentation bug, Rikyu's timing-noise bug). **Do not trust any
  qc-gh200 OpenACC-build result without cross-checking Total Energy
  against another machine's converged value for the same input.**
- **Ruled out: the separate `nvhpc-openacc-cuda` preset does not fix
  this.** Built it (`configure.py --arch=nvhpc-openacc-cuda`, which adds
  `-DUSE_CUDA`, `enable_language(CUDA)`, and genuinely compiles SALMON's
  hand-written CUDA kernels `src/common/zpseudo.cu` and
  `src/common/stencil_current.cu` — confirmed present in the source tree,
  not just an OpenACC-directives-only build) and reran the identical
  4-rank smoke test: **bit-for-bit identical wrong result** —
  `Total Energy -6112.12922835 eV`, same gap, same 288 `TL_UCP ERROR`
  occurrences, same ~130s. This makes sense in hindsight: the failure is
  in UCX's MPI transport layer itself rejecting GPU/host buffer mixing in
  `MPI_Allreduce`, a layer *below* SALMON's own code — whether SALMON was
  compiled with OpenACC directives or hand-written CUDA kernels doesn't
  change how the MPI library handles the resulting GPU-resident buffers.
- **Tried, ruled out: `UCX_MEMTYPE_CACHE=n` and disabling GPU-Direct
  transports.** Both the OpenACC build uses `-gpu=managed` (CUDA Unified
  Memory), and UCX's memtype cache is a known source of false-positive
  "asymmetric memory types" errors specifically with unified/managed
  memory (the same pointer's actual physical location can migrate, so a
  stale cache entry gives the wrong answer) — a well-targeted hypothesis.
  Tested on the OpenACC build, three ways, each rerunning the full 4-rank
  GS smoke test: `UCX_MEMTYPE_CACHE=n` alone, `UCX_TLS=^cuda_ipc,
  ^cuda_copy,^gdr_copy` alone (forces collectives to avoid every
  GPU-Direct transport), and both combined. **All three gave the
  identical wrong result** (`Total Energy -6112.12922835 eV`, same as
  the unmodified run) — neither env var changed anything.
- **Root-caused via a CPU-only build on the identical stack.** Built
  SALMON with SALMON's own `nvhpc-openmp` preset — same NVHPC compilers
  (`nvfortran`/`nvc` via `mpifort`/`mpicc`), same HPC-X MPI, same
  `qc-gh200` node, but `USE_OPENACC` never set, so **zero GPU code
  paths at all**:
  ```sh
  module load system/qc-gh200 nvhpc
  cd SALMON2 && mkdir build_cpu && cd build_cpu
  python3 ../configure.py --arch=nvhpc-openmp --prefix="$(pwd)/install" -r
  make -j$(nproc)
  ```
  The identical 4-rank GS smoke test on this build gave the **correct**
  result: `Total Energy -6099.94333354 eV, gap 5.71749793 eV` — exact
  match to every CPU machine — with **zero** `TL_UCP` errors, and
  faster too (26.58s, even faster than `genoa`'s pure-MPI run, plausibly
  thanks to NVPL's Grace-tuned BLAS and Grace's per-core performance).
  This confirms the bug is specific to the OpenACC/GPU code path, not
  SALMON's code in general or this MPI library in general.
- **Correction — the `MPI_Allreduce`/UCX theory was wrong.** Reran the
  OpenACC build's GS smoke test with **`mpirun -n 1`** (matching
  `qc-gh200`'s actual topology: exactly 1 GPU per node, so 1 rank = 1 GPU,
  no cross-rank sharing of one device at all). With a communicator of
  size 1, `MPI_Allreduce` is a local no-op — and indeed, **zero**
  `TL_UCP` errors this time. But the energy was **still wrong**,
  bit-for-bit identical to the 4-rank case: `-6112.12922835 eV`. Since
  this reproduces with no real inter-process reduction happening at all,
  **the bug cannot be in `MPI_Allreduce`/UCX** — all the UCX-flag
  experimentation above (`UCX_MEMTYPE_CACHE`, `UCX_TLS` variants) was
  chasing a symptom that only became *visible* at higher rank counts, not
  the actual defect. The real bug is somewhere in SALMON's own
  OpenACC-offloaded GPU kernels themselves (a host/device sync gap, a
  `-gpu=managed` data-coherence issue, or an `nvfortran` OpenACC codegen
  problem for this specific calculation) — not yet localized further.
- **Also tried, ruled out: `UCX_TLS=self,sm`** (whitelist to shared
  memory + loopback only, excluding every CUDA/verbs/RDMA transport, not
  just the GPU-Direct-specific ones). This fails *harder*, not better —
  a raw `SIGBUS` inside `MPI_Waitall` (UCX has no way left to move the
  OpenACC `managed`-memory device-resident buffers at all, so something
  ends up dereferencing a device pointer as host memory). Consistent with
  the point above: the bug isn't really about which UCX transport is
  selected.
- **Independent test on different hardware: DGX Spark's GPU build is
  CORRECT.** Built and ran the identical `nvhpc-openacc` 1-rank smoke
  test on `ng-dgx-m0` (`module load system/ng-dgx nvhpc` — GPU is an
  NVIDIA GB10, Blackwell architecture, compute capability 12.1, a
  completely different GPU generation from `qc-gh200`'s GH200/Hopper
  cc90; `nvhpc/26.3`+CUDA 13.1 there, vs. `qc-gh200`'s `nvhpc/26.5`+CUDA
  13.2 — the only/latest version available on each machine respectively,
  confirmed via `module avail`). Result: `Total Energy -6099.94333354 eV`
  — **correct**, exact match to every CPU machine, zero `TL_UCP` errors,
  33.24s. **The bug does not reproduce on DGX Spark.** Since GPU
  architecture and NVHPC/CUDA version both differ between the two
  machines, this doesn't yet cleanly isolate *which* difference matters —
  but it does mean a working GPU build genuinely exists on this cluster:
  **use DGX Spark, not `qc-gh200`, for any real GPU-accelerated SALMON
  benchmarking for now.**
- **Practical takeaway**: `qc-gh200`'s GPU build has a real, unresolved,
  silent correctness bug — use its CPU-only `nvhpc-openmp` build instead
  (ground-state DFT is CPU-recommended by the manual anyway, per
  `salmon-reference`'s GPU caveat). For actual GPU-accelerated work
  (particularly TDDFT, the stage the manual recommends GPU for), use
  DGX Spark's GPU build, which has been verified correct — but only for
  GS so far; TDDFT on DGX Spark's GPU build is untested, verify its
  converged energy against a CPU reference before trusting it, using the
  same cross-check method that caught this bug in the first place.
- Not yet tried: narrowing down *why* `qc-gh200` specifically fails while
  DGX Spark doesn't (same NVHPC major version family, different exact
  version + different GPU architecture) — would need either a matched
  NVHPC version on both machines, or profiling/debugging SALMON's actual
  OpenACC kernels directly (e.g. `compute-sanitizer`) rather than
  black-box energy comparison, to find the real defect.

## R-CCS Cloud, genoa (AMD EPYC)

AMD EPYC, x86_64, Rocky Linux, GCC 11.5.0, 96 physical cores. Fully
verified end-to-end (build + GS + TDDFT smoke test, see
`salmon-benchmarking`'s Recorded results for timings).

```sh
module load system/genoa mpi/openmpi-x86_64
cd SALMON2 && mkdir build_genoa && cd build_genoa
cmake \
  -D CMAKE_C_COMPILER=gcc \
  -D CMAKE_Fortran_COMPILER=gfortran \
  -D CMAKE_Fortran_FLAGS_RELEASE="-O3 -fallow-argument-mismatch" \
  -D LAPACK_VENDOR_FLAGS="/lib64/libflexiblas.so.3" \
  -D USE_MPI=on -D USE_SCALAPACK=off -D USE_EIGENEXA=off -D USE_LIBXC=off -D USE_FFTW=off \
  -D CMAKE_BUILD_TYPE=Release \
  ..
make -j$(nproc)
```

- **`-fallow-argument-mismatch` needed here too** — same
  generic-interface-vs-modern-GCC issue documented in the macOS section
  above (GCC 11.5.0 on this image is new enough to trigger it, same as
  Homebrew GCC 16 on Mac). Confirmed by first trying without it: build
  failed with the identical `Error: Type mismatch between actual argument
  at (1) and actual argument at (2)` pattern in
  `src/parallel/communication.f90`.
- **Use `LAPACK_VENDOR_FLAGS`, not `BLAS_LIBRARIES`/`LAPACK_LIBRARIES`.**
  Those are mVMC's CMake variable names, not SALMON's — passing them to
  SALMON's build is silently a no-op (SALMON's `build_lapack.cmake` only
  checks for `LAPACK_VENDOR_FLAGS`; anything else falls through to
  `find_package(LAPACK)`, which per mVMC's own genoa findings finds
  nothing on this Rocky Linux image, so the build would instead try to
  download and compile Netlib LAPACK from source via `ExternalProject`).
  Point `LAPACK_VENDOR_FLAGS` directly at `/lib64/libflexiblas.so.3`
  (FlexiBLAS, the only BLAS/LAPACK on this image, same as mVMC's finding).
- **Module (`FJSVstclanga` for fx700, `mpi/openmpi-x86_64` here) and the
  actual compiler/MPI toolchain only resolve on real compute nodes**, not
  the shared login node — same as fx700. Build via a submitted job
  (`queue_name: "genoa"`), not `run_command_on_cluster` directly.
- **Set `OMP_NUM_THREADS=1` before running** — without it, on this
  96-physical-core machine, 4 MPI ranks each spawning up to 96 OpenMP
  threads causes catastrophic oversubscription (~4 threads/core): a smoke
  test that should take under a minute instead did 2 SCF iterations in 4
  minutes (>100x slower) before being killed. This matches this repo's
  established mVMC convention (`OMP_NUM_THREADS=1`, one MPI rank per
  core) — don't assume it doesn't apply just because SALMON's
  parallelization model is otherwise different from mVMC's (see
  `salmon-reference`).
- No source patches needed (same as fx700, unlike the two required on
  Darwin) — build succeeds in well under a minute (~44s wall,
  `make -j$(nproc)` on 96 cores).
- Binary lands at `build_genoa/salmon` (x86_64 ELF).

## R-CCS Cloud, DGX Spark (`ng-dgx-m0`-`ng-dgx-m3`, GPU build)

NVIDIA GB10 (Blackwell, compute capability 12.1), Grace CPU, aarch64,
Ubuntu 24.04.4. Partition name for `submit_job`/`queue_name` is
`ng-dgx-m0` (etc, not the bare `system/ng-dgx` module name — those are
different things, don't conflate them for `queue_name`). **Fully
verified correct** — the only machine so far where SALMON's GPU build
(`nvhpc-openacc`) gives the right answer; see `qc-gh200`'s section for
the correctness bug found there that does *not* reproduce here.

```sh
module load system/ng-dgx nvhpc
cd SALMON2 && mkdir build_gpu && cd build_gpu
python3 ../configure.py --arch=nvhpc-openacc --prefix="$(pwd)/install" -r
make -j$(nproc)
```

- Only one `nvhpc` version exists on this machine's module tree
  (`nvhpc/26.3`, CUDA 13.1) — already the newest/only option, nothing to
  choose between (unlike `qc-gh200`, which has `nvhpc/24.3` through
  `26.5`).
- Builds cleanly despite the `nvhpc-openacc` preset's `-gpu=` compute-
  capability list (`cc80,cc90,cc100,cc120,...`) not containing an exact
  `cc121` entry for this GB10/Blackwell card — `nvfortran` handles the
  near-match via PTX JIT fallback, no build or runtime issue observed.
- Verified with the same 1-rank (1 GPU) GS smoke test used to root-cause
  `qc-gh200`'s bug: `Total Energy -6099.94333354 eV, gap 5.71749793 eV`
  — correct, matches every CPU machine, zero `TL_UCP` errors, 33.24s.
- `mpirun` confirmed working for this (single-rank) test; per
  `mvmc-build`'s own DGX Spark section, `srun` is unsupported by this
  partition's bundled Open MPI (no Slurm PMI support) — use `mpirun`.
- Not yet tested: multi-rank on this partition (each node has how many
  GPUs? — `mvmc-build`'s own DGX Spark section describes 20 CPU cores
  but doesn't mention GPU count; check before assuming 1 GPU/node the
  way `qc-gh200` is), or TDDFT specifically (only GS verified so far).

## RIKYU (GB200 NVL4, Grace CPU)

144 cores (2× Neoverse-V2 sockets), 4× GB200 GPUs/node, `nvhpc/26.5`
(same module family as `qc-gh200`/DGX Spark — `module load nvhpc/26.5`,
no `system/...` prefix needed here, unlike R-CCS Cloud). Jobs need
`attributes.account` set explicitly (Rikyu has multiple project
associations, no default) — this project's mVMC work used `rkp00015`,
reused here for consistency. CPU-only build (`nvhpc-openmp` preset, same
recipe as the other NVHPC machines) is fully verified correct.

```sh
module load nvhpc/26.5
cd SALMON2 && mkdir build_cpu && cd build_cpu
python3 ../configure.py --arch=nvhpc-openmp --prefix="$(pwd)/install" -r
make -j$(nproc)
```

- **Don't carry over mVMC's Rikyu env vars without re-verifying them for
  SALMON.** The first attempt reused `UCX_IB_MLX5_DEVX=n` from
  `mvmc-benchmarking`'s Rikyu findings (there, it fixed an MPI-*startup*
  registration failure) plus `--bind-to core --map-by core` — and hit a
  crash: `ib_mlx5_log.c:184 Remote operation error on mlx5_2:1/IB`, a real
  InfiniBand RDMA completion error, inside UCC (`mca_coll_ucc_bcast` →
  `ucc_tl_ucp_scatter_knomial_progress`), `SIGABRT`. Tried disabling UCC's
  collective component (`--mca coll ^ucc`) next — still crashed, same
  error. **The actual fix was to remove the inherited flags entirely** —
  a completely bare `mpirun -n 4 ./salmon < input.nml`, no env vars, no
  `--mca` flags at all, ran cleanly: `Total Energy -6099.94333354 eV, gap
  5.71749793 eV` (correct, matches every other machine), 26.67s. The
  lesson mVMC learned about this InfiniBand stack doesn't transfer
  automatically to a different code/MPI-collective-usage-pattern — verify
  fresh on each new codebase rather than assuming an old workaround still
  applies (or is still needed at all).
- Single-node scaling (4/36/72/144 ranks — all factor cleanly into 2s and
  3s, satisfying SALMON's automatic `&parallel` assignment requirement
  per `salmon-reference`): see `salmon-benchmarking` for recorded numbers.
- **MPI+OpenMP hybrid works well, but only with correct binding.** Rikyu
  has 144 cores across exactly 2 CPU sockets (`numactl --hardware` shows
  34 "NUMA nodes," but 32 of them are CPU-less GPU-memory-only nodes —
  the 4 GB200 GPUs' memory pools — only nodes 0 (cpus 0-71) and 1 (cpus
  72-143) have any CPUs; don't be misled by the raw NUMA node count into
  thinking this is a complex CPU topology, it's just 2 sockets).
  - **First attempt used `--bind-to none`** (copied from what worked on
    `genoa` — but `genoa` is single-socket, so unconstrained thread
    placement was harmless there). On Rikyu's 2-socket topology this let
    threads scatter across sockets — the run hadn't even finished the
    `init_ps` setup phase after 3.5+ minutes (the pure-MPI baseline
    finishes the *entire* run in ~65s), a clear sign of severe cross-
    socket memory-access thrashing. Never let it finish; killed it.
  - **`--map-by numa:PE=4` failed outright**: "A request was made to bind
    that would require binding processes to more cpus than are available
    in your allocation" — Open MPI's NUMA-aware mapper gets confused by
    the 32 CPU-less NUMA nodes in the topology.
  - **`--map-by socket:PE=4 --bind-to core` also failed the same way at
    first** — but the real cause wasn't the mapping policy, it was the
    **Slurm allocation itself**: `processes_per_node=36` with no
    `cpu_cores_per_process` set only reserves 1 core/task (36 cores
    total) by default, so Open MPI correctly refused to bind 4
    threads/rank when the job's own cgroup only had 36 cores available.
    Setting `resources.cpu_cores_per_process=4` alongside
    `processes_per_node=36` (renders to `--ntasks-per-node=36
    --cpus-per-task=4` in the sbatch script — verify this with `cat` on
    the rendered `agent/jobs/*.sh` script, don't just assume the resource
    spec mapped the way you intended) fixed it.
  - **Result, with both the binding flags and the Slurm allocation
    correct**: 36 ranks × 4 threads (144 total, matching pure-MPI 144's
    core count) — `Total Energy -55125.19516013 eV, gap 6.92196378`
    (bit-for-bit matches the pure-36-rank baseline, confirming
    correctness), **34.62s** — 1.89x faster than pure-MPI 36 ranks
    (65.32s) and 1.74x faster than pure-MPI 72 ranks (60.29s) using the
    *same* 144 total cores. Hybrid genuinely wins here, once bound
    correctly — same conclusion as `genoa`, different specific binding
    flags needed due to the different (multi-socket) topology.
- Multi-node: not yet tested.
