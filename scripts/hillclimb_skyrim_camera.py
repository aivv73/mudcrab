#!/usr/bin/env python3
"""Capture a frozen native corpus and hill-climb conditional camera responses for #520."""
import argparse
import contextlib
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys

from record_skyrim_motion import ROOT, read_fixture, read_trace, sha256, verify_trace

MODEL_SOURCE = ROOT / 'tools/skyrim-recorder/camera_response.rs'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def read_plan(path):
    plan = json.loads(path.read_text())
    require(plan['schema'] == 1 and plan['repeats'] >= 3, 'Need schema 1 and at least three repeats')
    cases = plan['cases']
    require(len({c['name'] for c in cases}) == len(cases), 'Duplicate fixture names')
    for split in ('train', 'heldout'):
        require({'ascent', 'descent'} <= {c['kind'] for c in cases if c['split'] == split},
                f'{split} needs both stair directions')
    require({'flat', 'jump'} <= {c['kind'] for c in cases if c['split'] == 'heldout'}, 'Missing held-out controls')
    for case in cases:
        require(case['kind'] != 'survey' and case['split'] in ('train', 'heldout'), 'Unsealed survey case')
        require(case['name'].replace('-', '').isalnum(), 'Invalid fixture name')
        for key in ('progress_range', 'rise_range', 'height_range', 'start_z_range'):
            lo, hi = case[key]
            require(math.isfinite(lo) and math.isfinite(hi) and lo <= hi, f'Invalid {key}')
    return plan


def native_pair(rows, code, action):
    events = [r for r in rows if r['kind'] == 2 and r['code'] == code and r['text'] == action and r['state'] == 0]
    down = [r for r in events if r['values'][0] > 0 and r['values'][1] == 0]
    up = [r for r in events if r['values'][0] == 0 and r['values'][1] > 0]
    require(len(down) == len(up) == 1, f'Missing unique native {action} press/release')
    return down[0], up[0]


