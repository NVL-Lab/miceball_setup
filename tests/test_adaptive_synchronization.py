"""Deterministic bounded-clock workflows through the synchronization owner."""

from copy import deepcopy
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lab_sync_acquisition.synchronization import SynchronizationManager
from lab_sync_acquisition.ingestor import InMemoryIngestor
from tests.test_distributed_synchronization import configuration


class AdaptiveSynchronizationTests(unittest.TestCase):
    def setUp(self):
        self.time = 0.0
        self.clock = patch('lab_sync_acquisition.synchronization.monotonic', side_effect=lambda: self.time)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.owner = SynchronizationManager()
        self.owner.prepare_session('session')
        self.owner.configure_distributed_session('session', configuration(
            clock_rate_error_bound=.02, max_uncertainty_s=.1, max_mapping_age_s=1000000))
        self.owner.start_distributed_session('session')

    @staticmethod
    def samples(local, session, rate=1.0, delay=.002):
        spacing = max(.1, (2 * delay + .01) / rate)
        return [dict(sent_session_time_s=session + rate * i * spacing - delay,
                     received_local_time_s=local + i * spacing,
                     sent_local_time_s=local + i * spacing,
                     received_session_time_s=session + rate * i * spacing + delay,
                     local_clock_resolution_s=0.0) for i in range(3)]

    def assess(self, local, session, rate=1., *, replace=True, node='node', delay=.002):
        self.time = max(self.time, session + 1)
        return self.owner.assess_cross_clock_exchanges('session', node,
            self.samples(local, session, rate, delay), replace_mapping=replace, source_id='sync')

    def test_accumulated_rate_estimate_and_confidence_preserve_measurements(self):
        first = self.assess(100, 0, 1.005)
        for n in range(1, 30):
            last = self.assess(100 + n * 10, n * 10 * 1.005, 1.005)
        self.assertLess(abs(last['mapping']['scale'] - 1.005), .0001)
        self.assertLess(last['estimator']['rate_bounds'][1] - last['estimator']['rate_bounds'][0],
                        first['estimator']['rate_bounds'][1] - first['estimator']['rate_bounds'][0])
        self.assertEqual(last['exchanges'], self.samples(390, 290 * 1.005, 1.005))

    def test_limited_history_can_establish_changed_rate_without_long_warmup(self):
        self.assess(100, 0)
        for n in range(1, 5):
            quality = self.assess(100 + n * 10, n * 10 * 1.01, 1.01)
        self.assertTrue(quality['acceptable'])
        self.assertLess(abs(quality['mapping']['scale'] - 1.01), .001)

    def test_explicit_nonunit_fixed_rate_is_preserved_without_false_precision(self):
        owner = SynchronizationManager()
        owner.prepare_session('fixed')
        owner.configure_distributed_session('fixed', configuration(initial_scale=1.5,
            clock_rate_error_bound=0., max_mapping_age_s=1000))
        owner.start_distributed_session('fixed')
        for n in range(3):
            self.time += 10
            quality = owner.assess_cross_clock_exchanges('fixed', 'node',
                self.samples(100 + n * 10, n * 15, 1.5), replace_mapping=True, source_id='sync')
            self.assertEqual(quality['mapping']['scale'], 1.5)
            self.assertEqual(quality['estimator']['rate_bounds'], [1.5, 1.5])
            self.assertGreaterEqual(quality['uncertainty_s'], .002)

    def test_initial_contradictory_batch_is_retained_without_fabricated_mapping(self):
        samples = self.samples(100, 0)
        samples[1]['received_local_time_s'] += 100
        samples[1]['sent_local_time_s'] += 100
        with self.assertRaises(ValueError):
            self.owner.assess_cross_clock_exchanges('session', 'node', samples,
                replace_mapping=True, source_id='sync')
        failed, = self.owner.session_timing_evidence('session', 'sync')
        self.assertEqual(failed.payload['exchanges'], samples)
        self.assertFalse(failed.payload['acceptable'])
        self.assertIsNone(failed.payload['mapping'])
        self.assertIsNone(self.owner.get_active_mapping('session', 'node'))
        quality = self.assess(200, 10)
        self.assertTrue(quality['acceptable'])
        self.assertEqual(quality['estimator']['disposition'], 'initial_assumption')

    def test_isolated_anomaly_is_quality_failure_not_mapping_correction(self):
        for n in range(1001):
            quality = self.assess(100 + n * 10, n * 10)
        mapping = self.owner.get_active_mapping('session', 'node')
        bad = self.assess(10110, 10010 + 1)
        self.assertFalse(bad['acceptable'])
        self.assertFalse(bad['estimator']['refinement_accepted'])
        self.assertEqual(self.owner.get_active_mapping('session', 'node'), mapping)
        recovered = self.assess(10120, 10020)
        self.assertTrue(recovered['acceptable'])
        self.assertLess(abs(recovered['mapping']['scale'] - 1), .0001)

    def test_sustained_change_after_long_history_and_gradual_changes_adapt(self):
        for n in range(101):
            self.assess(100 + n * 10, n * 10)
        for n in range(1, 21):
            changed = self.assess(1100 + n * 10, 1000 + n * 10 * 1.01, 1.01)
        self.assertLess(abs(changed['mapping']['scale'] - 1.01), .0005)
        session = 1202.
        for n in range(1, 41):
            rate = 1.01 - n * .0001
            session += 10 * rate
            changed = self.assess(1300 + n * 10, session, rate)
        self.assertLess(abs(changed['estimator']['scale'] - rate), .002)

    def test_assessment_only_keeps_mapping_and_reports_its_actual_error(self):
        first = self.assess(100, 0)
        for n in range(1, 30):
            quality = self.assess(100 + n * 10, n * 10 * 1.01, 1.01, replace=False)
        self.assertEqual(quality['mapping'], first['mapping'])
        self.assertFalse(quality['acceptable'])
        self.assertLess(abs(quality['estimator']['scale'] - 1.01), .0001)
        refreshed = self.assess(400, 303, 1.01)
        self.assertTrue(refreshed['acceptable'])

    def test_duplicate_and_stale_measurements_cannot_add_confidence(self):
        self.assess(100, 0)
        samples = self.samples(110, 10)
        quality = self.assess(110, 10)
        evidence = self.owner.session_timing_evidence('session', 'sync')
        duplicate = self.owner.assess_cross_clock_exchanges('session', 'node', samples,
            replace_mapping=True, source_id='sync')
        self.assertEqual(quality, duplicate)
        self.assertEqual(evidence, self.owner.session_timing_evidence('session', 'sync'))
        self.assess(120, 20)
        with self.assertRaises(ValueError):
            self.owner.assess_cross_clock_exchanges('session', 'node', samples,
                replace_mapping=True, source_id='sync')

    def test_rejected_and_partial_measurements_remain_durable_evidence(self):
        self.assess(100, 0)
        mapping = self.owner.get_active_mapping('session', 'node')
        damaged = self.samples(110, 10)
        damaged[1]['sent_local_time_s'] = 1
        with self.assertRaises(ValueError):
            self.owner.assess_cross_clock_exchanges('session', 'node', damaged,
                replace_mapping=True, source_id='sync')
        partial = self.samples(120, 20)[:1]
        quality = self.owner.mark_synchronization_unavailable('session', 'node', 'sync',
            'transport interrupted', exchanges=partial)
        self.assertFalse(quality['acceptable'])
        self.assertEqual(quality['exchanges'], partial)
        evidence = self.owner.session_timing_evidence('session', 'sync')
        self.assertTrue(any(m.payload.get('exchanges') == damaged for m in evidence))
        self.assertEqual(self.owner.get_active_mapping('session', 'node'), mapping)
        snapshot = deepcopy([m.to_dict() for m in evidence])
        quality['exchanges'].clear()
        self.assertEqual([m.to_dict() for m in self.owner.session_timing_evidence('session', 'sync')], snapshot)

    def test_node_isolation_and_long_duration_validity_use_configured_rate_bounds(self):
        for n in range(10):
            quality = self.assess(1000000000 + n * 1000, n * 1000 * 1.005, 1.005)
        other = self.assess(100, 0, node='other')
        self.assertEqual(other['estimator']['scale'], 1.0)
        self.assertLess(abs(quality['mapping']['scale'] - 1.005), .0001)
        self.assertLessEqual(quality['valid_until_local_time_s'] - quality['measured_local_time_s'],
                            .1 / .02)
        with self.assertRaises(RuntimeError):
            self.owner.assess_cross_clock_exchanges('replacement', 'node', [],
                replace_mapping=True, source_id='sync')

    def test_asymmetric_jitter_bounds_contain_known_clock_without_false_precision(self):
        for n in range(40):
            local = 100 + n * 10
            session = n * 10 * 1.005
            samples = self.samples(local, session, 1.005)
            for i, sample in enumerate(samples):
                sample['sent_session_time_s'] -= .001 * ((n + i) % 4)
                sample['received_session_time_s'] += .002 * ((n + i) % 3)
            self.time = session + 1
            quality = self.owner.assess_cross_clock_exchanges('session', 'node', samples,
                replace_mapping=True, source_id='sync')
            mapping = quality['mapping']
            truth = session + .2 * 1.005
            self.assertLessEqual(abs(mapping['session_time_anchor_s'] - truth), quality['uncertainty_s'])
            self.assertLessEqual(quality['estimator']['rate_bounds'][0], 1.005)
            self.assertGreaterEqual(quality['estimator']['rate_bounds'][1], 1.005)

    def test_current_evidence_can_be_uninformative_without_destroying_confidence(self):
        first = self.assess(100, 0, delay=.05)
        self.assertEqual(first['estimator']['rate_bounds'], [.98, 1.02])
        for n in range(1, 10):
            quality = self.assess(100 + n * 10, n * 10)
        width = quality['estimator']['rate_bounds'][1] - quality['estimator']['rate_bounds'][0]
        uncertain = self.assess(200, 100, delay=.5)
        self.assertFalse(uncertain['acceptable'])
        self.assertLessEqual(uncertain['estimator']['rate_bounds'][1] - uncertain['estimator']['rate_bounds'][0], width)
        self.assertGreater(uncertain['uncertainty_s'], self.owner.distributed_configuration.max_uncertainty_s)

    def test_failed_release_retains_history_and_successful_release_resets_learning(self):
        with tempfile.TemporaryDirectory() as directory:
            ingestor = InMemoryIngestor(recovery_journal_path=Path(directory) / 'evidence.jsonl', session_id='session')
            for n in range(10):
                self.assess(100 + n * 10, n * 10 * 1.005, 1.005)
            self.owner.stop()
            self.owner.retire_active_mapping('session', 'node', 'finished')
            messages = self.owner.session_timing_evidence('session', 'sync')
            with self.assertRaises(RuntimeError):
                self.owner.release_session('session', ingestor=ingestor)
            self.assertEqual(self.owner.session_timing_evidence('session', 'sync'), messages)
            for message in messages:
                ingestor.receive_runtime_evidence(message)
            self.assertTrue(self.owner.release_session('session', ingestor=ingestor))
            self.owner.prepare_session('next')
            self.owner.configure_distributed_session('next', configuration(clock_rate_error_bound=.02))
            self.owner.start_distributed_session('next')
            quality = self.owner.assess_cross_clock_exchanges('next', 'node', self.samples(1000, 0),
                replace_mapping=True, source_id='sync')
            self.assertEqual(quality['estimator']['rate_bounds'], [.98, 1.02])
            self.assertTrue(ingestor.has_durable_runtime_evidence(messages[-1]))


class AdaptivePublicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_closeout_retains_identical_evidence_for_explicit_retry(self):
        owner = SynchronizationManager()
        owner.prepare_session('session')
        owner.configure_distributed_session('session', configuration())
        owner.start_distributed_session('session')
        samples = AdaptiveSynchronizationTests.samples(100, 0)
        owner.assess_cross_clock_exchanges('session', 'node', samples, replace_mapping=True, source_id='sync')
        async def cancel(message):
            raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await owner.complete_session_evidence_publication('session', source_id='sync', publisher=cancel)
        retained = owner.session_timing_evidence('session', 'sync')
        with self.assertRaises(RuntimeError):
            owner.release_session('session')
        received = []
        async def publish(message):
            received.append(message)
        await owner.complete_session_evidence_publication('session', source_id='sync', publisher=publish)
        self.assertEqual(tuple(received), retained)
        self.assertEqual(sum(m.payload.get('update_type') == 'retired' for m in retained), 1)

