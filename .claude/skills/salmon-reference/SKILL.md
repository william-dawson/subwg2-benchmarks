---
name: salmon-reference
description: Reference for SALMON (Scalable Ab-initio Light-Matter simulator for Optics and Nanoscience) — the physics behind it, input-file keywords (Fortran namelists), parallelization model (nproc_k/ob/rgrid), and output files. Use whenever the user asks what a SALMON input keyword means, how SALMON parallelizes, what a SALMON output file contains, or anything else about how the code itself works (as opposed to building it — see the salmon-build skill for that).
---

# SALMON Reference

SALMON solves the time-dependent Kohn-Sham equation in real space and real
time (real-time TDDFT) with norm-conserving pseudopotentials, to compute
electron dynamics under a laser/EM field. It unifies two predecessor codes:
ARTED (U. Tsukuba, crystalline solids / periodic systems) and GCEED (IMS,
isolated molecules / nanostructures) — so SALMON handles both periodic and
isolated systems through the same input format. Apache 2.0 license.
Source: https://github.com/SALMON-TDDFT/SALMON2.

This repo keeps SALMON knowledge deliberately separate, mirroring the mVMC
split — don't blend them:

- **This skill (salmon-reference)**: what the code *is* and how it behaves —
  physics, input keywords, parallelization semantics, output formats.
- **benchmark-generator skill**: the CLI in this repo for generating
  input/job-script files (`src/benchmark_generator/salmon.py`).
- **salmon-build skill** (not yet written): building the binary on a given
  machine.
- **salmon-benchmarking skill** (not yet written): the empirical methodology
  for picking a problem size per machine, plus recorded results.

For anything not covered here, don't try to reconstruct it from memory —
point at the sources instead. **Don't bundle copies of any of these in this
repo** (copyright) — always link out. This skill was distilled from
`Manual_SALMON-v.2.2.2_simple_20250606.pdf` (177 pages), which the user
supplied locally for one-time reading; it is gitignored (`*.pdf`) and must
never be committed.

- Official manual (latest): https://salmon-tddft.jp/wp-content/manuals/manual_ver.html
  — the maintained web version; a downloadable "simple" PDF (like the one
  distilled here) is also linked from https://salmon-tddft.jp/. Cite section
  numbers against the version you actually have open.
- Source (dev branch): https://github.com/SALMON-TDDFT/SALMON2
- Dev manual source: https://github.com/SALMON-TDDFT/SALMON-DOCS
- Published-paper input database: https://github.com/SALMON-TDDFT/SALMON-inputs
  — real, citable input files for reproducing specific papers; a better
  source of "realistic" keyword combinations than guessing.
- Utilities (shape-file generation, animation post-processing):
  https://salmon-tddft.jp/utilities.html
