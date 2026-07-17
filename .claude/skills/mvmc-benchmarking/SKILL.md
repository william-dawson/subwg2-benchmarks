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

## Golden rule: read timing from mVMC's own output, never from `time`

**The authoritative time-to-solution is `zvo_CalcTimer.dat`'s `All` line
(or `benchgen fom`, which already reads it correctly) — not the `real`
value from wrapping a launch in `time mpirun ...`.** This isn't a style
preference. On R-CCS Cloud's `rikyu` partition, a `W=10` run's wall-clock
`time` reported **115s** while the same run's `zvo_CalcTimer.dat` `All`
was **22.13s** — nearly identical to `qc-gh200`'s 22.19s at the same size.
Repeated UCX InfiniBand-registration failures at MPI startup
(`mlx5dv_devx_alloc_uar(...) ... Cannot allocate memory`) were adding
~90s of pure launcher/network-setup noise to every wall-clock
measurement, and that noise was mistaken for real compute cost through an
entire investigation (see rikyu's row below and its history for the full
story). Every configuration change tried during that investigation
(removing the IB transport, single-socket pinning, rank-mapping strategy,
BLAS vendor, compiler) was actually just reducing *that startup noise*,
not real compute time — which is exactly why none of them meaningfully
closed what looked like a performance gap to `qc-gh200` but never
genuinely existed.

Wall-clock time is still worth knowing (it's what a real user waits for,
startup noise and all), but it must never be the number used to decide a
machine's problem size, and it must never be assumed to equal the
internal timer without checking. Confirm on every new machine: does the
job's log start producing output within a few seconds of launch, or does
it sit empty for tens of seconds first? An empty log for a while is the
tell that wall-clock and internal timer are about to diverge — go straight
to `zvo_CalcTimer.dat` rather than trusting `time`'s `real`.

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
6. **Before concluding a multi-rank slowdown is a hardware/interconnect
   limit, check MPI process binding.** On R-CCS Cloud's `fx700` partition,
   decrementing `W` repeatedly failed to bring a 48-rank run under the
   time budget — per-rank compute time stayed flat (~15s) while wall time
   grew *linearly* with rank count (1 rank: 13.7s, 12: 45.8s, 24: 91.9s,
   48: 183.8s — ~3.9s of pure overhead added per rank, every time), which
   looked exactly like a fundamental scaling ceiling. It wasn't: that
   partition's Open MPI wasn't binding processes to cores by default.
   Adding `--bind-to core --map-by core` to `mpiexec` dropped the same
   48-rank/`W=7` run from 183.8s to 15.2s — over 12x — matching pure
   compute with no overhead at all.

   This is not universal, though — don't apply it reflexively. Retesting
   the *already-recorded* DGX Spark result with the same flags changed
   nothing (127.7s unbound vs. 126.3s bound, within noise): that
   partition's default placement was already fine. Check binding on each
   new machine; don't assume either outcome.
