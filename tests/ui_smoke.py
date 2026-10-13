"""Run with py -3 -X utf8 tests/ui_smoke.py; no Bluetooth/network needed."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import asyncio
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop
from app.windows.main_window import MainWindow
from app.theme import apply_theme
from test_mobile_parity import FakeGatt
from app.constants import UUID_PRU_NOTIFY


async def smoke(app):
    with patch("app.windows.main_window.UpdateController"):
        window = MainWindow()
    window.show()
    assert window.stack.count() == 5
    assert not hasattr(window, "dac_page")
    assert not hasattr(window.scan_page, "filter_check")
    assert not window.windowIcon().isNull()
    assert not app.windowIcon().isNull()
    assert window.menu_page.ota_btn.text() == "設備更新"
    assert window.menu_page.back_btn.text() == "← 返回掃描"
    window.ota_page.path = Path("previous-device.bin")
    window.ota_page.file_label.setText("previous-device.bin")
    window.ota_page.enter_page()
    assert window.ota_page.path is None
    assert "previous-device" not in window.ota_page.file_label.text()
    finalized = []
    async def transfer():
        try:
            await asyncio.sleep(60)
        finally:
            await asyncio.sleep(.01)
            finalized.append(True)
    window.ota_page.task = asyncio.create_task(transfer())
    await asyncio.sleep(0)
    await window.ota_page.close_session()
    assert finalized == [True]
    fake = FakeGatt()
    fake.connected_devices = lambda: [("AA:BB", "0501ST")]
    fake.services = lambda: []
    async def disconnect():
        fake.is_connected = False
    fake.disconnect = fake.disconnect_all = disconnect
    window.ble = window.scan_page.ble = window.pru_page.ble = window.info_page.ble = fake
    window._on_connected("AA:BB", "0501ST")
    assert window.stack.currentWidget() is window.menu_page
    window._open_pru()
    await asyncio.sleep(.6)
    controller = window.pru_page.controller
    assert controller.link_state == "ready"
    assert controller.dynamic is not None
    assert window.pru_page.dynamic_card.tiles['VRECT'].value_label.text() == '0'
    assert window.pru_page.static_card.tree.topLevelItemCount() > 10
    window.pru_page.ctrl_combo.setCurrentText("EN_TIME_SET:20ms")
    window.pru_page.ctrl_send_btn.click()
    await asyncio.sleep(.03)
    assert controller.results["control"].phase == "sent"
    window.pru_page.disable_btn.click()
    await asyncio.sleep(.03)
    assert controller.results["control"].label == "DISABLE"
    window.pru_page.live_btn.click()
    assert controller.live_state == "pausedByUser"
    window.pru_page.interval_combo.setCurrentIndex(0)
    assert controller.poll_interval == .5
    output = Path(os.environ.get('GIOS_TEST_ARTIFACTS', Path(__file__).resolve().parents[1] / 'artifacts'))
    output.mkdir(exist_ok=True)
    assert window.grab().save(str(output / "pru_desktop.png"))
    # Exercise notification actions and the expanded view under the real Qt/async bridge.
    raw = bytearray(20)
    raw[0], raw[9], raw[16] = 0xdc, 65, 0x88
    for offset, value in ((1, 500), (3, 120), (5, 490), (7, 110), (10, 400), (12, 500), (14, 600)):
        raw[offset:offset+2] = value.to_bytes(2, 'little')
    fake.dynamic_raw = raw
    static_raw = bytearray(20)
    static_raw[3], static_raw[4], static_raw[5], static_raw[6], static_raw[7] = 3, 0x84, 0xF1, 0xE3, 5
    for offset, value in ((8, 350), (12, 450), (10, 650)):
        static_raw[offset:offset+2] = value.to_bytes(2, 'little')
    fake.static_raw = static_raw
    await controller.refresh_static()
    await controller.refresh_dynamic()
    fake.callback(UUID_PRU_NOTIFY, bytes.fromhex('88 01 02 03 04 05 06'))
    assert window.pru_page.snack_action_btn.text() == '詳細'
    window.pru_page.snack_action_btn.click()
    app.processEvents()
    dialog = window.pru_page._alert_dialog
    assert '01:02:03:04:05:06' in dialog.text()
    assert dialog.grab().save(str(output / 'pru_alert_detail.png'))
    dialog.close()
    window.pru_page.static_card.expand_btn.click()
    app.processEvents()
    assert not window.pru_page.static_card.details.isHidden()
    assert window.pru_page.scroll.widget().grab().save(str(output / 'pru_feedback_full.png'))
    assert window.pru_page.dynamic_card.alert_bits.chips[0].property('level') == 'error'
    assert window.pru_page.dynamic_card.alert_bits.chips[4].property('level') == 'success'
    await window._back_to_menu()
    assert controller.disposed
    await window._back_to_scan()
    assert fake.is_connected
    assert "已連線" in window.scan_page.list_widget.item(0).text()
    window._open_pru()
    await asyncio.sleep(.6)
    assert window.pru_page.controller is not controller
    assert window.pru_page.controller.alert_count == 0
    assert window.pru_page.static_card.details.isHidden()
    assert window.pru_page.snack_box.isHidden()
    await window._shutdown()
    assert not fake.is_connected
    print("PASS: 5 pages; PRU commands; pause/interval; alert detail; mixed flag colors; static collapse; retained connection; clean reentry/shutdown")


app = QApplication([])
apply_theme(app)
app.setQuitOnLastWindowClosed(False)
loop = QEventLoop(app)
asyncio.set_event_loop(loop)
with loop:
    loop.run_until_complete(smoke(app))
