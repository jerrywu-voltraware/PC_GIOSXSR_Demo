"""Wire-compatible port of device_ota_screen.dart (Windows uses negotiated MTU)."""
from __future__ import annotations
import asyncio
import functools
import operator
import struct

OTA_SERVICE_UUID = "8a97f7c0-8506-11e3-baa7-0800200c9a66"
NEW_IMAGE_UUID = "210f99f0-8508-11e3-baa7-0800200c9a66"
IMAGE_CONTENT_UUID = "2691aa80-8508-11e3-baa7-0800200c9a66"
IMAGE_SEQ_UUID = "2bdc5760-8508-11e3-baa7-0800200c9a66"


def chunk_size(mtu):
    size = 16 * ((mtu - 3 - 4) // 16)
    if size < 16:
        raise ValueError("MTU 太小，無法傳輸 OTA")
    return size


def handshake(image_size):
    return struct.pack("<BII", 8, image_size, 0x10057800)


def data_packet(data, size, sequence, needs_ack):
    payload = bytes(data).ljust(size, b"\xff") + struct.pack("<BH", int(needs_ack), sequence & 0xffff)
    return bytes([functools.reduce(operator.xor, payload, 0)]) + payload


class OtaTransfer:
    ack_timeout = 2.
    settle_delay = 1.
    retry_delay = .5
    packet_delay = .001

    def __init__(self, ble, progress=lambda fraction, text: None):
        self.ble = ble
        self.progress = progress
        self._ack = None
        self._deadline = None

    def on_notification(self, uuid, raw):
        if uuid.lower() == IMAGE_SEQ_UUID and self._ack is not None and not self._ack.done():
            self._ack.set_result(bytes(raw))

    def _prepare_ack(self):
        self._ack = asyncio.get_running_loop().create_future()
        self._deadline = asyncio.get_running_loop().time() + self.ack_timeout

    async def _wait_ack(self):
        remaining = max(0, self._deadline - asyncio.get_running_loop().time())
        raw = await asyncio.wait_for(self._ack, remaining)
        if len(raw) < 4:
            raise ValueError(f"ACK 長度不足 ({len(raw)}/4 bytes)")
        return struct.unpack("<HH", raw[:4])

    def characteristics(self):
        service = next((s for s in self.ble.services() if str(s.uuid).lower() == OTA_SERVICE_UUID), None)
        if service is None:
            raise RuntimeError("找不到 OTA 服務")
        chars = {str(c.uuid).lower(): c for c in service.characteristics}
        if any(u not in chars for u in (NEW_IMAGE_UUID, IMAGE_CONTENT_UUID, IMAGE_SEQ_UUID)):
            raise RuntimeError("找不到所有必要的 OTA 特徵值")
        return chars

    async def run(self, firmware):
        if not firmware:
            raise ValueError("韌體檔案是空的")
        chars = self.characteristics()
        self.progress(0, "步驟 1/4：建立連接並取得 MTU…")
        # WinRT negotiates MTU itself; do not pretend requestMtu is available.
        mtu = self.ble.client.mtu_size
        size = chunk_size(mtu)
        await asyncio.sleep(self.settle_delay)
        if not self.ble.is_connected:
            raise RuntimeError("設備已斷線")
        self.ble.set_notification_callback(self.on_notification)
        self.progress(0, f"步驟 2/4：啟用通知與交握（MTU {mtu}）…")
        try:
            for attempt in range(3):
                try:
                    await self.ble.enable_notify(IMAGE_SEQ_UUID)
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(self.retry_delay)
            self._prepare_ack()
            await self.ble.write(chars[NEW_IMAGE_UUID], handshake(len(firmware)), response=True)
            next_seq, error = await self._wait_ack()
            if next_seq or error:
                raise RuntimeError(f"設備拒絕開始 OTA (ErrorCode: {error})")
            sent = sequence = 0
            while sent < len(firmware):
                if not self.ble.is_connected:
                    raise RuntimeError("傳輸途中設備斷線；請確認韌體版本")
                self._prepare_ack()
                window_sent, window_sequence = sent, sequence
                for index in range(8):
                    if sent >= len(firmware):
                        break
                    data = firmware[sent:sent + size]
                    needs_ack = index == 7 or sent + size >= len(firmware)
                    await self.ble.write(chars[IMAGE_CONTENT_UUID], data_packet(data, size, sequence, needs_ack), response=False)
                    await asyncio.sleep(self.packet_delay)
                    sent += len(data)
                    sequence += 1
                next_seq, error = await self._wait_ack()
                if error == 240:
                    sequence = next_seq
                    sent = min(len(firmware), next_seq * size)
                    continue
                if error == 15:
                    sent, sequence = window_sent, window_sequence
                    continue
                if error:
                    raise RuntimeError(f"韌體回報錯誤，錯誤碼: {error}")
                if next_seq != sequence:
                    sequence = next_seq
                    sent = min(len(firmware), next_seq * size)
                self.progress(sent / len(firmware), f"步驟 3/4：傳輸韌體 {sent / len(firmware):.1%}")
            self.progress(1, "步驟 4/4：傳輸完成，等待設備重啟…")
        finally:
            if self._ack and not self._ack.done():
                self._ack.cancel()
            await self.ble.disable_all_notify()
