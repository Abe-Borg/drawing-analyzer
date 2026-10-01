# Check cost and useful output

The normal workflow is Windows GUI basic sheet analysis, with occasional QC.
Synthetic benchmarks check mechanical behavior; they cannot establish what a
real model sees or whether a review improved. A private live comparison is
agreed in principle, but **no spending budget has been authorized**. Do not run
billable checks until the owner supplies a written limit and approved drawings.

## Smallest useful comparison

Use four representative vector sheets from one private set: a dense schedule,
a typical plan, a detail/riser and a sheet with a known discrepancy. Include
at least two disciplines. Keep them local; do not commit PDFs, output or keys.
Record three known facts/problems before seeing either version's results.

Compare `v1.7.0` with an exact candidate commit in separate installations.
Use basic analysis, Economy, identical focus/specification/profile settings and
separate fresh test caches: set `DRAWING_ANALYZER_CACHE_PATH` to a new private
file path before launching each installation. Keep normal caches untouched. Pin the same supported
review model in both, for example `DRAWING_ANALYZER_MODEL=claude-opus-5`;
record any other requested models, effort and rendering overrides. Default models
changed after 1.7.0, so comparing defaults alone mixes model and code changes.

Run each version once and Export All to separate private folders. Record:

- sheets completed, crashes, failed/partial warnings and unexpected omissions;
- wall time, transport, model IDs, token usage, app estimate and provider charges;
- ten sampled extracted facts/findings checked against the source sheets;
- the three known problems: found, wrong, or missed; relevant anchoring/location.

Basic runs do not produce reviewed PDFs. If occasional QC still needs checking,
make a separate, budgeted two-sheet QC comparison and inspect the marked-up PDF
and HTML in the owner's usual viewer. Do not turn the first check into a full
mode/viewer/discipline matrix.

At an observed $4/sheet, eight initial sheet reads suggest about **$32**, plus
retries/follow-ups and any optional QC. This is a planning allowance, not a quote
or approved budget. Economy may reduce eligible token charges; measure the actual
set. The app has no global spending cutoff. Stop starting work before exhausting
the authorized allowance, and account for provider work already accepted.

Pause release work for lost sheets/findings, wrong source locations, key exposure
or unexplained extra spend. Keep a change that repairs one of those despite no
finding-count increase. If basic output is equivalent and cost is unchanged,
stop speculative QC/prompt work and target the measured expense. Fewer findings
alone do not demonstrate quality or savings; model output varies. Repeat only
an ambiguous result that would change a decision, with a separate allowance.

## Existing local tools

A free synthetic smoke benchmark:

```powershell
python scripts/benchmark_drawing_analyzer.py --check --sheets 4 --repeats 1
```

Its timings and fake replies are not live cost/quality evidence. The benchmark's
`--live` option is billable and performs cold/warm runs; it does not compare
repository versions. `scripts/ab_sweep_drawing_analyzer.py --help` describes
same-version configuration experiments; use `--estimate` for local pricing and
`--no-exhaustive` for basic analysis. Omitting `--estimate` can spend money.
`ab_findings_diff.py` supports that harness's finding comparison; there is no
separate command-line interface for comparing two application versions.

Use the GUI and exported records for the version comparison above. Keep the
short measured result in the PR/release evidence, with what actually ran and
what remains unknown; do not maintain a growing benchmark diary here.
