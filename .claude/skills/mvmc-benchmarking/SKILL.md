---
name: mvmc-benchmarking
description: Methodology and recorded results for picking an mVMC benchmark problem size on a given machine — largest lattice that completes one representative step in a practical time budget at one-MPI-rank-per-core. Use whenever the user asks what problem size to benchmark on a machine, wants to add a new machine's results, or asks about DGX Spark's / a Mac's recorded mVMC benchmark numbers.
---

# mVMC Benchmarking: picking a size per machine

This skill is the empirical companion to **mvmc-reference** (what the code
does) and **mvmc-build** (how to build it) — it's specifically about
*which problem size to run* on a given machine, and the actual measured
answers so far. Uses the `benchgen mvmc create` CLI from
**benchmark-generator** to generate inputs.

## Methodology

Deployment is fixed first, size is searched second — don't invert this:

1. **Fix the deployment**: `OMP_NUM_THREADS=1`, one MPI rank per core
   (`mpirun -n <core_count>`). Per `mvmc-reference`, OpenMP threading has
   shown no net benefit on any machine/size tested so far, and MPI ranks
   at the default `NSplitSize=1` are embarrassingly parallel (independent
   statistics, not shared memory) — so "one rank per core" is both the
   realistic default deployment and the one that maximizes memory
   pressure per rank (`total machine memory / core count` per rank, not
   the full machine total — see mvmc-reference's Memory section).
2. **Pick a time budget for one representative step** (`NSROptItrStep=1`,
   this repo's `benchgen mvmc create` default): **~2 minutes**. This isn't
   arbitrary — real production runs use hundreds of SR steps (tutorial
   examples: `NSROptItrStep~600`), so a 2-minute single step extrapolates
   to a ~20-hour full convergent run at that size, which is a plausible
   real production job. It also means memory essentially never becomes
   the binding constraint in practice: every problem size tested so far
   (`W`/`L` up to 20) used only ~100-200MB per rank, trivial against any
   modern machine's per-core memory share — time is the real constraint.
3. **Search `W=L` (square lattice, default half filling) at the full
   target deployment from the start** — don't extrapolate from a
   single-rank timing. Single-rank timing *understates* full-deployment
   wall time, sometimes substantially: on DGX Spark, `W=13` took 99s at 1
   rank but 125s once all 20 ranks were contending; on the Mac, `W=13`
   took even longer proportionally at 10 ranks than 1. Contention and (on
   heterogeneous chips) some ranks landing on slower cores both bite once
   every core is in use, and only testing at full deployment catches it.
4. **Stop at "close enough," not exactly under the cap.** DGX Spark's
   `W=13` came in at 125s against a ~120s target — 4% over — and was kept
   rather than stepping down to `W=12`, since the target itself is a soft
   guideline, not a hard limit.
5. If a candidate run is clearly going to blow well past the cap (not a
   close call), kill it early rather than waiting for it to finish —
   peak memory is set once during the initial `SetMemory()` allocation
   near the start of the run, so you don't need the run to complete to
   have learned what you needed from a doomed candidate.

## Recorded results

All results use `benchgen mvmc create --w N --l N` (defaults otherwise:
half filling, `NVMCSample=4000`, `NSROptItrStep=1`), `OMP_NUM_THREADS=1`,
one MPI rank per core, via `mpirun` (see mvmc-build for why not `srun` on
R-CCS Cloud).

| Machine | Cores | Build | Size | Wall time | Notes |
|---|---|---|---|---|---|
| R-CCS Cloud DGX Spark (`ng-dgx-m2`) | 20 (10 Cortex-X925 + 10 Cortex-A725) | GCC + NVPL `_gomp` (mvmc-build recipe) | `W=13, L=13` (169 sites) | 125.3s | `W=14` measured at 152s, over cap |
| Local Mac (Apple M4) | 10 (4P + 6E) | GCC-16 + Accelerate (mvmc-build recipe) | `W=12, L=12` (144 sites) | 73.3s | `W=13` measured at ~150s, over cap |

Peak per-rank memory on both machines stayed in the ~100-200MB range at
these sizes — nowhere near either machine's actual memory budget per
core. Confirms time, not memory, is the binding constraint at sizes
practical to benchmark quickly.

## Adding a new machine

1. Build per **mvmc-build** (add a new recipe there first if the machine
   needs one).
2. Determine core count (`nproc` / `sysctl -n hw.ncpu`).
3. Follow the methodology above: start from a known-fast size (e.g. try
   the smaller of the two sizes already recorded above as a sanity check
   first), binary-search upward at full deployment, stop near the 2-minute
   mark.
4. Record the result in the table above with machine spec, core count,
   build used, and the exact `benchgen` command.