- Key paper (cite if publishing benchmark results): Noda, Sato, Hirokawa,
  Uemoto, Takeuchi, Yamada, Yamada, Shinohara, Yamaguchi, Iida, Floss,
  Otobe, Lee, Ishimura, Boku, Bertsch, Nobusada, Yabana, "SALMON: Scalable
  Ab-initio Light-Matter simulator for Optics and Nanoscience", *Comp.
  Phys. Commun.* **235**, 356-365 (2019) — the software paper itself (both
  authors' repo-local copies read in full this session). Confirms:
  Fortran 2003, CMake ≥3.0.2 build (`python configure.py --arch=<ARCH>
  --prefix=<DIR> && make && make install`, `--disable-mpi` for serial),
  binary name `salmon.cpu` (or `salmon.mic` for Xeon Phi via
  `mpiexec.hydra`), run via `salmon.cpu < input.inp > out.log` (single
  node) or `mpiexec -n NPROC salmon.cpu < input.inp > out.log`.
  Parallelization-scheme detail beyond what's captured under `&parallel`
  below: ground-state calculations favor spatial (`nproc_rgrid`) division
  over orbital (`nproc_ob`) division because Gram-Schmidt orthogonalization
  is sequential across orbitals; time-propagation favors orbital division
  since each orbital propagates independently. Their own rule of thumb:
  assign nodes to a 2×2×2 spatial division and put the remainder into
  orbital parallelization once a system has ~200+ orbitals. An automatic
  process-assignment exists but only fires when total process count
  factors into 2/3/5 and `&parallel` is left unspecified.
- Hirokawa, Yamada, Yamada, Uemoto, Noda, Boku, Yabana, "Large-scale
  ab initio simulation of light-matter interaction at the atomic scale in
  Fugaku", *Int. J. High Perform. Comput. Appl.* **36**(2), 182-197
  (2022) — a **production SALMON run on Fugaku's A64FX**, using the exact
  physical system (amorphous SiO2 thin film) this repo already targets.
  Full detail folded into `salmon-benchmarking`'s Reference point section
  once that skill exists; the architecture-level facts below belong here
  since they're about how the code behaves, not one specific run.

## Two-stage workflow

Almost every real calculation is two SALMON runs, both reading a Fortran90
namelist from stdin (`salmon < input.nml > stdout.log`). **For
benchmarking purposes, the first stage is prep only — the TDDFT stage is
what we actually measure**; see `salmon-benchmarking`'s "The GS stage is
prep, not the benchmark" for why and how that shapes reported results.

1. **Ground-state DFT** (`&calculation/theory='dft'`): SCF loop to find the
   Kohn-Sham ground state. Writes restart data to `data_for_restart/`.
2. **Rename/copy** `data_for_restart/` → `restart/` (exactly what this
   repo's `create_job_script` in `salmon.py` does via `mv data_for_restart
   restart` between the two `mpiexec` calls).
3. **Time propagation** from that restart:
   - `theory='tddft_response'` — linear response via a weak impulsive
     field (`&emfield/ae_shape1='impulse'`); gives the frequency-dependent
     dielectric function / absorption spectrum from one run. This is what
     `create_input(..., tddft=True)` in `salmon.py` generates.
   - `theory='tddft_pulse'` — an explicit, physically realistic laser
     pulse (`ae_shape1` one of `Acos2/Acos3/Acos4/Acos6/Acos8/Ecos2`, plus
     `E_amplitude1`/`I_wcm2_1`, `tw1`, `omega1`, `phi_cep1`, etc. in
     `&emfield`) — for nonlinear response / pump-probe / HHG-type
     calculations, not just linear spectra.

`&calculation/theory` also has other values not covered above:
`'dft_md'` (ground state + ion dynamics), `'maxwell'` (pure
classical-EM FDTD, no electrons), `'multi_scale_maxwell_tddft'` /
`'single_scale_maxwell_tddft'` (couples TDDFT to a macroscopic FDTD light
propagation, for optically-thick samples — mostly `[Trial]` features),
`'maxwell_sbe'` (semiconductor Bloch equations coupled to Maxwell, a
cheaper approximation to full TDDFT for nanophotonics). All of these
except plain `dft`/`tddft_response`/`tddft_pulse` are out of scope for our
bulk-solid throughput benchmarking use case (see `&maxwell`/`&multiscale`/
`&singlescale[Trial]` note below) but are documented here for completeness
when a user asks.

## Namelist blocks that matter for benchmarking

Namelists (`&group ... /`) can appear in any order in the input file.
Everything below is `theory='dft'` / `'tddft_response'` unless noted.

### `&calculation`
- `theory` — see workflow above.
- `yn_md`, `yn_opt` — turn on ion dynamics / geometry optimization as an
  outer loop around the electronic structure (both `[Trial]`-adjacent
  features with their own `&md[Trial]`/`&opt[Trial]` blocks).

### `&control`
- `sysname` — prefix for all output file names.
- Restart/checkpoint options for resuming a `dft` SCF run or a `tddft_*`
  propagation from a previous run's dump.

### `&units`
- `unit_system` — `'au'` (atomic units, default) or `'A_eV_fs'`
  (Ångström/eV/femtosecond) for the whole input file.

### `&parallel` — the direct analogue of mVMC's `NSplitSize`
The MPI process grid is the product of five factors:

```
nproc_k * nproc_ob * nproc_rgrid(1) * nproc_rgrid(2) * nproc_rgrid(3) = total MPI processes
```

- `nproc_k` — parallelizes over k-points. Forced to 1 for isolated
  systems (`yn_periodic='n'`) and for `theory='maxwell'` (no electronic
  k-points at all there).
- `nproc_ob` — parallelizes over Kohn-Sham orbitals/bands. Forced to 1
  together with `nproc_k` for `theory='maxwell'`.
- `nproc_rgrid(1:3)` — parallelizes the real-space grid by domain
  decomposition, one factor per Cartesian direction.
- **Recommended tuning** (from the manual's parallelization guidance): if
  k-points > 1 and the real-space grid is small (below roughly 16³),
  prioritize `nproc_k` first. Otherwise prioritize `nproc_ob`, then
  `nproc_rgrid`, and once the grid reaches roughly 64³ or larger balance
  `nproc_ob` and `nproc_rgrid` together rather than maxing either one out
  first.
- Other knobs: `yn_fftw`, `yn_fftte` (parallel FFT backend choice),
  `yn_scalapack`, `yn_eigenexa` (distributed dense linear algebra for the
  SCF subspace diagonalization — turn on at large `nproc_ob`/system size,
  same rationale as mVMC's `-DUSE_SCALAPACK=ON`), `process_allocation`
  (how MPI ranks map onto the nproc_k/ob/rgrid grid vs. onto physical
  nodes/sockets).
- **`process_allocation` should differ by run stage**, per both the
  SALMON2 paper (§3.2) and the Fugaku production paper (§4.1): ground-state
  DFT communication is dominated by orbital-index traffic (Gram-Schmidt),
  so minimize the hop count in the orbital dimension — confine
  `nproc_ob`'s communicator within a node/socket where possible.
  Time-propagation (TDDFT) communication is dominated by spatial-grid
  traffic (halo exchange, density Allreduce, the Hartree-potential FFT),
  so there the node shape `(nproc_rgrid(1), nproc_rgrid(2),
  nproc_rgrid(3))` should be as close to a cube as the system permits, to
  minimize hop count on the torus/fabric — this is the opposite
  optimization target from the ground-state stage. Since a real workflow
  is always GS-then-TDDFT (see workflow above), the two stages may
  legitimately want different `&parallel` settings even within one
  physical run, not just one fixed process grid reused throughout.
- **A64FX-specific placement (relevant to `fx700`, and Fugaku itself)**:
  A64FX is organized as 4 CMGs (Core Memory Groups) per chip, each with 12
  cores + 8 GiB HBM2 and fast intra-CMG memory access but a slow
  inter-CMG NUMA network. The Fugaku production paper allocates **one MPI
  process per CMG** (4 processes/node) specifically to avoid crossing that
  slow inter-CMG link within a single rank's memory traffic — worth
  checking as a deployment default on `fx700` (which is the same A64FX
  chip), analogous to the socket-binding lessons already learned for
  mVMC on Rikyu (see `mvmc-benchmarking`).
- **FFT is a known weak-scaling bottleneck at large process counts.** The
  bundled FFTE library only does 2D block (y,z) parallelization of the 3D
  Hartree-potential FFT; the x-direction is handled by `MPI_Allgather`,
  which the Fugaku paper identifies as the single largest source of
  weak-scaling loss observed (elapsed FFT time grew the most of any
  component from 432 to 27,648 nodes). Don't expect the Hartree/FFT
  fraction of the timing breakdown to scale as cleanly as the Hamiltonian
  (stencil) fraction does when pushing node count up.
- **SALMON is memory-bandwidth-bound, not FLOP-bound, on A64FX** — worth
  knowing before interpreting any GFLOPS number from a benchmark run. The
  stencil (Hamiltonian) kernel's measured arithmetic intensity was
  ~2.68 Byte/Flop; A64FX's roofline ridge point is at 1024 GiB/s ÷ 3072
  GFLOPS ≈ 0.33 Byte/Flop, so **the maximum achievable fraction of peak
  FLOPS is bounded to roughly 0.33/2.68 ≈ 12.3%** regardless of code
  quality — the Fugaku paper's own single-node tuning reached 10.5%
  effective performance (322.72 GFLOPS out of 3072 GFLOPS peak, 84.5% of
  achievable memory bandwidth), and called that "close to the maximum
  that can be expected." A benchmark showing "only" ~10% of peak FLOPS on
  A64FX is not necessarily a red flag — check achieved memory bandwidth
  against the 1024 GiB/s hardware ceiling instead of judging by FLOPS
  alone.

### `&system`
- `yn_periodic` — `'y'` (crystal/solid) or `'n'` (isolated molecule).
  Gates which theory/parallel/poisson options are even legal, throughout
  the whole input.
- `al(3)` — orthorhombic cell edge lengths, **or** `al_vec1(3)`,
  `al_vec2(3)`, `al_vec3(3)` — general (non-orthogonal) cell vectors.
  Mutually exclusive with each other. `salmon.py`'s `create_input` uses
  `al_vec1/2/3` even for the (orthorhombic) SiO2 cell.
- `nelem`, `natom`, `nelec` — element count, atom count, total electron
  count (must match the sum of valence electrons implied by the chosen
  pseudopotentials).
- `nstate` — number of Kohn-Sham orbitals to solve for. Must be at least
  `nelec/2` (spin-unpolarized, doubly-occupied) to have a valid ground
  state, and in practice several extra empty/virtual states beyond that
  are usually included as a buffer for numerical stability. *Open item,
  not yet resolved against the exercise data*: `salmon.py` currently sets
  `nstate = nelec * 3 // 4`, which for typical `nelec` gives *fewer*
  states than the strict occupied-orbital count `nelec/2` would already
  need doubled — worth rechecking against a working crystalline-Si
  reference input (e.g. from SALMON-inputs) before relying on it for real
  benchmarking, since an undersized `nstate` would fail or silently
  misconverge SCF rather than just being slow.
- `spin` — `'unpolarized'`, `'polarized'`, `'noncollinear'` (the last
  gates the various `yn_out_*spin*`/`yn_out_mag*` analysis switches).
- `temperature` — electronic (Fermi-Dirac) temperature for the SCF
  occupation, relevant for metals/finite-temperature DFT.
- `yn_spinorbit` — spin-orbit coupling.
- `absorbing_boundary` — complex absorbing potential at the cell edge for
  isolated systems (prevents unphysical reflection of ejected density).

### `&atomic_red_coor` / `&atomic_coor`
Atom positions — reduced/fractional coordinates (`_red_coor`, what
`salmon.py` uses, natural for periodic cells) or Cartesian (`_coor`).

### `&pseudo`
- `izatom` — atomic number per species.
- `file_pseudo` — pseudopotential file path per species. Supported
  formats include ABINIT `.psp8` (pseudo-dojo — what this repo's `data/`
  directory already has for Si/O) among others.
- `lmax_ps`, `lloc_ps` — angular-momentum channel truncation / local
  channel choice for the pseudopotential.
- `psmask` — real-space masking function for the nonlocal projectors.

### `&functional`
- `xc` — `'PZ'` (Perdew-Zunger LDA), `'PZM'` (spin-polarized variant),
  `'TBmBJ'` (modified Becke-Johnson meta-GGA, better band gaps), or route
  through libxc via `alibx`/`alibc` for other functionals.
- `cval` — functional-specific parameter (e.g. for TBmBJ).
- Jellium runs (`&jellium/yn_jm='y'`) require `xc='pz'` specifically.

### `&rgrid` — the primary cost/sizing knob
- `dl(3)` — real-space grid spacing per direction (finer = more accurate,
  more expensive). **Mutually exclusive** with `num_rgrid`.
- `num_rgrid(3)` — number of real-space grid points per direction
  directly. `salmon.py`'s `create_input` computes this from a target
  spacing (`spacing=0.33 Å` default) via `ceil(cell_length / spacing)` —
  i.e. it always drives sizing through `num_rgrid`, never `dl`.
- This triple, together with `nelec`/`natom` (which set the number of
  bands/orbitals to propagate), is the main lever for scaling problem
  size up or down for benchmarking — directly analogous to mVMC's `W`/`L`.

### `&kgrid`
- `num_kgrid(3)` — k-point mesh dimensions for periodic systems. Forced
  to effectively 1 total k-point handling for isolated systems.
- `dk_shift` — Monkhorst-Pack-style shift off Γ.
- `file_kw` — read an explicit user-supplied k-point list instead.

### `&tgrid`
- `nt` — number of real-time propagation steps.
- `dt` — time step size.
- `gram_schmidt_interval` — how often orbitals are re-orthonormalized
  during propagation (numerical stability vs. cost trade-off).

### `&propagation`
- `n_hamil` — order of the Hamiltonian expansion used by the propagator.
- `propagator` — `'middlepoint'` (Crank-Nicolson-like, symmetric) or
  `'aetrs'` (approximate enforced time-reversal symmetry — typically
  faster per step).
- `yn_predictor_corrector`, `yn_fix_func` — propagator refinement
  switches.

### `&scf` — ground-state (`theory='dft'`/`'dft_md'`) SCF control
- `method_init_wf` — initial-orbital generation: `'gauss'` (single
  Gaussian per orbital, default) up through `'gauss10'` (ten Gaussians —
  more stable for very large systems) or `'random'`.
- `nscf` — max SCF iterations (default 300).
- `method_min` — orbital update method; only `'cg'` (conjugate gradient)
  is implemented.
- `ncg`, `ncg_init` — CG iteration counts per SCF step / for the first
  step.
- `method_mixing` — density/potential mixing: `'simple'`,
  `'simple_potential'`, `'simple_dm'` (spin density matrix, needs
  `yn_spinorbit='y'`), `'broyden'` (default, modified Broyden),
  `'pulay'`.
- `mixrate`, `nmemory_mb`/`alpha_mb` (Broyden), `nmemory_p`/`beta_p`
  (Pulay) — mixing-method parameters.
- `yn_auto_mixing`, `update_mixing_ratio` — automatic mixing-rate
  adjustment.
- `convergence` — what quantity triggers SCF convergence:
  `'rho_dne'` (density difference / nelec, default), `'norm_rho'`,
  `'norm_rho_dng'`, `'norm_pot'`, `'pot_dng'`.
- `threshold` — convergence threshold for whichever `convergence` metric
  (default `1d-17` a.u. for `rho_dne`).
- `yn_subspace_diagonalization` — subspace diagonalization during SCF
  (default on).
- `yn_preconditioning`, `alpha_pre` — low-filter preconditioning for the
  CG update (`theory='dft'` only).

### `&emfield` — the applied field, needed for `tddft_pulse`/`tddft_response`
- `ae_shape1`/`ae_shape2` — envelope of the first/second pulse:
  `'impulse'` (weak delta-function kick, linear response), `'Acos2'`
  through `'Acos8'` (cosⁿ envelope on the vector potential), `'Ecos2'`
  (cosine-squared envelope directly on the electric field — requires
  `phi_cep1` = 0.75 or 0.25 so the field's time integral vanishes),
  `'none'`.
- `e_impulse` — impulse magnitude, used only with `ae_shape1='impulse'`
  (what `salmon.py`'s `tddft=True` path relies on).
- `E_amplitude1`/`E_amplitude2` or `I_wcm2_1`/`I_wcm2_2` — field
  amplitude given either directly (energy/(length·charge)) or as
  intensity in W/cm² — mutually exclusive per pulse.
- `tw1`/`tw2` — pulse duration (edge-to-edge, not FWHM).
- `omega1`/`omega2` — mean photon energy.
- `epdir_re1/re2`, `epdir_im1/im2` — real/imaginary polarization unit
  vector components (both together give circular/elliptical
  polarization).
- `phi_cep1`/`phi_cep2` — carrier-envelope phase, in units of 2π.
- `t1_t2`, `t1_start` — inter-pulse delay / start-time shift.
- `num_dipole_source`, `vec_dipole_source`, `cood_dipole_source`,
  `rad_dipole_diele` — up to 2 point dipole sources mimicking optical
  near-fields (TDDFT-based theories only).

### `&analysis` — output/diagnostics selection
Large block of `yn_out_*` switches (mostly default `'n'`, opt-in) plus
matching `*_step` cadence controls. The ones most relevant to a
benchmarking-focused run:
- `yn_out_perflog` (default `'y'`) / `format_perflog` (`'stdout'`,
  `'text'`, `'csv'`) — **the performance-log output** most useful for
  parsing timing data out of a run, analogous to mVMC's
  `zvo_CalcTimer.dat`. Confirm the exact per-phase breakdown this
  produces once a real run is in hand (not yet verified empirically for
  SALMON in this repo).
- `out_rt_energy_step`, `yn_out_rt_energy_components` — total/component
  energy during propagation.
- `nenergy`, `de` — frequency-domain grid (used by
  `theory='tddft_response'` to produce the dielectric function/spectrum —
  the actual physics output of the linear-response workflow).
- `projection_option` — excited-state analysis by projecting onto
  ground-state (`'gs'`) or instantaneous (`'td'`) eigenstates.
- Many `yn_out_dns*`/`yn_out_psi`/`yn_out_elf`/`yn_out_dos*` switches for
  visualizing densities/orbitals/DOS — expensive I/O, leave off (`'n'`)
  for pure throughput benchmarking.

### `&poisson` (isolated systems only, `yn_periodic='n'`)
- `method_poisson` — `'cg'` (default), `'ft'` (Fourier), `'dirichlet'`.
- `layout_multipole`, `num_multipole_xyz`, `lmax_multipole` — multipole
  expansion setup for the Hartree potential boundary condition.
- `threshold_cg` — CG convergence threshold.

### `&ewald` (periodic systems only, `yn_periodic='y'`)
- `newald` — real-space neighbor-cell cutoff for the ion-ion Ewald sum
  (default 4).
- `aewald` — Ewald range-separation parameter.
- `cutoff_r`, `cutoff_g` — real-space / reciprocal-space cutoffs
  (auto-determined if left negative/default).

### `&opt[Trial]` / `&md[Trial]` / `&jellium`
Geometry optimization, ion molecular dynamics (NVE/NVT with Nose-Hoover),
and jellium-background calculations — all out of scope for a fixed-geometry
electronic-structure throughput benchmark, documented here only for
completeness.

### `&maxwell` / `&multiscale` / `&singlescale[Trial]`
Classical electromagnetic FDTD solver and its various couplings to TDDFT
(multiscale Maxwell-TDDFT for optically-thick media, single-scale variants,
nanoparticle/metasurface simulations via `shape_file`/`FDTD_make_shape`).
**Deliberately not distilled in depth here** — irrelevant to the simple
bulk-solid (SiO2) linear-response benchmark this repo targets; consult the
manual chapter 4 (`&maxwell`, `&multiscale`, `&singlescale[Trial]`)
directly if a future task needs nanophotonics/multiscale simulation.

## GPU caveat (relevant to qc-gh200 / Rikyu / DGX Spark benchmarking)

Per the manual: **the TDDFT propagation is well-tuned for GPU, but the DFT
(ground-state SCF) part is not.** Recommended practice is to run the
ground-state step on CPU and only the TDDFT propagation step on GPU — i.e.
the two-stage workflow above may legitimately want to run on two different
partitions/build configurations, not just two `mpiexec` calls in the same
job. Build-time `--arch` presets for GPU: `nvhpc-openacc` (recommended),
`nvhpc-openacc-cuda`, `nvhpc-openmp` (CPU-only via the NVHPC toolchain).

## Output files

- `data_for_restart/` — ground-state (or mid-propagation) checkpoint;
  must be renamed/copied to `restart/` to feed the next stage (see
  workflow above).
- Performance log — see `&analysis/yn_out_perflog`/`format_perflog` above;
  the analogue of mVMC's `zvo_CalcTimer.dat` for timing-based FOM
  extraction. Exact format/parsing not yet verified against a real run in
  this repo.
- `SYSname_*.data` family — `_sigma.data`/`_epsilon.data` (conductivity/
  dielectric function, `yn_out_gs_sgm_eps`), `_rt.data` (real-time
  observables), `_current_decomposed.data`, `_nex.data`/`_ovlp.data`
  (excited-state projection), `_trj.xyz` (ion trajectory), `_tm.data`
  (transition matrix elements) — each gated by its own `yn_out_*` switch
  in `&analysis`. `SYSname` is `&control/sysname`.
- 3D volumetric data (orbitals/density/ELF) in `'cube'` (default),
  `'avs'`, or `'vtk'` format per `&analysis/format_voxel_data`.

## Citation

SALMON is Apache 2.0. If benchmark results from this get published, cite:
Noda et al., "SALMON2: Scalable Ab-initio Light-Matter simulator for
Optics and Nanoscience", *Comp. Phys. Commun.* **235**, 356-365 (2019).