def export_run(directory, case, plan):
    proof = json.loads((directory / 'proof.json').read_text())
    require(sha256(directory / 'trace.bin') == proof['trace_sha256'], 'Native trace hash changed')
    require(proof['fixture'] == case, 'Captured fixture differs from frozen plan')
    session = proof['session']
    require(session['exe_sha256'] == plan['runtime_sha256'], 'Runtime mismatch')
    require(session['source_save_sha256'] == plan['source_save_sha256'], 'Save mismatch')
    rows = read_trace(directory / 'trace.bin')
    verify_trace(rows)
    require(rows[0]['text'] == 'mudcrab-motion-256-v2', 'Spring observations require recorder v2')
    frequency = rows[0]['sample']
    down, up = native_pair(rows, 17, 'Forward')
    held = (up['qpc'] - down['qpc']) / frequency
    require(abs(held - case['hold_ms'] / 1000) < 0.15, 'Received hold differs from fixture')
    if case['kind'] == 'jump':
        jump_down, jump_up = native_pair(rows, 57, 'Jump')
        require(abs(jump_down['qpc'] - down['qpc']) / frequency < 0.1 and
                jump_down['qpc'] < jump_up['qpc'], 'Jump is not paired with the movement pulse')
    else:
        require(not any(r['kind'] == 2 and r['text'] == 'Jump' for r in rows), 'Unexpected jump input')
    spring_rows = [r for r in rows if r['kind'] == 6]
    springs = {r['sample']: r for r in spring_rows}
    require(len(springs) == len(spring_rows), 'Duplicate spring sample')
    frames = [r for r in rows if r['kind'] == 3 and
              -plan['pre_roll_seconds'] <= (r['qpc'] - down['qpc']) / frequency <= held + plan['post_roll_seconds']]
    require(len(frames) > 60, 'Too few native samples')
    times = [(r['qpc'] - down['qpc']) / frequency for r in frames]
    require(times[0] < -plan['pre_roll_seconds'] + 0.05 and times[-1] > held + plan['post_roll_seconds'] - 0.05,
            'Insufficient pre-roll or settling tail')
    require(all(0 < b - a <= plan['max_gap_seconds'] for a, b in zip(times, times[1:])), 'Camera time gap')
    require(all(b['sample'] == a['sample'] + 1 for a, b in zip(frames, frames[1:])), 'Missing camera update')
    pre = [r for r, t in zip(frames, times) if t < 0]
    start = pre[-1]['values'][:3]
    end = frames[-1]['values'][:3]
    require(max(math.dist(r['values'][:3], start) for r in pre) < 1, 'Preroll player is moving')
    offsets = [r['values'][14] - r['values'][2] for r in pre]
    require(max(offsets) - min(offsets) < 0.02, 'Preroll camera has not settled')
    eye_offset = statistics.median(offsets)
    require(math.dist(start[:2], case['position'][:2]) < 5, 'Wrong start position')
    require(case['start_z_range'][0] <= start[2] <= case['start_z_range'][1], 'Wrong start surface')
    yaw = math.radians(case['yaw_degrees'])
    forward = [math.sin(yaw), math.cos(yaw)]
    progress = [(r['values'][0] - start[0]) * forward[0] +
                (r['values'][1] - start[1]) * forward[1] for r in frames]
    lateral = [(r['values'][0] - start[0]) * forward[1] -
               (r['values'][1] - start[1]) * forward[0] for r in frames]
    require(max(map(abs, lateral)) < case['corridor_half_width'], 'Left the surveyed route corridor')
    require(case['progress_range'][0] <= progress[-1] <= case['progress_range'][1], 'Wrong route progress')
    heights = [r['values'][2] for r in frames]
    rise = end[2] - start[2]
    height_range = max(heights) - min(heights)
    require(case['rise_range'][0] <= rise <= case['rise_range'][1], 'Wrong signed vertical traversal')
    require(case['height_range'][0] <= height_range <= case['height_range'][1], 'Wrong vertical excitation')
    if case['kind'] in ('ascent', 'descent'):
        require(height_range >= 40 and abs(rise) >= 40, 'Flat/no-motion trace cannot count as stairs')
    if case['kind'] == 'jump':
        require(max(heights) - start[2] >= 40 and abs(rise) < 2, 'Jump did not leave and return to its floor')
    samples = []
    boundary_errors = []
    recurrence_errors = []
    for frame, t, distance in zip(frames, times, progress):
        require(frame['state'] == 0 and frame['code'] & 3 == 3, 'Not a valid first-person camera sample')
        require(abs(math.remainder(frame['values'][5] - yaw, 2 * math.pi)) < 0.01, 'Heading changed')
        spring = springs.get(frame['sample'])
        require(spring and spring['code'] == 3 and spring['input_sequence'] == frame['input_sequence'],
                'Missing/unpaired spring state')
        v, s = frame['values'], spring['values']
        require(all(math.isfinite(x) for x in v + s), 'Nonfinite native observation')
        dt = s[32]
        require(0 < dt <= 0.1 and abs(s[17] - dt) < 1e-7, 'Invalid or changing native camera timestep')
        require(s[16] == s[31] == 1 and abs(s[15] - 1) < 1e-6 and abs(s[30] - 1) < 1e-6,
                'Native gate/weight is outside the fitted weight-one regime')
        boundary_errors.append(v[14] - s[29] - s[26])
        recurrence_errors.append(s[26] - (s[36] ** dt * (s[5] - v[2]) + s[37] * dt * s[8]))
        samples.append(dict(time=t, game_dt=dt, player=v[2] - start[2],
                            reference=v[14] - v[2] - eye_offset, progress=distance,
                            native_correction=s[26], native_velocity=s[23],
                            camera_input=s[29] - v[2], sample=frame['sample']))
    require(max(map(abs, boundary_errors)) < 0.002, 'NiCamera does not match observed source node plus correction')
    require(max(map(abs, recurrence_errors)) < 0.002, 'Native spring recurrence observation disagrees')
    tail = [r for r, t in zip(frames, times) if t > times[-1] - 0.5]
    require(max(math.dist(r['values'][:3], end) for r in tail) < 1, 'Player has not stopped/landed')
    require(max(abs(s['reference']) for s in samples if s['time'] > times[-1] - 0.5) < 0.05,
            'Native camera has not settled before trace end')
    return dict(schema=1, fixture=case, hold_seconds=held, eye_offset=eye_offset, samples=samples,
                validation=dict(rise=rise, height_range=height_range, progress=progress[-1],
                                spring_boundary_peak=max(map(abs, boundary_errors)),
                                spring_recurrence_peak=max(map(abs, recurrence_errors)),
                                controller_gate=1, spring_weight=1),
                provenance=dict(trace_sha256=proof['trace_sha256'], exe_sha256=session['exe_sha256'],
                                save_sha256=session['source_save_sha256'], recorder=session['build'],
                                input_sha256=session['input_sha256'], runner_sha256=proof['runner_sha256'],
                                proton_sha256=session['proton_sha256'],
                                before_sha256=sha256(directory / 'before.png'), after_sha256=sha256(directory / 'after.png')))


