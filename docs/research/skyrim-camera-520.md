# Native stair-camera hill climb for issue #520

Recorded and evaluated on 2026-11-06. The search recovered spring base **0.001**
and damping **0.6** from the training stairs. That response fits the separate
held-out stairs, but the complete camera candidate is **rejected**: all three
jump runs fail the absolute-fit gate because the source camera node adds a
landing animation. Production camera code and defaults remain unchanged.

## Experiment and result

Eighteen original Skyrim runs cover six fixed routes, each repeated three times.
Six lower-stair runs train the model; twelve upper-stair, flat, and jump runs are
held out from parameter search. Scripted compositor input reaches native movement
and jump handlers, where press/release observations are recorded. The corpus has
5,836 paired camera/spring samples. No computer-use recording tool is needed.

A standalone Rust evaluator receives native player height and scaled camera dt,
starts at rest, and evolves its own state. The bounded Python hill climb evaluated
265 unique candidates. The selected parameters were written to `winner.json`
before held-out observations were decoded for model scoring. The measured native
settings were evaluated separately only after selection.

RMSE below is the median of three runs, in Creation units. Peak is the largest
absolute error across the three runs. The target is attached-camera height minus
player height minus the stationary eye offset.

| Fixture | Partition | Direct RMSE | 55 ms RMSE | Spring RMSE | Spring peak |
| --- | --- | ---: | ---: | ---: | ---: |
| Lower ascent | train | 1.246230 | 0.100289 | 0.000156 | 0.005483 |
| Lower descent | train | 1.504848 | 0.124709 | 0.000122 | 0.000391 |
| Upper ascent | held out | 1.108779 | 0.103613 | 0.000347 | 0.000563 |
| Upper descent | held out | 1.194618 | 0.117340 | 0.000341 | 0.000596 |
| Flat | held out | 0.004500 | 0.000500 | 0.000261 | 0.000611 |
| Jump / landing | held out | 5.832950 | 2.955051 | 2.434643 | 7.242430 |

Training baseline repeat spread was **0.004227** units, below the preregistered
minimum gain of **0.05**. Stair gains over the better baseline were 0.099810 and
0.124587 units on training ascent/descent, and 0.103267 and 0.116999 on held-out
ascent/descent. All four stair-gain checks pass.

All held-out cases must also meet RMSE ≤ 0.1, peak error ≤ 0.5, end bias ≤ 0.05,
and settling requirements. Flat/jump controls must stay within 0.1 units of the
better baseline's peak error. Only the three jump absolute-fit checks fail. The
jump candidate improves over both baselines, but that does not make it accurate
enough to pass the frozen threshold.

## What the native observations resolve

The controller byte at `+0x1c5` and spring weight were both **1** in every selected
sample, including ordinary walking, stairs, and jump/landing. The issue's zero
construction default therefore does not describe these gameplay samples.

The observed correction agrees with the two-state recurrence documented in the
[hill-climb guide](../../tools/skyrim-recorder/HILLCLIMB.md). Using each sample's
measured previous state, spring base, damping, and scaled dt, the maximum one-step
residual was **0.000001107** units. Attached-camera height equals source-node
height plus correction to within **0.0001221** units. These are diagnostics of the
native observations; the fitted model never consumes the observed future state.

The scaled timestep had median 0.0166667 seconds and range 0.0163333–0.0203333.
The largest adjacent wall-clock camera gap was 0.0288796 seconds. This supports
behavior at the sampled cadence; it does not establish arbitrary-framerate parity.

During landing, the source `Camera1st` node drops as much as **7.242432** units
relative to the player, after the spring is already close to rest. Supplying that
observed source-node motion as a diagnostic reduces the selected model's worst
jump error from **7.242430** to **0.000335** units. This locates the missing input;
it is not an accepted whole-camera model, because Mudcrab does not supply the
native animation motion. The spring-only prediction settles about 0.75–0.76 s
after W release; the native complete camera settles about 1.16–1.17 s after it.

## Boundaries and reproducibility

The direct baseline is relative-height equivalence to
`walk_camera_follow_system` at HEAD `1dcca42fc398baaf626e588694f9e08084117f11`.
The 55 ms baseline uses the response formula from open
[PR #511 at `41df866`](https://github.com/Mudcrab-Team/mudcrab/pull/511), applied to
all vertical changes. Its solver eligibility, fixed-tick event collection, and
resets are not reproduced. The evaluator uses f64 relative coordinates rather
than claiming bitwise native f32 parity.

Native player movement on these stairs is comparatively smooth. Feeding it into
a response evaluator isolates the camera law; it does not test Mudcrab's step
solver or prove a production integration. Neither GPU consumption, changing
spring gates, nor teleport/door behavior is established. Three repeats on one
runtime are a bounded comparison, not a general confidence interval.

The initial normalization window ended 1.5 s after release. It rejected the first
jump because the final half-second still contained the landing animation. Before
any parameter search, the window was extended to 1.9 s for every fixture. The raw
recordings already contained 2 s after release and were reused without alteration.
All model acceptance thresholds stayed unchanged. Survey pilots and failed
normalization attempts are excluded from fitting and retained locally.

- [Rerun and capture instructions](../../tools/skyrim-recorder/HILLCLIMB.md)
- [Frozen numerical corpus](../../tools/skyrim-recorder/reference/whiterun-v2/corpus.json)
- [Full result and gate outcomes](../../tools/skyrim-recorder/reference/whiterun-v2/result/report.json)
- [Winner and source hashes](../../tools/skyrim-recorder/reference/whiterun-v2/result/winner.json)
- [Every search trial](../../tools/skyrim-recorder/reference/whiterun-v2/result/trials.jsonl)
- [Original research issue #520](https://github.com/Mudcrab-Team/mudcrab/issues/520)

Validation: 25 Python checks and 3 Rust response checks pass; the native DLL builds
with warnings treated as errors. All 18 native runs pass input, route, timing,
spring-state, and stationary-tail validation. Original executable and save hashes
are checked separately after capture. No game binaries, saves, assets, or raw
screenshots are included in the numerical corpus.
