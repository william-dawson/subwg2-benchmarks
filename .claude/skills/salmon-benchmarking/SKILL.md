---
name: salmon-benchmarking
description: Methodology and recorded results for picking a SALMON (TDDFT) benchmark problem size on a given machine — real-space grid size, k-point mesh, and MPI/OpenMP deployment that completes a representative run in a practical time budget. Use whenever the user asks what SALMON problem size to benchmark on a machine, wants to add a new machine's results, or asks about SALMON's real-world scaling behavior on Fugaku/A64FX.
---

# SALMON Benchmarking: picking a size per machine

This skill is the empirical companion to **salmon-reference** (what the
code does) and **salmon-build** (how to build it, not yet written) — it's
specifically about *which problem size to run* on a given machine. Uses
`benchgen salmon create` from **benchmark-generator** to generate inputs.

**Status**: no empirical runs have been performed through this repo's
pipeline yet — this skill currently holds only the methodology (adapted
from `mvmc-benchmarking`'s, which is battle-tested) and one real external
reference point (see below). The "Recorded results" table is empty until
a machine is actually built and run per `salmon-build`.

## The GS stage is prep, not the benchmark

**The ground-state DFT run (`theory='dft'`) is only ever preparation for
the TDDFT run that follows it — it is not what we're benchmarking.** The
figure of merit for a SALMON benchmark is TDDFT propagation performance
(`theory='tddft_response'` or `'tddft_pulse'`), since that's the part of
the code real workloads actually spend their compute budget on and the
part the manual says is GPU-tuned (see `salmon-reference`'s GPU caveat —
"we recommend executing DFT (ground-state) calculations on CPUs and
TDDFT calculations on GPUs" is a direct statement of this same
priority). GS still has to run to completion first — TDDFT reads its
`restart/` output and can't start without it — and its wall time is
worth recording so a full pipeline's total cost is known, but **GS time
is not the number to report as "the" benchmark result, and it is not the
number to optimize deployment around.** When comparing machines or
deployments, lead with TDDFT per-step (or per-`nt`) cost; treat GS time
as a fixed, mostly-unavoidable setup tax to mention alongside it, not
the headline.

Practical implication: `benchgen salmon create --nt <N>` (added
specifically for this) lets you cap the TDDFT run at a short, fast `N`
instead of the base template's production-length `nt=6000` — use a
small `N` for iterating on deployment/sizing quickly, since GS itself
already costs real wall time (~94s even at the smallest 18-atom system
locally) before TDDFT timing can even start.

## What's different from mVMC here

SALMON's cost/deployment knobs are not a direct copy of mVMC's — read
`salmon-reference` first. The two most load-bearing differences:

- **Two-stage workflow, but only one stage is the benchmark.** Every run
  is a ground-state DFT run (SCF, `theory='dft'`) followed by a TDDFT run
  (`theory='tddft_response'`) reading its restart — see "The GS stage is
  prep, not the benchmark" above for why only the second stage is the
  figure of merit. They also have different scaling behavior (see
  `&parallel`'s `process_allocation` note in `salmon-reference`) and —
  per the GPU caveat in `salmon-reference` — potentially want to run on
  different hardware.
- **Sizing is grid-based, not lattice-count-based.** mVMC's cost knob is
  `W×L` (site count). SALMON's is the real-space grid
  (`&rgrid/num_rgrid`, driven in this repo by `spacing` via
  `create_input`'s `ceil(cell_length / spacing)`) combined with the
  supercell atom count (`atoms.repeat(size)` in `salmon.py`) and, for
  periodic systems, the k-point mesh (`&kgrid/num_kgrid`). Three separate
  levers, not one — a size sweep needs to decide up front which lever(s)
  it's actually varying.

## Golden rule (carried over from mVMC, not yet re-derived for SALMON)

mVMC's Golden Rule was "read timing from the code's own internal timer
(`zvo_CalcTimer.dat`), never wall-clock `time`" — because MPI startup
noise on some machines (Rikyu specifically) silently dominated wall-clock
measurements. **The SALMON analogue is `&analysis/yn_out_perflog`'s
performance log** (`format_perflog='text'` or `'csv'` for something
parseable) — but its exact per-phase breakdown has not yet been verified
against a real SALMON run in this repo. Treat wall-clock timing on any
new machine with the same suspicion mVMC required until this is checked:
confirm the perflog's total time is close to wall-clock before trusting
either one, and re-derive whether this machine's MPI startup carries the
same kind of hidden overhead Rikyu did for mVMC (there is no reason to
assume it won't recur — it was a property of the machine/launcher, not
of mVMC specifically).

## Methodology (adapted from mvmc-benchmarking)

1. **Fix the deployment before searching size.** Per `salmon-reference`'s
   GPU caveat, this may mean two different deployments (CPU for DFT, GPU
   for TDDFT) rather than one — decide that split first if the target
   machine has a GPU, per the manual's explicit recommendation that only
   the TDDFT part is GPU-tuned.
2. **Pick a time budget for one representative TDDFT run — this is the
   actual benchmark** (see "The GS stage is prep, not the benchmark"
   above). mVMC used a representative *single SR step* (~2 minutes)
   because a real run is hundreds of repeats of that step. SALMON's
   real-time propagation is the same shape — cost is (near-)linear in
   `&tgrid/nt` — so the same logic applies: use `benchgen salmon create
   --nt <N>` to cap propagation at a modest, fixed step count (enough
   steps to see steady per-step cost, not a single step, since setup
   overhead in step 1 isn't representative) and extrapolate from there.
   The ground-state SCF stage must still run to completion first (TDDFT
   can't start without its restart data) and its wall time is worth
   recording, but it doesn't get its own size/time search — run it to
   actual convergence once per problem size and move on; it is not the
   figure of merit.
3. **Search grid size first, k-points second**, unless the target
   application specifically needs converged k-sampling — grid spacing is
   the more direct analogue of mVMC's `W`/`L` as "the knob that scales
   compute cost predictably," while k-point count multiplies orbital
   count directly and independently.
4. **Verify real MPI coordination before trusting any timing**, exactly
   as mVMC's methodology point 8 requires — check that the reported
   process/rank count in the perflog or stdout actually matches what was
   launched, on every new machine. A launcher silently fragmenting into
   independent single-rank processes (confirmed to happen with bare
   `srun` on `qc-gh200` for mVMC) is a property of the launcher/machine,
   not of the specific code being run, so assume it can recur here too
   until checked.
5. **Check MPI process binding explicitly on `fx700`.** Two independent
   reasons to expect this matters more for SALMON than it did for mVMC:
   mVMC's own `fx700` result required `--bind-to core --map-by core` to
   fix a ~12x slowdown from unbound placement (see `mvmc-benchmarking`
   methodology point 6); and the Fugaku production paper (see Reference
   point below) shows SALMON specifically wants **one MPI process per
   CMG** on A64FX (not one per core) to avoid crossing the slow
   inter-CMG NUMA link — a coarser-grained binding requirement than
   mVMC's. Confirm which placement `fx700`'s Open MPI defaults to before
   trusting a multi-rank `fx700` timing.

## Recorded results

All results use `benchgen salmon create` (defaults otherwise: 18-atom
1×1×1 SiO2 conventional cell, `spacing=0.33/1.88973` bohr →
29×49×31 grid, no explicit `&kgrid` → Γ-point only). Timing source is
wall-clock via `time`/process-monitoring, not yet cross-checked against
`&analysis/yn_out_perflog`'s own reported total (see Golden Rule above —
this hasn't been verified safe on any machine yet, so treat these numbers
as provisional pending that check).

| Machine | Deployment | Size | GS time (prep) | TDDFT time | Notes |
|---|---|---|---|---|---|
| Local Mac (Apple M4) | GCC-16 + Open MPI 5.0.9 (`OMPI_CC=gcc-16 OMPI_FC=gfortran-16`), `mpirun -n 4`, Accelerate BLAS/LAPACK, `OMP_NUM_THREADS` unset (salmon-build recipe) | 1×1×1 (18 atoms, 29×49×31 grid) | 94.4s (100/100 `nscf` iterations to the template's default threshold, converged: Total Energy -6099.943 eV, gap 5.717 eV) | **1759.3s for `nt=6000`** ≈ 0.293s/step (electron count conserved to ~1.4e-6, energy stable at -6099.81 eV throughout, `_response.data`/`_rt.data`/`_rt_energy.data` all produced correctly) | First real data point through this pipeline. Confirms `--nt 300` (≈88s at this rate) is a much more practical quick-benchmark duration than the base template's `nt=6000` default — use `--nt` for future sizing searches on this or any machine rather than the full production-length run. |
| R-CCS Cloud `genoa` (AMD EPYC) | GCC 11.5.0 + Open MPI (`mpi/openmpi-x86_64` module), `mpirun -n 4`, FlexiBLAS, **`OMP_NUM_THREADS=1`** (salmon-build recipe) | 1×1×1 (18 atoms, 29×49×31 grid) — same input file uploaded from the Mac run, not regenerated | 22.25s (100/100 `nscf` iterations, converged: Total Energy -6099.943 eV, gap 5.717 eV — identical to Mac, as expected for identical input) | **49.48s for `nt=300`** ≈ 0.165s/step (electron count conserved to ~1.5e-7, energy stable at -6099.81 eV, all three output files produced correctly) | Both GS (4.2x) and TDDFT-per-step (1.8x) faster than the Mac M4 — plausible given genoa's higher core clock/count even at matched 4-rank deployment. **`OMP_NUM_THREADS=1` is not optional here**: the first attempt left it unset and got ~100x slower (2 SCF iterations in 4 minutes) from 4 MPI ranks each spawning up to 96 OpenMP threads on this 96-core machine — see salmon-build's genoa section. This is the same `OMP_NUM_THREADS=1` convention mVMC's methodology already established; don't assume it doesn't transfer just because SALMON's parallelization model differs. |
| R-CCS Cloud DGX Spark (`ng-dgx-m2`, GPU build) | `nvhpc/26.3` (`nvc`/`nvfortran` via NVIDIA HPC-X MPI), `--arch=nvhpc-openacc`, `mpirun -n 1` (1 rank = 1 GB10 GPU) (salmon-build recipe) | 1×1×1 (18 atoms, 29×49×31 grid) — same input file, not regenerated | 33.24s (100/100 `nscf` iterations, converged: Total Energy -6099.943 eV, gap 5.717 eV — correct, matches every CPU machine) | **10.81s for `nt=300`** ≈ 0.036s/step (electron count conserved to ~1.5e-7, energy -6099.81098920 eV — exact match to Mac/`genoa`'s CPU TDDFT) | **First machine with both GS and TDDFT verified correct on a GPU build** (`qc-gh200`'s GPU build has an unresolved correctness bug — see salmon-build). TDDFT is ~4.6x faster than `genoa`'s CPU-only `nt=300` run (49.48s) — the first concrete confirmation of `salmon-reference`'s GPU caveat ("TDDFT is GPU-tuned, DFT is not"): GS itself was *not* dramatically faster than CPU machines, but TDDFT was. |
| RIKYU (Grace CPU, `nvhpc-openmp` CPU-only build) | `nvhpc/26.5` (`nvfortran`/`nvc` via NVIDIA HPC-X MPI), `mpirun -n 4`, bare defaults — no `--mca`/binding flags needed (salmon-build recipe) | 1×1×1 (18 atoms, 29×49×31 grid) — same input file, not regenerated | 26.66s (100/100 `nscf` iterations, converged: Total Energy -6099.943 eV, gap 5.717 eV — correct, matches every other machine) | **34.35s for `nt=300`** ≈ 0.114s/step (electron count conserved to ~1.5e-7, energy -6099.81098920 eV — exact match to every other machine's CPU TDDFT) | First full GS+TDDFT correctness confirmation on Rikyu's CPU side, following the single/multi-node scaling and hybrid work in salmon-build. TDDFT actually *faster* than `genoa`'s CPU-only run (49.48s) despite GS being slightly slower than `genoa`'s (22.25s) — not deeply investigated, just noted. |

## Reference point: real Fugaku production run (not from this pipeline)

From Hirokawa, Yamada, Yamada, Uemoto, Noda, Boku, Yabana, "Large-scale
ab initio simulation of light-matter interaction at the atomic scale in
Fugaku", *IJHPCA* **36**(2), 182-197 (2022) — recorded here as an
external calibration point, not a result produced by this repo's
tooling. Directly relevant because it's the **same physical system**
(`salmon.py`'s `make_sio2()`) this repo already targets, run on the
**same processor family** (A64FX) as our `fx700` testbed, just at a
vastly larger scale (production Fugaku, up to 27,648 nodes ≈ 1/6 of the
full machine).

**System**: amorphous SiO2 thin film, H-terminated dangling bonds at the
surface. Unit block for weak scaling: `(SiO2)_480 H_264` = 1704 atoms per
432 nodes. Representative production run: 6 replicated blocks = **10,224
atoms** on 27,648 nodes, spatial grid **216×288×480**, box
3.95nm×5.13nm×8.65nm, a 6.6nm-thick slab sandwiched between ~1nm vacuum
regions, periodic in the two in-plane directions only (a slab
calculation, not fully 3D-periodic bulk) — closely matches what
`salmon.py`'s `create_input`/`make_sio2` builds, just at far larger
supercell size.

**Fugaku node spec** (Table 4 in the paper — directly relevant to
`fx700`, the same A64FX chip): 48+2 or 4 cores @ 2.0 GHz, 32 GiB HBM2, 4
CMGs of 12 cores + 8 GiB each, Tofu-D 6D mesh-torus network, 3072 GFLOPS
peak, 1024 GiB/s memory bandwidth, 512-bit SVE, 4 MPI processes/node (one
per CMG).

**Timestep cost**: `&tgrid/dt` = 0.00075 fs; 8000-step jobs (~6 fs of
physical time) took **~3 hours wall-clock** (~1.35s/step average,
including I/O) for the 10,224-atom production system. The full 18fs
simulation was 3 chained 8000-step jobs. I/O was negligible: reading the
initial state took 200-1200s, writing restart ~150s, and periodic
analysis output during an 8000-step run totaled only ~3.14s — out of a
~9000s job.

**Non-obvious methodology worth reusing**: to prepare the ground state
for the full 10,224-atom system, they did **not** run ground-state SCF on
the full supercell directly. They instead solved a much smaller
852-atom system (same slab thickness, same z-extent) with an explicit
k-point mesh (4×3 k-points, four subdivisions in x, three in y), then
**unfolded the resulting Bloch orbitals** to construct initial orbitals
for the full real-space supercell before starting TDDFT propagation. This
is a real, reusable technique for standing up ground-state initial
conditions of large low-symmetry/amorphous supercells cheaply — worth
considering if this repo ever needs a ground state at a supercell size
too expensive to converge directly.

**Scaling behavior** (weak scaling: fixed problem/node ratio, node count
432→1728→6912→27,648; strong scaling: fixed 6816-atom problem, node count
6912→13,824→27,648):
- Weak-scaling efficiency: 100% (432 nodes, baseline) → 95.8% → 84.3% →
  **73.4%** at 27,648 nodes, against a stated target of ≤1000ms/iteration
  (achieved: ~830ms → ~1132ms per iteration across that range) —
  "mostly accomplished" per the paper's own assessment.
- Strong-scaling parallel efficiency: 79-82%, called *better* than weak
  scaling by the authors, attributed to halo-communication growth being
  a smaller relative cost than the FFT/Allgather growth that dominates
  weak-scaling loss (see the FFTE bottleneck note in `salmon-reference`).
- Effective performance: 2.692 PFLOPS actual out of 84.935 PFLOPS
  theoretical peak at 27,648 nodes (3.17% of theoretical peak) — but
  **25.4% of the 10.583 PFLOPS memory-bandwidth-bound ceiling**, which is
  the number that actually matters (see the roofline note in
  `salmon-reference`) — the paper frames this as a genuine success, not
  underperformance, given SALMON is memory-bound on this hardware by
  construction.
- Compared explicitly against the prior largest real-time TDDFT
  benchmark they knew of (Draeger et al. 2016, plane-wave code on
  Sequoia BlueGene/Q, 5400 Al atoms, 53.2s/timestep, 43% of peak): this
  Fugaku run reached <1.2s/timestep for a comparably-sized 13,632-atom
  system — over 10x better time-to-solution, despite far lower fraction
  of theoretical peak, because SALMON's real-space grid method has a much
  more favorable memory-bandwidth ceiling than a dense plane-wave basis
  does.

**Single-node stencil roofline** (128³ grid, 48 OpenMP threads, A64FX):
322.72 GFLOPS achieved (10.5% of 3072 GFLOPS peak), ~2.68 Byte/Flop
arithmetic intensity, 866 GiB/s achieved memory bandwidth (84.5% of the
1024 GiB/s hardware ceiling) — see `salmon-reference`'s roofline note for
why 10.5%-of-peak is actually near-optimal here, not a red flag.

## Adding a new machine

1. Build per **salmon-build** (not yet written — add a recipe there
   first).
2. Determine core/CMG topology (`fx700` in particular: confirm 4
   CMGs/node and consider one-rank-per-CMG per the Reference point note
   above, not one-rank-per-core as mVMC uses).
3. Follow the methodology above: fix deployment (including any CPU/GPU
   split across the two stages), then search grid size at a fixed,
   modest k-point count, then k-points if the machine has room.
4. Verify perflog vs. wall-clock agree before trusting a number (Golden
   Rule above) — this hasn't been established as safe on any machine yet,
   unlike mVMC where it's now routine.
5. Record the result below with machine spec, deployment used (including
   CPU/GPU split if applicable), grid size, k-points, and the exact
   `benchgen` command. **Lead with TDDFT per-step time as the reported
   figure of merit; note GS wall time alongside it as setup cost, not as
   a second benchmark result** (see "The GS stage is prep, not the
   benchmark" above).