7. **Check both `srun` and `mpirun`, on each new machine — don't assume
   `mpirun` is universal.** DGX Spark and `fx700`'s bundled Open MPI lack
   Slurm PMI support, so `srun` fails outright there (loud, immediate
   error) and `mpirun` is the only option (see mvmc-build). `rikyu` also
   failed `srun` outright (bare `srun` errors at `MPI_Init`; `srun
   --mpi=pmix_v3` there segfaults instead) — a different, also-loud
   failure mode from `qc-gh200`'s silent one below. `mpirun`/`mpiexec` is
   what's used on `rikyu`.

   On `qc-gh200`, bare `srun -n 72 ./vmc.out` did *not* fail loudly — it
   silently fell back to 72 independent single-rank processes (a known
   Open MPI behavior when PMI/PMIx isn't wired up for a given binary),
   each believing it was rank 0, all racing to write the same output
   files. This produced a clean-looking, plausible result (~19-22s) that
   was actually just single-rank speed, and was originally mistaken for
   "`srun` is 25% faster than `mpirun`" — it wasn't; it wasn't measuring
   72 ranks at all. `srun --mpi=pmix_v3 -n 72` (the correct explicit
   invocation) and `mpirun -n 72` are both genuinely coordinated on this
   machine and give essentially identical numbers (~21-22s). This is
   exactly why point 8 (below) is now mandatory before trusting any
   launcher/rank-count combination on a new machine — a clean output file
   does not by itself prove real coordination happened.
8. **Verify real MPI coordination before trusting any timing, on every
   machine.** Apply the source patch documented in **mvmc-build**'s
   "Apply this patch before building, on every machine" section, then
   check `zvo_walkercheck.dat` after every run: `IndependentWalkers` must
   equal the rank count you launched with, and `TotalEffectiveSamples`
   must equal `NVMCSample × IndependentWalkers`. This is a standing
   requirement now, not a one-off fix for the `qc-gh200` bug — a launcher
   can silently fragment into N independent single-rank processes on any
   machine, produce a perfectly clean-looking output file, and give a
   plausible timing number that isn't measuring what you think it is.
   Confirmed working on every machine tested so far — `qc-gh200`, DGX
   Spark, `fx700`, `genoa`, and `rikyu` (the last confirmed at both
   single-node/144-rank and 2-node/288-rank scale) — see each machine's
   row below.

## Recorded results

All results use `benchgen mvmc create --w N --l N` (defaults otherwise:
half filling, `NVMCSample=4000`, `NSROptItrStep=1`), `OMP_NUM_THREADS=1`,
one MPI rank per core. Launcher varies by machine — see methodology
points 7-8 and each machine's row below; check mvmc-build for what a
given machine's bundled MPI actually supports. Every row below has been
spot-checked against `zvo_walkercheck.dat` (methodology point 8) —
`IndependentWalkers` matched the intended rank count in every case,
including DGX Spark and `fx700`, which were re-verified retroactively
after the `qc-gh200` bug was found and turned out to have been genuine
all along.

**Timing source**: per the Golden Rule above, all times below are (or
should be treated as) `zvo_CalcTimer.dat`'s `All` value, not raw
wall-clock. DGX Spark, Mac, `fx700`, `qc-gh200`, and `genoa` all showed
prompt log output (no multi-second silent gap at launch) and, where
directly cross-checked (`qc-gh200`: wall 105.3s vs. internal 103.4s),
wall-clock and internal timer agreed closely — consistent with these
machines having negligible MPI-startup overhead, unlike `rikyu`. Still,
these were recorded before the Golden Rule was formalized; treat them as
reliable but not re-verified against `zvo_CalcTimer.dat` line-by-line,
and re-check if a number here is ever surprising.

| Machine | Cores | Build | Size | Time | Notes |
|---|---|---|---|---|---|
| R-CCS Cloud DGX Spark (`ng-dgx-m2`) | 20 (10 Cortex-X925 + 10 Cortex-A725) | GCC + NVPL `_gomp` (mvmc-build recipe) | `W=13, L=13` (169 sites) | 125.3s | `mpirun` (`srun` unsupported); `W=14` measured at 152s, over cap; binding flags retested and confirmed no-op (127.7s vs. 126.3s); walker-check re-verified at 130.3s, `IndependentWalkers=20` as expected |
| Local Mac (Apple M4) | 10 (4P + 6E) | GCC-16 + Accelerate (mvmc-build recipe) | `W=12, L=12` (144 sites) | 73.3s | `mpirun` (only launcher available); `W=13` measured at ~150s, over cap |
| R-CCS Cloud `fx700` testbed (Fujitsu A64FX) | 48 (4 NUMA/CMG × 12) | Fujitsu compiler + SSL2 (mvmc-build recipe) | `W=12, L=12` (144 sites) | 158.0s | `mpirun` (`srun` unsupported); requires `--bind-to core --map-by core` (see methodology point 6) — accepted as "close enough" over the ~120s target rather than narrowing further to `W=11`; walker-check re-verified at 155.1s, `IndependentWalkers=48` as expected |
| R-CCS Cloud `qc-gh200` (NVIDIA Grace Hopper) | 72 (Neoverse-V2) | GCC + NVPL `_gomp` (mvmc-build recipe) | `W=13, L=13` (169 sites) | 108.2s (wall 105.3-108.2s vs. internal 103.4s, cross-checked, closely agree) | `mpirun` (bare `srun` is broken here — see methodology point 7; `srun --mpi=pmix_v3` also works and gives the same ~equivalent numbers, but `mpirun` needs no extra flag); walker-check confirmed `IndependentWalkers=72`; `W=14` re-measured at 269s — over 2x the cap, a much steeper jump than the other machines saw between adjacent sizes, plausibly memory-bandwidth contention across 72 ranks on one socket; `W=10` baseline (100 sites) measured at 22.2s for scale |
| R-CCS Cloud `genoa` (AMD EPYC 9684X) | 96 (SMT on, 192 logical — used 96 physical) | GCC + FlexiBLAS/OpenBLAS-OpenMP (mvmc-build recipe) | `W=13, L=13` (169 sites) | 102.2s | `mpirun --bind-to core --map-by core`; walker-check confirmed `IndependentWalkers=96`; `W=14` measured at 157.1s, over cap; `W=10` baseline (100 sites) measured at 27.7s for scale — single NUMA node, no cross-socket effects to check (unlike Rikyu's dual-socket Grace) |
| R-CCS Cloud `rikyu` (GB200 NVL4, Grace CPU) | 144 (2× Neoverse-V2 Grace sockets, 72 each) | `nvc`/NVPL `_seq` (mvmc-build recipe) | `W=13, L=13` (169 sites) | 112.7s (internal timer — see Golden Rule; wall-clock on this machine includes ~90s of unrelated MPI-startup noise and should never be used) | **This is the machine that prompted the Golden Rule above** — an entire investigation chasing an apparent "2.4x slower than `qc-gh200`" gap (tried: removing IB transport, single/dual-socket pinning, `core`/`l3cache`/`socket` rank mapping, NVPL vs. system OpenBLAS, `nvc` vs. GCC) never found a real compute problem because there wasn't one: every fix was incidentally reducing MPI-startup noise (UCX InfiniBand-registration retries, `mlx5dv_devx_alloc_uar ... Cannot allocate memory`, a `PF_LOG_BAR_SIZE` firmware limit) counted by wall-clock `time`, not real compute time. `UCX_IB_MLX5_DEVX=n` (forces UCX's older, non-DEVX ibverbs path) clears the warning without fixing the startup delay itself, but is confirmed **safe for genuine multi-node use** — a real 2-node/288-rank `W=10` run completed correctly with it set (22.97s internal timer, walker-check confirmed `IndependentWalkers=288`), nearly identical to the single-node `W=10` baseline (22.13s), showing no cross-node slowdown. `--bind-to core --map-by core` is required (default placement is measurably worse, consistent with `fx700`'s binding requirement). `W=14` measured at 277.4s, well over cap. Walker-check confirmed `IndependentWalkers=144` throughout. |

Peak per-rank memory on all six machines with completed sizing searches
stayed in the ~100-200MB range
at these sizes — nowhere near any machine's actual memory budget per
core. Confirms time, not memory, is the binding constraint at sizes
practical to benchmark quickly.

## Reference point: real Fugaku (not from this pipeline)

User-reported, run directly on production Fugaku (not built/run via this
repo's tooling — recorded here as an external calibration point, not a
result to treat the same as the table above):

- `W=10, L=10` (100 sites), 48 MPI ranks, 1 node, same input `benchgen
  mvmc create --w 10 --l 10` would generate (`ncond=100`,
  `NVMCSample=4000`, `NSROptItrStep=1`) — **67.76s total**, no special
  binding flags needed (Fugaku's own MPI, not the `fx700` testbed's Open
  MPI, handles placement correctly by default).
- This is the number that caught the `fx700` testbed's binding bug: its
  unbound 48-rank runs were wildly slower than this for comparable sizes,
  which is what prompted checking process binding in the first place
  (methodology point 6). Once bound correctly, the testbed's `W=7` result
  (15.2s) scales cubically to a `W=10` prediction of ~62s — close to this
  real 67.76s, confirming the testbed is now a reasonable proxy for real
  Fugaku once binding is fixed.
- The detailed per-phase timer breakdown from this run also corrected an
  assumption in `mvmc-reference`'s parallelization notes: `VMCMainCal`'s
  own `CalculateMAll` call (27.34s of the 67.76s total) is actually the
  single largest sub-component, not `VMCMakeSample`'s `UpdateMAll`
  (12.19s) as the DGX Spark/Mac profiling alone had suggested. `StochasticOpt`
  (the actual SR matrix solve, using ScaLAPACK's `DPOSV` — confirmed
  active via `initBLACS`/`DPOSV` sub-timers) was only 0.57s — sampling
  and local-energy evaluation dominate total cost by roughly two orders
  of magnitude over the SR solve itself, in practice.

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
