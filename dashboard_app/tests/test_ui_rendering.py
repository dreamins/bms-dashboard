import unittest
import threading
import time
import httpx
import os
import sys
from nicegui import ui

# Ensure we can import the dashboard
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

class TestUIRendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Redirect to temporary config for testing
        cls.test_config = os.path.join(os.path.dirname(__file__), 'test_render_batteries.json')
        os.environ['LITHIUM_CONFIG_PATH'] = cls.test_config
        
        # Start the server in a background thread
        def run_server():
            import dashboard
            # Use a unique port for testing
            ui.run(port=8089, show=False, reload=False)
        
        cls.server_thread = threading.Thread(target=run_server, daemon=True)
        cls.server_thread.start()
        # Give it a moment to start
        time.sleep(3)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_config):
            os.remove(cls.test_config)
        os.environ.pop('LITHIUM_CONFIG_PATH', None)

    def test_desktop_rendering_elements(self):
        """Verify that desktop-specific layout elements are present in the HTML."""
        response = httpx.get("http://127.0.0.1:8089/", timeout=5.0)
        self.assertEqual(response.status_code, 200)
        html = response.text
        
        # Check for the desktop engine indicator (we used max-md:hidden)
        self.assertIn('max-md:hidden', html, "Desktop engine 'max-md:hidden' container missing")
        
        # Check for the fixed sidebar width
        self.assertIn('w-[420px]', html, "Desktop sidebar width 'w-[420px]' missing")
        
        # Check for the main content area title
        self.assertIn('SYSTEM NODES', html, "Main content header 'SYSTEM NODES' missing")
        
        # Check for the mobile engine indicator
        self.assertIn('md:hidden', html, "Mobile engine 'md:hidden' container missing")

    def test_header_overlap_fix(self):
        """Verify the body padding fix for the fixed header."""
        response = httpx.get("http://127.0.0.1:8089/", timeout=5.0)
        html = response.text
        self.assertIn('"padding-top":"84px"', html, "Body padding-top fix missing")

if __name__ == '__main__':
    unittest.main()
