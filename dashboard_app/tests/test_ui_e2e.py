"""
End-to-end UI tests using Playwright.
Launches the dashboard as a subprocess on an isolated port with an empty
batteries config (no real BLE hardware needed), drives a headless browser,
and verifies that the page loads and key interactions work.

Both a desktop engine and a mobile engine are always in the DOM; only one
is visible at a given viewport width via Tailwind's max-md/md hidden classes.
Selectors are scoped to `.first` or to the visible engine container to avoid
strict-mode violations.
"""
import json
import os
import subprocess
import time
import unittest
import urllib.request
from pathlib import Path

ROOT        = Path(__file__).resolve().parent.parent.parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
APP         = ROOT / "dashboard_app" / "dashboard.py"
PORT        = 8092
URL         = f"http://127.0.0.1:{PORT}"


def _wait_for_server(url: str, timeout: int = 20) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


@unittest.skipUnless(
    VENV_PYTHON.exists(),
    "venv not found — run run.bat first",
)
class TestUIE2E(unittest.TestCase):
    """Playwright end-to-end tests against a live dashboard instance."""

    @classmethod
    def setUpClass(cls):
        cls.test_config = str(Path(__file__).parent / "_e2e_test.json")
        with open(cls.test_config, "w") as f:
            json.dump([], f)

        env = os.environ.copy()
        env["LITHIUM_CONFIG_PATH"] = cls.test_config
        env["LITHIUM_PORT"]        = str(PORT)
        env["PYTHONUNBUFFERED"]    = "1"

        cls.proc = subprocess.Popen(
            [str(VENV_PYTHON), str(APP)],
            cwd=str(ROOT / "dashboard_app"),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if not _wait_for_server(URL, timeout=20):
            cls.proc.terminate()
            raise RuntimeError(f"Dashboard did not start on {URL} within 20 s")

        from playwright.sync_api import sync_playwright
        cls._pw     = sync_playwright().start()
        cls.browser = cls._pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._pw.stop()
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        if os.path.exists(cls.test_config):
            os.remove(cls.test_config)

    def _page(self, width=1440, height=900):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        page.goto(URL, wait_until="networkidle", timeout=15000)
        page.wait_for_timeout(1000)
        return page

    # ------------------------------------------------------------------
    # Basic load
    # ------------------------------------------------------------------

    def test_page_returns_200(self):
        import httpx
        r = httpx.get(URL, timeout=5)
        self.assertEqual(r.status_code, 200)

    def test_page_title_contains_lithium_core(self):
        page = self._page()
        self.assertIn("Lithium Core", page.title())
        page.close()

    def test_lithium_core_header_visible(self):
        page = self._page()
        # Header appears in both engines; .first is fine — at least one must be visible
        self.assertTrue(
            page.locator("text=LITHIUM CORE").first.is_visible(),
            "LITHIUM CORE header not visible",
        )
        page.close()

    def test_system_nodes_heading_visible(self):
        page = self._page()
        self.assertTrue(
            page.locator("text=SYSTEM NODES").first.is_visible(),
            "SYSTEM NODES heading not visible on desktop",
        )
        page.close()

    # ------------------------------------------------------------------
    # Desktop layout (1440 px)
    # ------------------------------------------------------------------

    def test_desktop_sidebar_visible(self):
        page = self._page(width=1440, height=900)
        # The 420 px fixed sidebar is desktop-only
        sidebar = page.locator(".w-\\[420px\\]").first
        self.assertTrue(sidebar.is_visible(), "Desktop sidebar not visible at 1440 px")
        page.close()

    def test_desktop_discovery_section_visible(self):
        page = self._page(width=1440, height=900)
        # Scope to the desktop engine (max-md:hidden container)
        desktop = page.locator(".max-md\\:hidden").first
        self.assertTrue(
            desktop.locator("text=DISCOVERY").is_visible(),
            "DISCOVERY section not visible in desktop engine",
        )
        page.close()

    def test_desktop_scan_button_visible_and_enabled(self):
        page = self._page(width=1440, height=900)
        desktop = page.locator(".max-md\\:hidden").first
        btn = desktop.locator("button", has_text="SCAN")
        self.assertTrue(btn.is_visible(), "SCAN button not visible on desktop")
        self.assertTrue(btn.is_enabled(), "SCAN button not enabled on desktop")
        page.close()

    def test_desktop_add_button_visible_and_enabled(self):
        page = self._page(width=1440, height=900)
        desktop = page.locator(".max-md\\:hidden").first
        btn = desktop.locator("button", has_text="ADD")
        self.assertTrue(btn.is_visible(), "ADD button not visible on desktop")
        self.assertTrue(btn.is_enabled(), "ADD button not enabled on desktop")
        page.close()

    def test_desktop_scan_button_clickable_no_crash(self):
        page = self._page(width=1440, height=900)
        desktop = page.locator(".max-md\\:hidden").first
        btn = desktop.locator("button", has_text="SCAN")
        btn.click()
        page.wait_for_timeout(800)
        # Page must still be alive after click
        self.assertEqual(page.url, URL + "/")
        page.close()

    def test_desktop_bms_type_dropdown_present(self):
        page = self._page(width=1440, height=900)
        desktop = page.locator(".max-md\\:hidden").first
        self.assertTrue(
            desktop.locator("text=Auto-Detect").is_visible(),
            "BMS type dropdown not visible on desktop",
        )
        page.close()

    def test_desktop_power_sources_section_visible(self):
        page = self._page(width=1440, height=900)
        desktop = page.locator(".max-md\\:hidden").first
        self.assertTrue(
            desktop.locator("text=POWER SOURCES").is_visible(),
            "POWER SOURCES section not visible on desktop",
        )
        page.close()

    # ------------------------------------------------------------------
    # Mobile layout (390 px)
    # ------------------------------------------------------------------

    def test_mobile_sidebar_hidden(self):
        page = self._page(width=390, height=844)
        # The 420 px sidebar must not be visible on mobile
        self.assertFalse(
            page.locator(".w-\\[420px\\]").first.is_visible(),
            "Desktop sidebar should be hidden at mobile width",
        )
        page.close()

    def test_mobile_scan_button_visible_and_enabled(self):
        page = self._page(width=390, height=844)
        mobile = page.locator(".md\\:hidden").first
        btn = mobile.locator("button", has_text="SCAN")
        self.assertTrue(btn.is_visible(), "SCAN button not visible on mobile")
        self.assertTrue(btn.is_enabled(), "SCAN button not enabled on mobile")
        page.close()

    def test_mobile_scan_button_clickable_no_crash(self):
        page = self._page(width=390, height=844)
        mobile = page.locator(".md\\:hidden").first
        btn = mobile.locator("button", has_text="SCAN")
        btn.click()
        page.wait_for_timeout(800)
        self.assertEqual(page.url, URL + "/")
        page.close()


RESIZE_PORT = 8094
RESIZE_URL  = f"http://127.0.0.1:{RESIZE_PORT}"

# Breakpoints to stress-test: (width, height, label)
VIEWPORTS = [
    (320,  568,  "iPhone SE"),
    (375,  667,  "iPhone 8"),
    (390,  844,  "iPhone 14"),
    (414,  896,  "iPhone XR"),
    (768,  1024, "iPad"),
    (1024, 768,  "iPad landscape"),
    (1280, 800,  "Small laptop"),
    (1440, 900,  "Desktop"),
    (1920, 1080, "Full HD"),
]


def _check_overflow(page) -> list[dict]:
    """
    Return visible TEXT LEAF elements whose content is wider than their box.
    Skips wrapper/container divs (elements with block children) to avoid
    false positives from parent elements that inherit child overflow.
    """
    return page.evaluate("""() => {
        const bad = [];
        const skipTags = new Set(['HTML','BODY','SCRIPT','STYLE','HEAD','SVG','PATH','DEFS','G']);
        for (const el of document.querySelectorAll('*')) {
            if (skipTags.has(el.tagName)) continue;
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;   // hidden/zero-size

            const style = getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            if (style.overflow === 'hidden' || style.overflow === 'auto'
                || style.overflowX === 'hidden' || style.overflowX === 'auto'
                || style.overflowX === 'scroll') continue;

            // Only check leaf-ish elements: those whose only children are inline/text
            const hasBlockChild = Array.from(el.children).some(c => {
                const cs = getComputedStyle(c);
                return cs.display === 'block' || cs.display === 'flex'
                    || cs.display === 'grid' || cs.display === 'table';
            });
            if (hasBlockChild) continue;

            const text = el.textContent.trim();
            if (!text) continue;

            if (el.scrollWidth > el.clientWidth + 2) {  // 2px tolerance
                bad.push({
                    tag: el.tagName,
                    text: text.slice(0, 60),
                    scrollWidth: el.scrollWidth,
                    clientWidth: el.clientWidth,
                    overflow: el.scrollWidth - el.clientWidth,
                });
            }
        }
        return bad;
    }""")


@unittest.skipUnless(
    VENV_PYTHON.exists(),
    "venv not found — run run.bat first",
)
class TestUIResponsive(unittest.TestCase):
    """
    Resize / overflow tests across common viewport widths.
    Uses demo mode with a connected battery so the full UI is rendered.
    Checks that no text element overflows its container at any breakpoint.
    """

    @classmethod
    def setUpClass(cls):
        cls.test_config = str(Path(__file__).parent / "_e2e_resize_test.json")
        # Pre-populate so the mock battery is provisioned at startup —
        # no need to click ADD in each test (which fails on hidden mobile DOM).
        with open(cls.test_config, "w") as f:
            json.dump([{"mac": "AA:BB:CC:00:00:01", "bms_type": "EG4",
                        "name": "EG4 Test Battery"}], f)

        env = os.environ.copy()
        env["LITHIUM_CONFIG_PATH"] = cls.test_config
        env["LITHIUM_PORT"]        = str(RESIZE_PORT)
        env["LITHIUM_DEMO_MODE"]   = "1"
        env["PYTHONUNBUFFERED"]    = "1"

        cls.proc = subprocess.Popen(
            [str(VENV_PYTHON), str(APP)],
            cwd=str(ROOT / "dashboard_app"),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if not _wait_for_server(RESIZE_URL, timeout=20):
            cls.proc.terminate()
            raise RuntimeError(f"Dashboard did not start on {RESIZE_URL}")

        from playwright.sync_api import sync_playwright
        cls._pw      = sync_playwright().start()
        cls.browser  = cls._pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._pw.stop()
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        if os.path.exists(cls.test_config):
            os.remove(cls.test_config)

    def _page_with_battery(self, width: int, height: int):
        """Open page at given size; battery is pre-provisioned from config at startup."""
        page = self.browser.new_page(viewport={"width": width, "height": height})
        page.goto(RESIZE_URL, wait_until="networkidle", timeout=15000)
        # Wait for a VISIBLE "85%" label — not just any DOM element with that text,
        # since both engines render it but only one is visible at a given width.
        page.wait_for_function(
            "() => Array.from(document.querySelectorAll('*')).some("
            "  el => el.textContent.trim() === '85%'"
            "  && el.children.length === 0"
            "  && el.getBoundingClientRect().width > 0"
            ")",
            timeout=15000,
        )
        return page

    def _run_overflow_check(self, width: int, height: int, label: str):
        page = self._page_with_battery(width, height)
        try:
            overflows = _check_overflow(page)
            if overflows:
                details = "; ".join(
                    f"<{o['tag']}> '{o['text'][:30]}' overflows by {o['overflow']}px"
                    for o in overflows[:5]
                )
                self.fail(f"{label} ({width}×{height}): text overflow detected — {details}")
        finally:
            page.close()

    def test_no_overflow_iphone_se(self):
        self._run_overflow_check(320, 568, "iPhone SE")

    def test_no_overflow_iphone_8(self):
        self._run_overflow_check(375, 667, "iPhone 8")

    def test_no_overflow_iphone_14(self):
        self._run_overflow_check(390, 844, "iPhone 14")

    def test_no_overflow_iphone_xr(self):
        self._run_overflow_check(414, 896, "iPhone XR")

    def test_no_overflow_ipad_portrait(self):
        self._run_overflow_check(768, 1024, "iPad portrait")

    def test_no_overflow_ipad_landscape(self):
        self._run_overflow_check(1024, 768, "iPad landscape")

    def test_no_overflow_small_laptop(self):
        self._run_overflow_check(1280, 800, "Small laptop")

    def test_no_overflow_desktop(self):
        self._run_overflow_check(1440, 900, "Desktop")

    def test_no_overflow_full_hd(self):
        self._run_overflow_check(1920, 1080, "Full HD")

    def test_header_single_line_at_all_widths(self):
        """LITHIUM CORE header must not wrap — check it stays under 60px tall."""
        for width, height, label in VIEWPORTS:
            with self.subTest(label=label):
                page = self.browser.new_page(viewport={"width": width, "height": height})
                page.goto(RESIZE_URL, wait_until="networkidle", timeout=15000)
                page.wait_for_timeout(800)
                header_height = page.evaluate("""() => {
                    const el = Array.from(document.querySelectorAll('*'))
                        .find(e => e.textContent.trim() === 'LITHIUM CORE');
                    return el ? el.getBoundingClientRect().height : 0;
                }""")
                self.assertLess(
                    header_height, 60,
                    f"Header appears to be wrapping at {label} ({width}px) — height {header_height}px",
                )
                page.close()

    def test_buttons_not_clipped_at_mobile_widths(self):
        """SCAN and ADD buttons must be fully visible (no clipping) on mobile."""
        for width, height, label in VIEWPORTS[:4]:  # mobile sizes only
            with self.subTest(label=label):
                page = self.browser.new_page(viewport={"width": width, "height": height})
                page.goto(RESIZE_URL, wait_until="networkidle", timeout=15000)
                page.wait_for_timeout(800)
                clipped = page.evaluate("""() => {
                    const results = [];
                    for (const btn of document.querySelectorAll('button')) {
                        const text = btn.textContent.trim();
                        if (!['SCAN', 'ADD'].includes(text)) continue;
                        const rect = btn.getBoundingClientRect();
                        // Skip buttons from the hidden engine (rect.width === 0)
                        if (rect.width === 0 || rect.height === 0) continue;
                        if (rect.right > window.innerWidth + 2
                            || rect.bottom > window.innerHeight + 2) {
                            results.push({ text, rect: {
                                right: Math.round(rect.right),
                                bottom: Math.round(rect.bottom),
                                width: Math.round(rect.width),
                                height: Math.round(rect.height),
                            }});
                        }
                    }
                    return results;
                }""")
                self.assertEqual(
                    clipped, [],
                    f"Button clipped at {label} ({width}px): {clipped}",
                )
                page.close()


DEMO_PORT = 8093
DEMO_URL  = f"http://127.0.0.1:{DEMO_PORT}"


@unittest.skipUnless(
    VENV_PYTHON.exists(),
    "venv not found — run run.bat first",
)
class TestUIInteractionFlow(unittest.TestCase):
    """
    Full interaction flow using mock BLE hardware (LITHIUM_DEMO_MODE=1).
    Tests: scan → add battery → battery card visible → click card → detail view.
    No real BLE adapter or batteries required.
    """

    @classmethod
    def setUpClass(cls):
        cls.test_config = str(Path(__file__).parent / "_e2e_flow_test.json")
        with open(cls.test_config, "w") as f:
            json.dump([], f)

        env = os.environ.copy()
        env["LITHIUM_CONFIG_PATH"] = cls.test_config
        env["LITHIUM_PORT"]        = str(DEMO_PORT)
        env["LITHIUM_DEMO_MODE"]   = "1"
        env["PYTHONUNBUFFERED"]    = "1"

        cls.proc = subprocess.Popen(
            [str(VENV_PYTHON), str(APP)],
            cwd=str(ROOT / "dashboard_app"),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if not _wait_for_server(DEMO_URL, timeout=20):
            cls.proc.terminate()
            raise RuntimeError(f"Dashboard did not start on {DEMO_URL}")

        from playwright.sync_api import sync_playwright
        cls._pw     = sync_playwright().start()
        cls.browser = cls._pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._pw.stop()
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        if os.path.exists(cls.test_config):
            os.remove(cls.test_config)

    def _page(self, width=1440, height=900):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        page.goto(DEMO_URL, wait_until="networkidle", timeout=15000)
        page.wait_for_timeout(1500)
        return page

    def _desktop(self, page):
        return page.locator(".max-md\\:hidden").first

    def _select_device(self, page, device_text: str):
        """Open the SELECT SOURCE dropdown and pick a device by partial text."""
        desktop = self._desktop(page)
        # Open the first q-select (SELECT SOURCE)
        desktop.locator(".q-select").nth(0).click()
        page.locator(".q-menu").wait_for(state="visible", timeout=5000)
        page.locator(".q-menu .q-item").filter(has_text=device_text).first.click()
        page.wait_for_timeout(300)

    def _add_battery(self, page, device_text: str, bms_type: str = "EG4"):
        """Select a device, set BMS type, click ADD, wait for card to appear."""
        desktop = self._desktop(page)

        self._select_device(page, device_text)

        # Set BMS type (second q-select)
        desktop.locator(".q-select").nth(1).click()
        page.locator(".q-menu").wait_for(state="visible", timeout=5000)
        page.locator(".q-menu .q-item").filter(has_text=bms_type).first.click()
        page.wait_for_timeout(300)

        desktop.locator("button", has_text="ADD").click()

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    def test_startup_scan_finds_mock_devices(self):
        """Status bar should report found devices after auto-scan at startup."""
        page = self._page()
        page.wait_for_selector("text=FOUND 2 SOURCES", timeout=8000)
        page.close()

    def test_scan_button_populates_dropdown(self):
        """Clicking SCAN populates SELECT SOURCE with the two mock devices."""
        page = self._page()
        desktop = self._desktop(page)
        desktop.locator("button", has_text="SCAN").click()
        page.wait_for_selector("text=FOUND 2 SOURCES", timeout=8000)
        # Open dropdown and verify options are present
        desktop.locator(".q-select").nth(0).click()
        page.locator(".q-menu").wait_for(state="visible", timeout=5000)
        menu = page.locator(".q-menu")
        self.assertTrue(
            menu.locator(".q-item").filter(has_text="EG4 Test Battery").is_visible(),
            "EG4 Test Battery not in dropdown after SCAN",
        )
        self.assertTrue(
            menu.locator(".q-item").filter(has_text="LiTime Test Battery").is_visible(),
            "LiTime Test Battery not in dropdown after SCAN",
        )
        page.keyboard.press("Escape")
        page.close()

    # ------------------------------------------------------------------
    # Add battery
    # ------------------------------------------------------------------

    def test_add_battery_card_appears(self):
        """After ADD, a battery card appears in the sidebar and node grid."""
        page = self._page()
        self._add_battery(page, "EG4 Test Battery", "EG4")
        # Battery card should appear in sidebar
        page.wait_for_selector("text=EG4 Test Battery", timeout=8000)
        self.assertTrue(
            self._desktop(page).locator("text=EG4 Test Battery").first.is_visible(),
        )
        page.close()

    def test_add_battery_shows_live_data(self):
        """After connecting, node card shows SOC percentage (mock delivers 85%)."""
        page = self._page()
        self._add_battery(page, "EG4 Test Battery", "EG4")
        # Wait for mock BMS data to propagate (initial_sync → shows %)
        page.wait_for_selector("text=85%", timeout=10000)
        page.close()

    # ------------------------------------------------------------------
    # Click card → detail view
    # ------------------------------------------------------------------

    def test_click_battery_card_opens_detail_view(self):
        """Clicking a battery node card switches the main area to detail view."""
        page = self._page()
        self._add_battery(page, "EG4 Test Battery", "EG4")
        page.wait_for_selector("text=85%", timeout=10000)

        # Click the node card in the main grid
        main = page.locator(".max-md\\:hidden .q-scrollarea").first
        main.locator(".cursor-pointer").first.click()
        page.wait_for_timeout(1000)

        # Detail view shows CELL VOLTAGES section
        page.wait_for_selector("text=CELL VOLTAGES", timeout=5000)
        self.assertTrue(
            page.locator("text=CELL VOLTAGES").first.is_visible(),
            "CELL VOLTAGES section not visible in detail view",
        )
        page.close()

    def test_detail_view_shows_voltage_metric(self):
        """Detail view metric grid includes a VOLTAGE card."""
        page = self._page()
        self._add_battery(page, "EG4 Test Battery", "EG4")
        page.wait_for_selector("text=85%", timeout=10000)

        main = page.locator(".max-md\\:hidden .q-scrollarea").first
        main.locator(".cursor-pointer").first.click()
        page.wait_for_timeout(1000)

        self.assertTrue(
            page.locator("text=VOLTAGE").first.is_visible(),
            "VOLTAGE metric card not visible in detail view",
        )
        page.close()

    def test_detail_view_back_button_returns_to_grid(self):
        """Clicking the back (chevron_left) button returns to the system grid."""
        page = self._page()
        self._add_battery(page, "EG4 Test Battery", "EG4")
        page.wait_for_selector("text=85%", timeout=10000)

        main = page.locator(".max-md\\:hidden .q-scrollarea").first
        main.locator(".cursor-pointer").first.click()
        page.wait_for_timeout(1000)
        page.wait_for_selector("text=CELL VOLTAGES", timeout=5000)

        # Click back button — Quasar renders the icon as text inside .q-icon
        back_btn = page.locator("button").filter(
            has=page.locator(".q-icon", has_text="chevron_left")
        ).first
        back_btn.click()
        page.wait_for_timeout(800)

        # Should be back on the grid showing SYSTEM NODES
        self.assertTrue(
            page.locator("text=SYSTEM NODES").first.is_visible(),
            "SYSTEM NODES not visible after pressing back",
        )
        page.close()


if __name__ == "__main__":
    unittest.main()
