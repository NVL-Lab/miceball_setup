"""Unified Parameters through real GUI/catalog HTTP and controlled inventory replies."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from gui.tests import test_catalog
from lab_sync_acquisition import AcquisitionNode, DeviceManager, DeviceDeclaration, ScientificProductDeclaration
from lab_sync_acquisition.device_adapter import DeviceAdapter


class ParametersBrowserTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_catalog.CatalogHttpTests.asyncSetUp

    async def test_unified_contexts(self):
        node = shutil.which('node')
        module = os.environ.get('LAB_SYNC_PLAYWRIGHT_MODULE', 'playwright')
        if not node or subprocess.run([node, '-e', 'require(process.argv[1])', module], capture_output=True).returncode:
            self.skipTest('Node and Playwright required')
        class Adapter(DeviceAdapter):
            def get_session_parameter_definitions(self):
                return {'count': {'type': 'integer', 'allowed_values': [0, 2]},
                    'rate': {'type': 'number', 'minimum': 0, 'exclusive_minimum': 0, 'maximum': 3, 'nullable': True},
                    'advanced_text': {'type': 'string'}, 'flag': {'type': 'boolean'}}
        owner = AcquisitionNode(device_manager=DeviceManager([Adapter('camera', 'test', (), True)]), node_id='node', role='acquisition',
            synchronization_source_id='sync', device_declarations=[DeviceDeclaration('camera', 'test', True, False, (),
                (ScientificProductDeclaration('frames', 'camera_frames', {}, 'jsonl'),))])
        environment = {**os.environ, 'MICEBALL_PARAMETERS_ORIGIN': self.origin,
            'MICEBALL_PARAMETERS_INVENTORY': json.dumps(owner.get_inventory())}
        if os.environ.get('LAB_SYNC_GUI_EVIDENCE_DIR'):
            Path(os.environ['LAB_SYNC_GUI_EVIDENCE_DIR']).mkdir(parents=True, exist_ok=True)
        result = await asyncio.to_thread(subprocess.run, [node, str(Path(__file__).with_suffix('.mjs'))],
            env=environment, capture_output=True, text=True, encoding='utf-8', timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
