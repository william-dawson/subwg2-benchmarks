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
- **`ncond`** — **must be specified**; the total number of itinerant
  electrons (↑ + ↓ combined). `nelec` is a plain alias for the same field
  in StdFace's source. mVMC sets `Ne = (NLocSpin + ncond) / 2`, and for
  `FermionHubbard` (`NLocSpin=0`) that's just `Ne = ncond / 2`. **`ncond`
  does not scale with `W`/`L` automatically** — if you want a fixed physical
  density (e.g. half filling) across different lattice sizes, you must set
  `ncond` yourself proportional to `W*L`, and it must be even. `benchgen
  mvmc create` in this repo now defaults `ncond` to half filling (`W*L`,
  rounded down to even) for exactly this reason — earlier versions held it
  at a fixed 100 regardless of lattice size, which silently kept the actual
  matrix dimension (and thus the real compute cost) constant no matter what
  `W`/`L` you asked for.
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
- **OpenMP never touches the Markov chain loop itself.** The core
  Metropolis loop (`for(outStep...) for(inStep...) { CalculateNewPfM2(...);
  ... }` in `vmcmake.c`) is plain serial C — necessarily so, since each
  step depends on the accepted configuration from the previous one.
  `#pragma omp parallel for` only appears on (a) a few one-time array-reset
  loops outside that loop, and (b) inside the BLAS/LAPACK calls the loop
  invokes per step for Pfaffian/matrix updates. So OpenMP's only possible
  benefit is threaded BLAS inside each step's matrix update — and if the
  matrices are small relative to per-call thread-spawn overhead (true for
  small-to-moderate `W`/`L` in testing so far), adding threads makes things
  *slower*, not faster, dominated by kernel-level thread scheduling
  overhead. Default to `OMP_NUM_THREADS=1` unless you've specifically
  confirmed a larger benefit at your problem size.
- **Practical guidance for this project so far**: use MPI ranks for more
  statistics per wall-clock second, not for speed. Don't assume OpenMP
  threading helps without measuring at your specific `W`/`L` — the
  "linear-algebra-heavy enough to be worth threading" crossover has not yet
  been found empirically for any size tested to date.

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
