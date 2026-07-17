---
name: mvmc-reference
description: Reference for mVMC (many-variable Variational Monte Carlo) — the physics behind it, Standard-mode input keywords, parallelization model (MPI vs OpenMP), and output file formats. Use whenever the user asks what an mVMC input keyword means, how mVMC parallelizes, what an mVMC output file contains, or anything else about how the code itself works (as opposed to building it — see the mvmc-build skill for that).
---

# mVMC Reference

mVMC (many-variable Variational Monte Carlo) optimizes a Pfaffian-Slater
variational wavefunction against a model Hamiltonian (Hubbard, Kondo
lattice, or Heisenberg spin) via the Stochastic Reconfiguration (SR)
method, using Markov-chain Monte Carlo sampling for expectation values.
Source: https://github.com/issp-center-dev/mVMC.

This skill covers the code itself — input keywords, parallelization
semantics, output formats. For actually building the binary, see the
**mvmc-build** skill. For generating benchmark `.inp` files, see the
**benchmark-generator** skill.

A copy of the official PDF manual (v1.2.0) ships alongside this file at
`mVMC-1.2.0_en.pdf` — page-cite it for anything below. For newer syntax or
anything this pinned copy doesn't cover, use the live manual:
https://issp-center-dev.github.io/mVMC/doc/master/en/index.html

## Two run modes

- **Standard mode** (`vmc.out -s input.inp`): a short, physics-level input
  file (the `StdFace` format — this is exactly what `benchgen mvmc create`
  in this repo generates) gets expanded internally into the full set of
  Expert-mode `.def` files, then run in one step.
- **Expert mode** (`vmc.out -e namelist.def`): hand-written/hand-edited
  `.def` files for arbitrary per-site control. `vmcdry.out input.inp` runs
  only the Standard→Expert expansion (no MPI, no calculation) if you want
  to inspect or edit the generated `.def` files before running.

## Standard-mode input keywords that matter for benchmarking

- `model` — `FermionHubbard`, `Spin`, `KondoLattice` (plus `...GC` grand-
  canonical variants that don't conserve electron number).
- `lattice` — `Chain Lattice`, `Square Lattice`, `Triangular Lattice`,
  `Honeycomb Lattice`, `Kagome`, `Ladder`.
- `W`, `L` — the size of the simulation cell (number of unit cells along
  each lattice vector). `Wsub`, `Lsub` optionally force pair-orbital
  symmetry under sublattice translation; default is no sublattice
  (`Wsub=W`, `Lsub=L`).
- **`ncond`** — StdFace's electron-count control (`nelec` is a plain alias
  for the same field). mVMC sets `Ne = (NLocSpin + ncond) / 2`, and for
  `FermionHubbard` (`NLocSpin=0`) that's just `Ne = ncond / 2` — this is the
  itinerant-electron count that sets `Nsize`, the actual matrix dimension
  driving VMC cost. **This repo's `create_input`/`benchgen mvmc create`
  does not let you set `ncond` at all** — filling is hardcoded to half
  filling (`ncond = W*L`, rounded down to even) so the real linear-algebra
  problem size always scales predictably with `W`/`L`, and the FOM formula
  in `fom.py` can derive `Nsize` from `W*L` without needing to parse
  `ncond` out of the file. Passing `ncond` to `create_input` raises
  `TypeError`; change `W`/`L` instead. (An earlier version of this tool
  exposed `ncond` as a tunable defaulting to a fixed 100 regardless of
  lattice size, which silently decoupled `W`/`L` from the actual compute
  cost — that's why it was removed rather than just fixed to default
  correctly.) `ncond` is omitted entirely for `Spin`-family models, since
  StdFace hard-errors (`StdFace_exit`) if it's specified where there's no
  itinerant-electron sector.
- `NVMCSample` — Monte Carlo samples per optimization step **per MPI rank**
  (see parallelization below). mVMC's own documented default is 1000; this
  repo's CLI defaults to 4000.
- `NSROptItrStep` — number of SR optimization steps. mVMC's own documented
  default is 1000; this repo's CLI defaults to 1 (deliberately, to keep a
  single benchmark run short — one step's cost is representative, since
  each step does the same amount of work).
- `2Sz` — total Sz quantum number (default 0).
- `NVMCCalMode` — `0` (default): optimize variational parameters. `1`:
  compute physical quantities/Green's functions from an already-optimized
  wavefunction.

## Parallelization: MPI ranks vs OpenMP threads

This is the single most surprising thing about mVMC's performance model,
found by direct source inspection (`src/mVMC/vmcmain.c`) — read this before
trying to draw scaling conclusions from a benchmark.

