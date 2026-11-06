import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest

from hillclimb_skyrim_camera import export_run, hill_climb, load_corpus, digest_json
from record_skyrim_motion import RECORD, sha256


def native_fixture(root, *, rise=120.0, motion=True, spring_pairs=True):
    case = dict(schema=1, name='synthetic-stairs', kind='ascent', split='train',
                position=[1000, 2000, -3000], yaw_degrees=0, hold_ms=4000,
                progress_range=[240, 320], rise_range=[100, 155], height_range=[100, 160],
                start_z_range=[-3005, -2995], corridor_half_width=10)
    plan = dict(runtime_sha256='1' * 64, source_save_sha256='2' * 64,
                pre_roll_seconds=0.75, post_roll_seconds=1.5, max_gap_seconds=0.1)
    rows, input_sequence, sample = [], 0, 0
    previous, velocity, correction = -3000.0, 0.0, 0.0
    def f32(x):
        return struct.unpack('<f', struct.pack('<f', x))[0]
    def emit(kind, qpc, values=None, code=0, text='', frequency=None):
        rows.append([len(rows) + 1, qpc, sample if frequency is None else frequency,
                     input_sequence, kind, 320, code, 0, *(values or [0.0] * 40), text.encode().ljust(48, b'\0')])
    emit(1, 0, text='mudcrab-motion-256-v2', frequency=1_000_000)
    for i in range(351):
        t, qpc = i * 0.02, i * 20000 + 100
        if i in (50, 250):
            input_sequence += 1
            values = [0.0] * 40
            values[:4] = [1, 0, 0, 1] if i == 50 else [0, 4, 0, 0]
            emit(2, qpc, values, 17, 'Forward')
        sample += 1
        progress = min(max((t - 1) / 4, 0), 1)
        height = f32(-3000 + rise * progress)
        position_y = f32(2000 + (300 * progress if motion else 0))
        dt, base, damping = f32(0.02), f32(0.001), f32(0.6)
        old, old_velocity, old_correction = previous, velocity, correction
        delta = previous - height
        correction = f32(base ** dt * delta + damping * dt * velocity)
        previous = f32(height + correction)
        velocity = f32((correction - delta) / dt)
        spring = [0.0] * 40
        spring[:3] = [1000, position_y, height]
        spring[5], spring[8], spring[11], spring[14] = old, old_velocity, old_correction, height + 120.5
        spring[15:18] = [1, 1, dt]
        spring[20], spring[23], spring[26], spring[29] = previous, velocity, correction, height + 120.5
        spring[30:33], spring[36:38] = [1, 1, dt], [base, damping]
        if spring_pairs:
            emit(6, qpc + 1, spring, 3)
        values = [0.0] * 40
        values[:3] = [1000, position_y, height]
        values[9:12] = [1000, position_y, height + 120.5 + correction]
        values[12:15] = values[9:12]
        emit(3, qpc + 2, values, 3)
    emit(5, 7_100_000, text='complete after native W release')
    (root / 'trace.bin').write_bytes(b''.join(RECORD.pack(*row) for row in rows))
    (root / 'before.png').write_bytes(b'fixture before')
    (root / 'after.png').write_bytes(b'fixture after')
    proof = dict(trace_sha256=sha256(root / 'trace.bin'), fixture=case,
                 runner_sha256='5' * 64,
                 session=dict(exe_sha256=plan['runtime_sha256'], source_save_sha256=plan['source_save_sha256'],
                              build={}, input_sha256='3' * 64, proton_sha256='4' * 64))
    (root / 'proof.json').write_text(json.dumps(proof))
    return case, plan


def rewrite_trace(root, mutate):
    data = (root / 'trace.bin').read_bytes()
    rows = [list(RECORD.unpack_from(data, offset)) for offset in range(0, len(data), RECORD.size)]
    mutate(rows)
    (root / 'trace.bin').write_bytes(b''.join(RECORD.pack(*row) for row in rows))
    proof = json.loads((root / 'proof.json').read_text())
    proof['trace_sha256'] = sha256(root / 'trace.bin')
    (root / 'proof.json').write_text(json.dumps(proof))


