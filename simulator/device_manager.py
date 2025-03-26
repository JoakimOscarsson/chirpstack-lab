import logging
import asyncio
from device import Device

class DeviceManager:
    """
    Manages one or more LoRaWAN devices.
    """
    def __init__(self, gateway):
        self.logger = logging.getLogger(__name__)
        self.gateway = gateway
        self.devices = []
        self.device_tasks = []
        self.device_map = {}

    def add_device(self, dev_addr, nwk_skey, app_skey, send_interval):
        device = Device(dev_addr, nwk_skey, app_skey, send_interval)
        self.devices.append(device)
        self.device_map[dev_addr] = device
        self.logger.info(f"Added device {dev_addr} with interval={send_interval}.")

    async def start_all_devices_async(self):
        loop = asyncio.get_running_loop()
        for dev in self.devices:
            task = loop.create_task(self.run_device_loop(dev))
            self.device_tasks.append(task)

        self.logger.info(f"Spawned {len(self.device_tasks)} device task(s).")
        # Wait for them all to finish (they won't unless canceled)
        await asyncio.gather(*self.device_tasks)

    async def run_device_loop(self, device):
        while True:
            encoded = device.build_uplink_payload()
            await self.gateway.send_uplink_async(encoded)
            try:
                await asyncio.sleep(device.send_interval)
            except asyncio.CancelledError:
                self.logger.info(f"Device {device.dev_addr} shutting down.")
                break

    def dispatch_downlink(self, raw_payload):
        self.logger.debug("in dispatch_downlink")
        if len(raw_payload) < 5:
            self.logger.warning("payload < 5")
            return
        devaddr = raw_payload[1:5][::-1].hex().upper()
        device = self.device_map.get(devaddr)
        if device:
            self.logger.debug("Found the device!")
            device.handle_downlink_payload(raw_payload)
        else:
            self.logger.debug("device not in list")
