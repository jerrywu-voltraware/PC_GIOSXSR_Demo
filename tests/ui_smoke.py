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
    output = Path(__file__).resolve().parents[1] / "artifacts"
    output.mkdir(exist_ok=True)
    assert window.grab().save(str(output / "pru_desktop.png"))
    await window._back_to_menu()
    assert controller.disposed
    await window._back_to_scan()
    assert fake.is_connected
    assert "已連線" in window.scan_page.list_widget.item(0).text()
    window._open_pru()
    await asyncio.sleep(.6)
    assert window.pru_page.controller is not controller
    assert window.pru_page.controller.alert_count == 0
    await window._shutdown()
    assert not fake.is_connected
    print("PASS: 5 pages; no DAC; controller-driven PRU; quick commands; pause/interval; retained connection; page reentry; clean shutdown")


app = QApplication([])
apply_theme(app)
app.setQuitOnLastWindowClosed(False)
loop = QEventLoop(app)
asyncio.set_event_loop(loop)
with loop:
    loop.run_until_complete(smoke(app))
