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

This repo keeps three kinds of mVMC knowledge deliberately separate —
don't blend them:

- **This skill (mvmc-reference)**: what the code *is* and how it behaves —
  physics, input keywords, parallelization semantics, output formats.
- **benchmark-generator skill**: the CLI in this repo for generating
  `.inp`/job-script files.
- **mvmc-build skill** (and any future run/monitor tooling): building and
  executing the binary on a cluster.

**Important framing**: this repo's benchmark generator measures raw code
*throughput*, not physics. Real research runs use very different settings
(many SR steps, sublattice symmetry, particular fillings chosen for the
physics question at hand — see below) — that's expected and correct, not
something the generator should be made to imitate. Realistic-condition
knowledge below exists so you can *explain* the code accurately, not to
motivate changing the generator's defaults to match it.

For anything not covered here, don't try to reconstruct it from memory —
point at the sources instead:
- Official manual (v1.2.0 PDF, bundled alongside this file as
  `mVMC-1.2.0_en.pdf`; page-cite it) or the live version for newer syntax:
  https://issp-center-dev.github.io/mVMC/doc/master/en/index.html
- Community workflow/examples: https://github.com/issp-center-dev/mVMC-tutorial
- Source: https://github.com/issp-center-dev/mVMC

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

Background context for explaining the code accurately — not a spec for
what this repo's benchmarks should look like. Full detail:
https://github.com/issp-center-dev/mVMC-tutorial (hands-on slides and
sample scripts, 2017-2024).

- mVMC's reason to exist is going past what exact diagonalization (HΦ, the
  companion code from the same group) can reach — HΦ tops out around
  **~40 sites**; mVMC's own stated target is **~100-1000 sites**
  (`>10⁴` variational parameters in published applications). Anything
  small enough to exactly diagonalize is a validation case there, not a
  target size.
- The community workflow is finite-size scaling: validate a small lattice
  against HΦ, then rerun the same recipe at increasing `W`/`L`,
  extrapolating physical quantities across the whole size sequence — not
  one fixed "the" problem size. Real convergence also uses many more SR
  steps than a throughput benchmark needs (tutorial examples: `NVMCSample
  ~200`, `NSROptItrStep ~600`), and sublattice symmetry (`Wsub`/`Lsub`) to
  keep the SR method's parameter count tractable as size grows.
- A full research calculation is 3 steps — optimize (`NVMCCalMode=0`),
  compute Green's functions on the optimized wavefunction
  (`NVMCCalMode=1`), then Fourier-transform those into physical
  observables (manual ch. 9, `fourier`/`greenr2k`). This repo's generator
  only targets the first step, by design (see framing note above).

## Memory

The two things that blow up memory: per-rank Pfaffian arrays
(`O(NQPFull·Nsize²)`) and the SR method's `Nparam × Nparam` S-matrix.
Four documented/verified levers exist — `NSRCG=1` (iterative solve instead
of forming the S-matrix), `NStore=0` (drop the cached `⟨O_kO_l⟩` matrix,
trade speed for memory), `Wsub`/`Lsub` sublattice symmetry (shrinks
`Nparam` directly), and building with `-DUSE_SCALAPACK=ON` (distributes
the S-matrix solve — `stcopt_pdposv.c`, ScaLAPACK's `pdposv` — across MPI
ranks via BLACS instead of replicating it on every rank, unlike the
default `NSplitSize=1` MPI behavior above). See manual §4.5 (`NSRCG`,
`NStore`) and §2.2 (ScaLAPACK build) for exact semantics and flags.

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
