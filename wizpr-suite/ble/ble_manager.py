from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from bleak import BleakClient, BleakScanner 
from bleak.backends.device import BLEDevice  
from bleak.backends.scanner import AdvertisementData  

from ..core.logging_setup import get_logger

logger = get_logger("wizpr_suite.ble")


@dataclass
class DiscoveredDevice:
    address: str
    name: str
    rssi: int


class BLEManager:
    def __init__(self) -> None:
        self._client: BleakClient | None = None

    async def scan(self, seconds: float = 5.0) -> list[DiscoveredDevice]:
        found: Dict[str, Tuple[BLEDevice, AdvertisementData]] = {}

        def _cb(device: BLEDevice, adv: AdvertisementData) -> None:
            found[device.address] = (device, adv)

        scanner = BleakScanner(detection_callback=_cb)
        await scanner.start()
        try:
            await asyncio.sleep(seconds)
        finally:
            await scanner.stop()

        out: list[DiscoveredDevice] = []
        for addr, (dev, adv) in found.items():
            name = (adv.local_name or dev.name or "").strip()
            rssi = int(getattr(adv, "rssi", 0) or 0)
            out.append(DiscoveredDevice(address=addr, name=name, rssi=rssi))
        out.sort(key=lambda d: d.rssi, reverse=True)
        logger.info("BLE scan complete: %d devices found", len(out))
        for addr, (dev, adv) in sorted(found.items(), key=lambda x: int(getattr(x[1][1], "rssi", 0) or 0), reverse=True):
            name = (adv.local_name or dev.name or "").strip() or "(no name)"
            rssi = int(getattr(adv, "rssi", 0) or 0)
            svc_uuids = [str(u) for u in (getattr(adv, "service_uuids", None) or [])]
            mfr_data = getattr(adv, "manufacturer_data", None) or {}
            mfr_str = ", ".join(f"0x{k:04X}:{v.hex()}" for k, v in mfr_data.items()) if mfr_data else ""
            logger.info("  [%4d dBm] %-36s  %-30s  svc=%s  mfr=%s",
                        rssi, addr, name, svc_uuids or "[]", mfr_str or "")
        return out

    async def connect(self, address: str, timeout: float = 12.0) -> BleakClient:
        await self.disconnect()

        device = None
        try:
            device = await BleakScanner.find_device_by_address(address, timeout=timeout)
        except Exception:
            device = None

        client = BleakClient(device or address, timeout=timeout)

        try:
            await client.connect()
        except Exception as first_err:
            try:
                await asyncio.sleep(0.5)
                device2 = await BleakScanner.find_device_by_address(address, timeout=timeout)
                client = BleakClient(device2 or address, timeout=timeout)
                await client.connect()
            except Exception:
                raise first_err

        if not client.is_connected:
            raise RuntimeError(f"Failed to connect to {address}")

        self._client = client
        logger.info("Connected BLE: %s", address)
        return client

    async def disconnect(self) -> None:
        if self._client is None:
            return
        try:
            await self._client.disconnect()
        finally:
            self._client = None
            logger.info("Disconnected BLE.")

    def client(self) -> BleakClient | None:
        return self._client
