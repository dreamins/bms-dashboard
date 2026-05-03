import unittest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ui_components import get_soc_color, generate_cell_svg, Theme

class TestUIAssets(unittest.TestCase):

    # --- get_soc_color ---

    def test_soc_color_low(self):
        self.assertEqual(get_soc_color(10), Theme.ERROR_RED)

    def test_soc_color_mid(self):
        self.assertEqual(get_soc_color(35), Theme.WARNING_AMBER)

    def test_soc_color_high(self):
        self.assertEqual(get_soc_color(80), Theme.SUCCESS_GREEN)

    def test_soc_color_boundary_20(self):
        self.assertEqual(get_soc_color(20), Theme.WARNING_AMBER)

    def test_soc_color_boundary_50(self):
        self.assertEqual(get_soc_color(50), Theme.SUCCESS_GREEN)

    # --- generate_cell_svg: balanced ---

    def test_cell_svg_balanced_green_tint(self):
        svg = generate_cell_svg(3.3, False, False)
        self.assertIn('16,185,129', svg)

    def test_cell_svg_balanced_has_voltage(self):
        self.assertIn('3.300V', generate_cell_svg(3.3, False, False))

    def test_cell_svg_balanced_white_text(self):
        self.assertIn(Theme.TEXT_PRIMARY, generate_cell_svg(3.3, False, False))

    # --- generate_cell_svg: imbalanced ---

    def test_cell_svg_imbalanced_red_tint(self):
        svg = generate_cell_svg(3.0, False, True)
        self.assertIn('239,68,68', svg)

    def test_cell_svg_imbalanced_red_text(self):
        self.assertIn(Theme.CELL_LOW, generate_cell_svg(3.0, False, True))

    # --- generate_cell_svg: ghost ---

    def test_cell_svg_ghost_faded(self):
        self.assertIn('opacity:0.15', generate_cell_svg(0.0, True, False))

    def test_cell_svg_ghost_no_voltage_text(self):
        self.assertNotIn('V</text>', generate_cell_svg(0.0, True, False))

    # --- generate_cell_svg: label & structure ---

    def test_cell_svg_has_label(self):
        self.assertIn('L01', generate_cell_svg(3.3, False, False, label='L01'))

    def test_cell_svg_no_label_by_default(self):
        self.assertNotIn('font-size="6"', generate_cell_svg(3.3, False, False))

    def test_cell_svg_valid_xmlns(self):
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', generate_cell_svg(3.3, False, False))

if __name__ == '__main__':
    unittest.main()