def capture(plan_path, session, output, ocr_prefix):
    plan = read_plan(plan_path)
    output.mkdir(parents=True, exist_ok=True)
    frozen = output / 'plan.json'
    if frozen.exists():
        require(json.loads(frozen.read_text()) == plan, 'Cannot resume with a changed plan')
    else:
        write_json(frozen, plan)
    session_config = json.loads((session / 'session.json').read_text())
    receipt = output / 'capture-source.json'
    identity = {'session_sha256': sha256(session / 'session.json'), 'plan_sha256': sha256(frozen),
                'recorder_source_sha256': sha256(ROOT / 'tools/skyrim-recorder/probe.cpp'),
                'runner_sha256': sha256(ROOT / 'scripts/record_skyrim_motion.py'),
                'normalizer_sha256': sha256(Path(__file__))}
    if receipt.exists():
        require(json.loads(receipt.read_text()) == identity, 'Capture source changed during campaign')
    else:
        write_json(receipt, identity)
    assets_path = output / 'assets.json'
    if not assets_path.exists():
        data = Path(session_config['source_game']) / 'Data'
        write_json(assets_path, {name: sha256(data / name) for name in
                                ['Skyrim.esm', 'Skyrim - Meshes0.bsa', 'Skyrim - Meshes1.bsa']})
    (output / 'runs').mkdir(exist_ok=True)
    (output / 'raw').mkdir(exist_ok=True)
    entries = []
    # Interleave routes by repetition to expose session/order drift.
    for repeat in range(plan['repeats']):
        for case in plan['cases']:
            name = f"{case['name']}-{repeat + 1}"
            normalized = output / 'runs' / (name + '.json')
            fixture_path = output / 'raw' / (case['name'] + '.json')
            write_json(fixture_path, case)
            read_fixture(fixture_path)
            if not normalized.exists():
                attempts = sorted(p for p in (output / 'raw').glob(name + '-attempt-*') if p.is_dir())
                completed = [p for p in attempts if (p / 'proof.json').exists()]
                if completed:
                    raw = completed[-1]
                else:
                    raw = output / 'raw' / f'{name}-attempt-{len(attempts) + 1}'
                    with (output / 'raw' / f'{raw.name}.log').open('w') as log:
                        subprocess.run([sys.executable, str(ROOT / 'scripts/record_skyrim_motion.py'),
                                        'run', '--session', str(session), '--output', str(raw),
                                        '--ocr-prefix', str(ocr_prefix), '--fixture', str(fixture_path)],
                                       stdout=log, stderr=subprocess.STDOUT, check=True)
                run = export_run(raw, case, plan)
                run['repeat'] = repeat + 1
                run['name'] = name
                write_json(normalized, run)
                print(f'Accepted {name}: {len(run["samples"])} native camera samples', flush=True)
            else:
                run = json.loads(normalized.read_text())
                require(run['fixture'] == case and run['repeat'] == repeat + 1, 'Existing normalized run changed')
            entries.append(dict(name=name, fixture=case['name'], kind=case['kind'], split=case['split'],
                                repeat=repeat + 1, path=str(normalized.relative_to(output)), sha256=sha256(normalized)))
    write_json(output / 'corpus.json', dict(schema=1, plan=plan, plan_sha256=digest_json(plan),
                                          assets=json.loads(assets_path.read_text()), runs=entries,
                                          capture_source=identity))
    print(f'Corpus complete: {output / "corpus.json"}', flush=True)