class HillClimbTests(unittest.TestCase):
    def test_valid_native_stair_observations_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case, plan = native_fixture(root)
            run = export_run(root, case, plan)
            self.assertAlmostEqual(run['validation']['rise'], 120, places=2)
            self.assertGreater(len(run['samples']), 300)
            self.assertLess(run['validation']['spring_recurrence_peak'], 0.002)

    def test_flat_cannot_be_relabelled_as_stairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case, plan = native_fixture(root, rise=0)
            with self.assertRaisesRegex(ValueError, 'Wrong signed vertical traversal'):
                export_run(root, case, plan)

    def test_blocked_player_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case, plan = native_fixture(root, motion=False)
            with self.assertRaisesRegex(ValueError, 'No horizontal player movement'):
                export_run(root, case, plan)

    def test_unpaired_spring_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case, plan = native_fixture(root, spring_pairs=False)
            with self.assertRaisesRegex(ValueError, 'Missing/unpaired spring'):
                export_run(root, case, plan)

    def test_jump_requires_native_jump_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case, plan = native_fixture(root)
            case['kind'] = 'jump'
            proof = json.loads((root / 'proof.json').read_text())
            proof['fixture'] = case
            (root / 'proof.json').write_text(json.dumps(proof))
            with self.assertRaisesRegex(ValueError, 'native Jump'):
                export_run(root, case, plan)

    def test_trace_bytes_are_bound_to_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case, plan = native_fixture(root)
            data = bytearray((root / 'trace.bin').read_bytes())
            data[300] ^= 1
            (root / 'trace.bin').write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'trace hash changed'):
                export_run(root, case, plan)

    def test_changed_capture_pose_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case, plan = native_fixture(root)
            changed = copy.deepcopy(case)
            changed['position'][0] += 500
            with self.assertRaisesRegex(ValueError, 'differs from frozen plan'):
                export_run(root, changed, plan)

    def test_unsupported_spring_gate_is_not_silently_fitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case, plan = native_fixture(root)
            def mutate(rows):
                for row in rows:
                    if row[4] == 6:
                        row[8 + 31] = 0.0
            rewrite_trace(root, mutate)
            with self.assertRaisesRegex(ValueError, 'outside the fitted weight-one regime'):
                export_run(root, case, plan)

    def test_nonfinite_camera_matrix_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case, plan = native_fixture(root)
            def mutate(rows):
                for row in rows:
                    if row[4] == 3:
                        row[8 + 20] = float('nan')
            rewrite_trace(root, mutate)
            with self.assertRaisesRegex(ValueError, 'Nonfinite native observation'):
                export_run(root, case, plan)

    def test_dropped_time_is_not_interpolated_away(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case, plan = native_fixture(root)
            def mutate(rows):
                for row in rows:
                    if row[1] >= 800000:
                        row[1] += 150000
            rewrite_trace(root, mutate)
            with self.assertRaisesRegex(ValueError, 'Camera time gap'):
                export_run(root, case, plan)

    def test_hill_climb_finds_non_default_parameters_within_bounds(self):
        seen = []
        def objective(point):
            seen.append(point)
            return (point[0] + 2.3) ** 2 + (point[1] - 0.33) ** 2
        loss, point = hill_climb(objective, [-4, 0.8], [1, 0.2], [0.003, 0.001], [(-5, -1), (0, 0.95)])
        self.assertLess(loss, 0.0001)
        self.assertTrue(all(-5 <= p[0] <= -1 and 0 <= p[1] <= 0.95 for p in seen))
        self.assertAlmostEqual(point[0], -2.3, delta=0.01)

    def test_corpus_membership_and_hashes_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = dict(repeats=3, cases=[dict(name='stairs', kind='ascent', split='train')])
            entries = []
            for i in range(3):
                p = root / f'{i}.json'
                p.write_text('{}')
                entries.append(dict(name=str(i), fixture='stairs', kind='ascent', split='train',
                                    repeat=i + 1, path=p.name, sha256=sha256(p)))
            corpus = dict(schema=1, plan=plan, plan_sha256=digest_json(plan), runs=entries)
            p = root / 'corpus.json'
            p.write_text(json.dumps(corpus))
            load_corpus(p)
            (root / '0.json').write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError, 'observation hash changed'):
                load_corpus(p)
            corpus['runs'] = entries[:2]
            p.write_text(json.dumps(corpus))
            with self.assertRaisesRegex(ValueError, 'Incomplete repeat group'):
                load_corpus(p)


if __name__ == '__main__':
    unittest.main()