- **MPI ranks do not split the work of one Markov chain by default.** In
  `vmcmain.c`, ranks are grouped by `group1 = rank0 / NSplitSize`; with the
  default `NSplitSize=1`, every rank is its own group of size 1, so each
  rank independently runs the *entire* `NVMCSample`-length Markov chain and
  results are only averaged together afterward (`WeightAverageWE` over the
  full communicator). More ranks at the default `NSplitSize` buys you more
  independent statistical samples in the same wall time, **not** a faster
  time-to-solution for a fixed sample count. `NSplitSize` (documented:
  "the number of processes of MPI parallelization") is the actual knob that
  would make ranks split a single chain's sampling work — untested in this
  project so far.
- **The Markov chain walk itself is serial**, necessarily so (each step
  depends on the accepted configuration from the previous one) — but three
  different functions called from inside that walk *do* use
  `#pragma omp parallel for`, all over the same `qpidx` loop
  (`NQPFull`, 8 by default), with very different work-per-call vs.
  call-frequency tradeoffs:

  | Function | Per-call cost | Called | Effect of threading |
  |---|---|---|---|
  | `CalculateNewPfM2` (`pfupdate.c`) | O(`Nsize`) | every trial move (~`NVMCSample·Nsite` times/step) | overhead-dominated, hurts |
  | `UpdateMAll` (`pfupdate.c`) | O(`Nsize²`) | every accepted move (~half of trials) | still overhead-dominated, hurts |
  | `CalculateMAll_fcmp` (`matrix.c`, via PFAPACK's `M_ZSKTRF`) | O(`Nsize³`) | once per SR step, **plus** a periodic from-scratch recompute every time accepted moves since the last one exceed `Nsite` (`if(nAccept>Nsite)` in `vmcmake.c`) — so really ~`0.5·NVMCSample` times/step | genuinely benefits from threading, up to 8-way |

  Net effect measured so far (DGX Spark, Mac, multiple `W`/`L`): total wall
  time gets *worse* with more `OMP_NUM_THREADS`, because the first two
  functions are invoked far more often than the third and their overhead
  dominates. This is not "mVMC doesn't use OpenMP well" — one of the three
  call sites is doing exactly the right thing; it's just outweighed.
- **Practical guidance for this project so far**: use MPI ranks for more
  statistics per wall-clock second, not for speed (see above — ranks don't
  reduce wall time by default either). Default to `OMP_NUM_THREADS=1`
  unless you've specifically measured a benefit at your problem size — no
  configuration tested so far (several `W`/`L` values up to `14×14`, two
  different machines, two different compiler/BLAS stacks) has shown net
  positive OpenMP scaling. In principle a large enough `Nsize` should tip
  the balance toward `CalculateMAll`'s O(`Nsize³`) term dominating, but
  that crossover hasn't been located, and per the tutorial material below,
  real mVMC problem sizes (100-1000 sites) go well beyond anything tested
  here — so this is a real open question, not a closed one.

## How big are real problems, and how do people scale up?

Sourced from https://github.com/issp-center-dev/mVMC-tutorial (hands-on
slides and sample scripts, 2017-2024) — this is the actual community
workflow, not just the manual's parameter reference.

- **The whole point of mVMC is to go past what exact diagonalization can
  reach.** HΦ (the companion exact-diagonalization code from the same
  group) tops out around **~40 sites** — exponential Hilbert-space growth.
  mVMC's own stated target range is **~100-1000 sites**, with published
  applications using `>10⁴` variational parameters (2024 tutorial slides).
  Anything you can exactly diagonalize is a *validation* case, not a
  target size.
- **The standard workflow is finite-size scaling, not one fixed problem
  size**: (1) pick a small lattice small enough for HΦ to exactly
  diagonalize the same Hamiltonian, (2) run mVMC on it with your intended
  settings (model, `NVMCSample`, `NSROptItrStep`, sublattice symmetry) and
  confirm the optimized energy matches HΦ's exact answer, (3) rerun the
  *identical* recipe at increasing `W`/`L` — the tutorial literally shows
  this as "copy the directory, edit one number" (`L4_1D_Heisenberg` →
  `L8_1D_Heisenberg` → ...) — up to whatever size the compute budget
  allows, (4) extrapolate physical quantities across the whole size
  sequence toward the thermodynamic limit. There is no single "the"
  problem size in real usage; there's a validated small case and a
  sequence of production sizes analyzed together.