def load_corpus(path):
    corpus = json.loads(path.read_text())
    require(corpus['schema'] == 1 and digest_json(corpus['plan']) == corpus['plan_sha256'], 'Corpus plan hash changed')
    plan = corpus['plan']
    entries = corpus['runs']
    require(len({e['name'] for e in entries}) == len(entries), 'Duplicate corpus run')
    for case in plan['cases']:
        matches = [e for e in entries if e['fixture'] == case['name']]
        require(sorted(e['repeat'] for e in matches) == list(range(1, plan['repeats'] + 1)), 'Incomplete repeat group')
        require(all(e['split'] == case['split'] and e['kind'] == case['kind'] for e in matches), 'Split assignment changed')
    require(len(entries) == len(plan['cases']) * plan['repeats'], 'Unexpected corpus membership')
    for entry in entries:
        source = (path.parent / entry['path']).resolve()
        require(source.is_relative_to(path.parent.resolve()), 'Corpus path escapes its directory')
        require(sha256(source) == entry['sha256'], 'Corpus observation hash changed')
    return corpus


def load_partition(path, corpus, split):
    runs = []
    for entry in corpus['runs']:
        if entry['split'] != split:
            continue
        run = json.loads((path.parent / entry['path']).read_text())
        case = next(c for c in corpus['plan']['cases'] if c['name'] == entry['fixture'])
        require(run['fixture'] == case, 'Normalized fixture changed')
        require(run['name'] == entry['name'] and run['repeat'] == entry['repeat'], 'Run identity mismatch')
        require(len(run['samples']) > 60, 'Empty normalized run')
        require(all(math.isfinite(s[k]) for s in run['samples'] for k in ('time', 'game_dt', 'player', 'reference')), 'Nonfinite normalized data')
        runs.append(run)
    return runs


