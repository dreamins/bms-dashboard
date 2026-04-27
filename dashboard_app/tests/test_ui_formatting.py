import unittest
from dashboard import get_cell_logic

class TestUIFormatting(unittest.TestCase):
    def test_cell_ghosting(self):
        # Ghost cell (<= 0.5V)
        voltages = [0.0, 3.3, 3.3, 3.3]
        v, ghost, bad = get_cell_logic(voltages, 0)
        self.assertEqual(v, 0.0)
        self.assertTrue(ghost)
        self.assertFalse(bad)

    def test_cell_healthy(self):
        # Healthy cell (near average)
        voltages = [3.3, 3.3, 3.3, 3.3]
        v, ghost, bad = get_cell_logic(voltages, 0)
        self.assertEqual(v, 3.3)
        self.assertFalse(ghost)
        self.assertFalse(bad)

    def test_cell_imbalance(self):
        # Imbalanced cell (> 100mV from avg)
        # avg = (3.0 + 3.3 + 3.3 + 3.3)/4 = 3.225
        # diff = 0.225 > 0.1
        voltages = [3.0, 3.3, 3.3, 3.3]
        v, ghost, bad = get_cell_logic(voltages, 0)
        self.assertEqual(v, 3.0)
        self.assertFalse(ghost)
        self.assertTrue(bad)

if __name__ == '__main__':
    unittest.main()