- **Real convergence needs many SR steps, not one.** The tutorial's own
  worked examples use `NVMCSample=200` with `NSROptItrStep=600` — a nearly
  inverted ratio from this repo's CLI defaults (`NVMCSample=4000`,
  `NSROptItrStep=1`). That's not a discrepancy to fix: this repo's tool is
  a *throughput* benchmark (one step is fully representative of every
  other step's cost, see the FOM discussion below), not a physics
  calculation — but if anyone asks what a real, convergent run looks like,
  it looks like the tutorial's numbers, not this tool's defaults. People
  judge convergence by plotting energy (`xxx_out_yyy.dat`) vs. SR step and
  watching it plateau, and judge accuracy from the variance column
  (`(⟨H²⟩-⟨H⟩²)/⟨H⟩²`, which → 0 only for an exact eigenstate — VMC is not
  exact, so it stays small but finite).
- **Sublattice symmetry (`Wsub`/`Lsub`) is used aggressively even at small
  sizes** — e.g. `Wsub=Lsub=2` on a 4×4 lattice in the tutorial's own
  examples — specifically to cap the number of independent variational
  parameters (and thus the `O(Nparam²)` SR-solve memory/cost) as `W`/`L`
  grow. This repo's CLI currently always defaults `Wsub=W`, `Lsub=L` (no
  reduction) — worth knowing that's not how real large-scale runs are
  typically configured.
- **A full research calculation is three steps**, only the first of which
  this repo's benchmark generator exercises: (1) optimize the wavefunction
  (`NVMCCalMode=0`, what `benchgen mvmc create` targets), (2) recompute
  one- and two-body Green's functions on the optimized wavefunction
  (`NVMCCalMode=1`, needs `zqp_opt.dat` from step 1 as input), (3)
  Fourier-transform those into physical observables (structure factors,
  correlation functions) via the `fourier`/`greenr2k` utility (chapter 9 of
  the manual) or post-processing scripts. Worth knowing when deciding
  whether a benchmark that only does step 1 is representative enough of
  what a real user's wall-clock time is actually spent on.

## Memory

The two things that actually blow up memory are the per-rank Pfaffian
arrays (`O(NQPFull · Nsize²)`) and the SR method's `Nparam × Nparam`
S-matrix. Documented/verified levers, roughly in the order people reach
for them:

- **`NSRCG=1`** — solves `S·x=g` iteratively (conjugate gradient) instead
  of explicitly forming and factoring the S-matrix. Manual: reduces memory
  from `O(Np²)+O(Np·N_MCS)` to `O(Np)+O(Np·N_MCS)`. Pure memory win, more
  CG iterations in exchange.
- **`NStore=0`** — the default (`NStore=1`) caches `⟨O_k O_l⟩` products as
  an explicit matrix for speed, costing `O(Np²)+O(Np·N_MCS)`; turning it
  off drops back to `O(Np²)` at a speed cost.
- **`Wsub`/`Lsub` sublattice symmetry** — directly shrinks `Nparam` without
  shrinking the physical lattice (see above) — the standard way real large
  runs stay tractable, not just a memory-crisis fallback.
- **Build with `-DUSE_SCALAPACK=ON`** — distributes the S-matrix solve
  (`stcopt_pdposv.c`, ScaLAPACK's `pdposv`) across MPI ranks via BLACS
  block-cyclic layout instead of replicating it on every rank. This is the
  "add more nodes to fit a bigger problem" lever, and unlike the default
  `NSplitSize=1` MPI behavior (redundant independent chains, no memory
  sharing — see parallelization above), it genuinely reduces per-rank
  memory for the dominant term.

## Output files (in the `output/` directory)

| File | Contents |
|---|---|
| `***_opt.dat` | Final optimized variational parameters + energy |
| `xxx_var_yyy.dat` | Variational parameters/energy at each SR step |
| `xxx_out_yyy.dat` | `⟨H⟩, ⟨H²⟩, (⟨H²⟩-⟨H⟩²)/⟨H⟩², ⟨Sz⟩, ⟨(Sz)²⟩` per bin |
| `xxx_CalcTimer.dat` | Wall-clock time per named phase, e.g. `All`, `VMCParaOpt`, `VMCMakeSample` — this is what `benchgen fom mvmc` parses (looks for the `All` line) |
| `xxx_time_zzz.dat` | Per-sample Monte Carlo acceptance ratios and timestamps |
| `xxx_cisajs_yyy.dat` | One-body Green's function ⟨c†c⟩ |
| `xxx_cisajscktalt_yyy.dat` | Two-body Green's function / correlation functions |

`***`/`xxx` are the `CParaFileHead`/`CDataFileHead` prefixes (default `zqp`/
`zvo`); `yyy`/`zzz` are run-numbering suffixes from `NDataIdxStart`.

## Citation

mVMC is GPL v3. If benchmark results from this get published, cite:
Misawa, Morita, Yoshimi, Kawamura, Motoyama, Ido, Ohgoe, Imada, Kato,
*Comp. Phys. Commun.* **235**, 447-462 (2019).
