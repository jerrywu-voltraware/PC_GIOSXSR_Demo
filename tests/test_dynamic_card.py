import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from pathlib import Path
from types import SimpleNamespace
import time
from PyQt6.QtWidgets import QApplication
from app.theme import apply_theme
from app.protocol import parse_pru_dynamic, parse_pru_static
from app.windows.dynamic_info_card import DynamicInfoCard, thresholds, range_geometry, ERROR, WARNING, PRIMARY


def model(vrect=5000, validity=0xdc, alert=0):
    raw = bytearray(20)
    raw[0], raw[9], raw[16] = validity, 65, alert
    for offset, value in ((1, vrect // 10), (3, 120), (5, 490), (7, 110), (10, 400), (12, 500), (14, 600)):
        raw[offset:offset+2] = value.to_bytes(2, 'little')
    static_raw = bytearray(20)
    for offset, value in ((8, 350), (12, 450), (10, 650)):
        static_raw[offset:offset+2] = value.to_bytes(2, 'little')
    return SimpleNamespace(dynamic=parse_pru_dynamic(raw), static=parse_pru_static(static_raw),
                           dynamic_updated=time.monotonic(), dynamic_loading=False, dynamic_error='', failures=0)


class DynamicCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self):
        self.card = DynamicInfoCard()
        self.card.resize(700, 750)

    def tearDown(self):
        self.card.close()

    def test_live_sample_moves_cursor_and_updates_metric(self):
        self.card.render_model(model(4500))
        initial = self.card.range_bar.cursor_fraction
        self.card.render_model(model(5500))
        self.assertGreater(self.card.range_bar.cursor_fraction, initial)
        self.assertEqual(self.card.tiles['VRECT'].value_label.text(), '5500')
        self.assertEqual(self.card.tiles['IRECT'].value_label.text(), '120')
        self.assertEqual(self.card.range_bar.cursor_color, PRIMARY)
        self.assertEqual(self.card.markers[1].text(), 'SET\n5000')

    def test_alarm_priority_and_invalid_fields(self):
        self.card.render_model(model(7000, 0x1c, 0x80))
        self.assertEqual(self.card.tiles['VRECT'].note_label.text(), 'OV 警報')
        self.assertEqual(self.card.tiles['VOUT'].value_label.text(), '—')
        self.assertIn('無效', self.card.tiles['VOUT'].unit_label.text())
        self.assertEqual(self.card.range_bar.cursor_color, ERROR)
        self.card.render_model(model(3000))
        self.assertEqual(self.card.tiles['VRECT'].note_label.text(), 'MIN 4000 以下')
        self.assertEqual(self.card.range_bar.cursor_color, WARNING)

    def test_each_threshold_falls_back_independently(self):
        c = model(validity=0x10)
        self.assertEqual(thresholds(c.dynamic, c.static), ((4000, 4500, 6500), False))
        self.card.render_model(c)
        self.assertIn('Static', self.card.source_label.text())
        self.assertEqual(self.card.threshold_labels[1].text(), '— mV (無效)')
        self.assertEqual(thresholds(c.dynamic, None), ((4000, None, None), True))

    def test_mobile_range_padding_and_empty_state(self):
        cursor, markers = range_geometry(5000, (4000, 5000, 6000))
        self.assertEqual(cursor, .5)
        self.assertAlmostEqual(markers[0], 300 / 2600)
        self.assertEqual(range_geometry(0, (0, 0, 0))[0], .5)
        c = model(validity=0)
        c.static = None
        self.card.render_model(c)
        self.assertTrue(self.card.range_section.isHidden())
        c.dynamic = None
        self.card.render_model(c)
        self.assertTrue(self.card.content.isHidden())

    def test_error_retains_last_sample_and_visual_artifact(self):
        c = model()
        c.failures, c.dynamic_error = 2, 'read failed'
        self.card.render_model(c)
        self.assertEqual(self.card.tiles['VRECT'].value_label.text(), '5000')
        self.assertIn('×2', self.card.failure_label.text())
        c.failures, c.dynamic_error = 0, ''
        self.card.render_model(c)
        self.card.show()
        self.app.processEvents()
        output = Path(__file__).resolve().parents[1] / 'artifacts'
        output.mkdir(exist_ok=True)
        self.assertTrue(self.card.grab().save(str(output / 'dynamic_mobile_style.png')))
