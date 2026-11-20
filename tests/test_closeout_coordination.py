"""Normal closeout through independent authenticated NATS command/evidence consumers."""
import asyncio
import json
import unittest
from unittest.mock import patch

from lab_sync_acquisition import AcquisitionNode, ExperimentConfiguration, ScientificOutputSelection
from tests.test_distributed_synchronization import configuration
from tests import test_session_artifact_destinations as destinations


class CloseoutCoordinationTests(unittest.IsolatedAsyncioTestCase):
    setUp = destinations.DestinationLaunchTests.setUp
    asyncSetUp = destinations.DestinationLaunchTests.asyncSetUp

    async def test_rejected_before_start_then_delayed_marker_is_preserved_and_released(self):
        f = self.f
        f.config['synchronization_configuration'] = configuration()
        await f.services()
        def remote_node(**settings):
            settings.pop('synchronization_manager')
            settings.pop('ingestor')
            return AcquisitionNode(**settings, synchronization_source_id='sync')
        _, device, _ = await f.node(node_class=remote_node)
        js = self.boundaries['ingestor', 'ingestor']._require_jetstream()
        subscribe = js.subscribe
        delayed = asyncio.Event()

        async def subscribe_with_delay(subject, cb, **options):
            async def receive(message):
                if json.loads(message.data).get('evidence_type') == 'acquisition_evidence_completion':
                    delayed.set()
                    await asyncio.sleep(.1)
                await cb(message)
            return await subscribe(subject, cb=receive, **options)

        with patch.object(js, 'subscribe', side_effect=subscribe_with_delay):
            launched = await f.launch({'node-a': [device]})
        self.assertTrue(launched.succeeded, launched.error)
        sid = launched.details['session_id']
        started = await f.controller.start_launched_session()
        self.assertTrue(started.succeeded, started.error)
        with patch.object(f.sync, 'assess_cross_clock_exchanges', side_effect=RuntimeError('controlled unacceptable quality')):
            rejected = await f.controller.start_launched_experiment('never-started',
                configuration=ExperimentConfiguration(5, {'node-a': 100000}, 100000,
                    participating_devices={'node-a': [device.device_id]}),
                scientific_outputs=(ScientificOutputSelection(device.device_id, 'node-a', device.scientific_products[0].data_product_id),),
                storage_participant=next(p for p in f.participants if p.component_type == 'storage_manager'))
        self.assertFalse(rejected.succeeded)
        self.assertFalse(f.controller.get_status()['experiment_lifecycle_evidence'])
        stopped = await f.controller.normal_stop_session(communication=f.communication,
            storage_participant=next(p for p in f.participants if p.component_type == 'storage_manager'), result_window_s=5)
        self.assertTrue(delayed.is_set())
        self.assertTrue(stopped.succeeded, stopped.error)
        self.assertTrue(stopped.details['acquisition_preservation_eligible'])
        released = await f.controller.release_session(communication=f.communication, result_window_s=5)
        self.assertTrue(released.succeeded, released.error)
        self.assertIsNone(f.ingestor.session_id)