class Replay:
    def __init__(self, binary, runs, path):
        with path.open('w') as stream:
            for index, run in enumerate(runs):
                for s in run['samples']:
                    stream.write('\t'.join(map(str, [index, s['time'], s['game_dt'], s['player'], s['reference']])) + '\n')
        self.process = subprocess.Popen([str(binary), str(path)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def evaluate(self, model, a=0.0, b=0.0, *, curves=False):
        self.process.stdin.write(f'{model} {a:.17g} {b:.17g} {int(curves)}\n')
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        require(bool(line), 'Rust response failed: ' + (self.process.stderr.read() if not line else ''))
        return json.loads(line)['runs']

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=10)
        self.process.stdout.close()
        error = self.process.stderr.read()
        self.process.stderr.close()
        require(self.process.returncode == 0, 'Rust response exited unsuccessfully: ' + error)


def aggregate(runs, metrics):
    groups = {}
    for run, metric in zip(runs, metrics):
        groups.setdefault(run['fixture']['name'], []).append(metric['rmse'])
    return statistics.mean(statistics.median(values) for values in groups.values())


def hill_climb(evaluate, seed, steps, minimum, bounds):
    point = tuple(seed)
    value = evaluate(point)
    steps = list(steps)
    while any(step >= floor for step, floor in zip(steps, minimum)):
        neighbors = []
        for dimension, step in enumerate(steps):
            for direction in (-1, 1):
                proposed = list(point)
                lo, hi = bounds[dimension]
                proposed[dimension] = min(hi, max(lo, proposed[dimension] + step * direction))
                p = tuple(proposed)
                if p != point:
                    neighbors.append((evaluate(p), p))
        best = min(neighbors, default=(value, point))
        if best[0] < value - 1e-12:
            value, point = best
        else:
            steps = [step / 2 for step in steps]
    return value, point


def end_bias(run, metric):
    stop = run['samples'][-1]['time'] - 0.5
    errors = [p - s['reference'] for p, s in zip(metric['prediction'], run['samples']) if s['time'] > stop]
    return abs(statistics.mean(errors))


def settling(run, values, threshold=0.05):
    samples = run['samples']
    last_outside = max((s['time'] for s, value in zip(samples, values)
                        if s['time'] >= run['hold_seconds'] and abs(value) > threshold), default=run['hold_seconds'])
    # A final 0.5 s inside the band is needed to call the response settled.
    if samples[-1]['time'] - last_outside < 0.5:
        return None
    return max(0.0, last_outside - run['hold_seconds'])


def study(corpus_path, output):
    corpus = load_corpus(corpus_path)
    plan = corpus['plan']
    output.mkdir(parents=True, exist_ok=False)
    binary = output / 'camera-response'
    subprocess.run(['rustc', '--edition=2024', '-O', str(MODEL_SOURCE), '-o', str(binary)], check=True)
    training = load_partition(corpus_path, corpus, 'train')
    trials, cache = [], {}
    with contextlib.closing(Replay(binary, training, output / 'training.tsv')) as replay:
        def trial(model, a, b):
            key = (model, round(a, 14), round(b, 14))
            if key not in cache:
                require(len(trials) < plan['search']['max_evaluations'], 'Search evaluation budget exhausted')
                metrics = replay.evaluate(model, a, b)
                loss = aggregate(training, metrics)
                cache[key] = loss
                trials.append(dict(index=len(trials), model=model, a=a, b=b, training_loss=loss, runs=metrics))
            return cache[key]
        trial('direct', 0.0, 0.0)
        trial('exponential', 0.055, 0.0)
        exp = hill_climb(lambda p: trial('exponential', p[0] / 1000, 0.0), [55], [20], [0.125],
                         [plan['search']['exponential_ms_bounds']])
        springs = [hill_climb(lambda p: trial('spring', 10 ** p[0], p[1]), seed, [1, 0.2], [0.003, 0.001],
                              [plan['search']['spring_log10_bounds'], plan['search']['damping_bounds']])
                   for seed in plan['search']['spring_seeds']]
        spring = min(springs)
        contenders = [(exp[0], dict(model='exponential', a=exp[1][0] / 1000, b=0.0)),
                      (spring[0], dict(model='spring', a=10 ** spring[1][0], b=spring[1][1]))]
        _, selected = min(contenders, key=lambda item: item[0])
        train_winner = replay.evaluate(**selected, curves=True)
        train_direct = replay.evaluate('direct', curves=True)
        train_55 = replay.evaluate('exponential', 0.055, curves=True)
    lock = dict(candidate=selected, corpus_sha256=sha256(corpus_path), plan_sha256=corpus['plan_sha256'],
                model_source_sha256=sha256(MODEL_SOURCE), evaluator_sha256=sha256(Path(__file__)),
                binary_sha256=sha256(binary), rustc=subprocess.check_output(['rustc', '--version'], text=True).strip(),
                training_loss=aggregate(training, train_winner), trials=len(trials))
    # No held-out observations are decoded or evaluated before this immutable choice is written.
    write_json(output / 'winner.json', lock)
    (output / 'trials.jsonl').write_text(''.join(json.dumps(t, allow_nan=False) + '\n' for t in trials))
    heldout = load_partition(corpus_path, corpus, 'heldout')
    with contextlib.closing(Replay(binary, heldout, output / 'heldout.tsv')) as replay:
        test_winner = replay.evaluate(**selected, curves=True)
        test_direct = replay.evaluate('direct', curves=True)
        test_55 = replay.evaluate('exponential', 0.055, curves=True)
        documented = replay.evaluate('spring', 0.001, 0.6, curves=True)
    noise = []
    for case in {r['fixture']['name'] for r in training}:
        for metrics in (train_direct, train_55):
            values = [m['rmse'] for r, m in zip(training, metrics) if r['fixture']['name'] == case]
            noise.append(max(values) - min(values))
    required_gain = max(plan['minimum_gain'], max(noise))
    summaries = []
    checks = []
    for split, runs, winning, direct, exponential in [('train', training, train_winner, train_direct, train_55),
                                                      ('heldout', heldout, test_winner, test_direct, test_55)]:
        for i, (run, win, raw, exp55) in enumerate(zip(runs, winning, direct, exponential)):
            summary = dict(name=run['name'], fixture=run['fixture']['name'], kind=run['fixture']['kind'], split=split,
                           direct={k: raw[k] for k in ('rmse', 'peak')}, exponential_55ms={k: exp55[k] for k in ('rmse', 'peak')},
                           candidate={k: win[k] for k in ('rmse', 'peak')}, end_bias=end_bias(run, win),
                           native_settling=settling(run, [s['reference'] for s in run['samples']]),
                           candidate_settling=settling(run, win['prediction']))
            # Diagnostic only: supply the independently observed animated source-node height.
            # Selection and acceptance still score the constant-eye candidate above.
            source_errors = [p + s['camera_input'] - run['eye_offset'] - s['reference']
                             for p, s in zip(win['prediction'], run['samples']) if s['time'] >= 0]
            summary['source_node_conditioned_peak'] = max(map(abs, source_errors))
            summary['source_node_excursion'] = max(abs(s['camera_input'] - run['eye_offset'])
                                                   for s in run['samples'] if s['time'] >= 0)
            if split == 'heldout':
                summary['documented_spring'] = {k: documented[i][k] for k in ('rmse', 'peak')}
                checks += [dict(name=run['name'] + ':absolute_fit', passed=win['rmse'] <= plan['max_heldout_rmse'] and win['peak'] <= plan['max_heldout_peak']),
                           dict(name=run['name'] + ':settled', passed=summary['end_bias'] <= plan['max_end_bias'] and summary['candidate_settling'] is not None)]
                if run['fixture']['kind'] in ('flat', 'jump'):
                    checks.append(dict(name=run['name'] + ':control', passed=win['peak'] <= min(raw['peak'], exp55['peak']) + plan['control_peak_allowance']))
            summaries.append(summary)
            with (output / (run['name'] + '.csv')).open('w') as stream:
                writer = csv.writer(stream)
                writer.writerow(['time_s', 'player_height', 'native_relative_height', 'direct', 'exponential_55ms', 'candidate'])
                writer.writerows([s['time'], s['player'], s['reference'], d, e, w] for s, d, e, w in
                                 zip(run['samples'], raw['prediction'], exp55['prediction'], win['prediction']))
    gains = []
    for split in ('train', 'heldout'):
        for kind in ('ascent', 'descent'):
            group = [s for s in summaries if s['split'] == split and s['kind'] == kind]
            improvements = [min(s['direct']['rmse'], s['exponential_55ms']['rmse']) - s['candidate']['rmse'] for s in group]
            gain = statistics.median(improvements)
            gains.append(dict(split=split, kind=kind, median_gain=gain, required_gain=required_gain, passed=gain > required_gain))
    verdict = ('rejected' if not all(c['passed'] for c in checks) else
               'conditional_improvement' if all(g['passed'] for g in gains) else 'inconclusive')
    report = dict(schema=1, verdict=verdict, winner=lock, winner_lock_sha256=sha256(output / 'winner.json'),
                  models={'direct': 'HEAD 1dcca42 walk_camera_follow_system, relative-height equivalence',
                          'exponential_55ms': 'PR511 41df866 response formula only; all vertical deltas; solver eligibility NOT replayed',
                          'candidate': 'free-running f64 response; native scaled dt; all vertical deltas; observed gate=weight=1'},
                  training_repeat_rmse_spread=max(noise), required_gain=required_gain,
                  runs=summaries, gates=checks, stair_gains=gains,
                  limitations=['post-update CPU camera boundary, not GPU consumption', 'three repeats per fixture, one runtime and cadence',
                               'native player trajectory supplied; no Mudcrab movement/collision parity', 'production camera unchanged'])
    write_json(output / 'report.json', report)
    print(json.dumps({'verdict': verdict, 'candidate': selected, 'trials': len(trials), 'report': str(output / 'report.json')}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    record = sub.add_parser('capture')
    record.add_argument('--plan', type=Path, required=True)
    record.add_argument('--session', type=Path, required=True)
    record.add_argument('--output', type=Path, required=True)
    record.add_argument('--ocr-prefix', type=Path, required=True)
    search = sub.add_parser('study')
    search.add_argument('--corpus', type=Path, required=True)
    search.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'capture':
        capture(args.plan.resolve(), args.session.resolve(), args.output.resolve(), args.ocr_prefix.resolve())
    else:
        study(args.corpus.resolve(), args.output.resolve())


if __name__ == '__main__':
    main()
