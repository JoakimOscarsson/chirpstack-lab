import logging
import asyncio
from device import Device

class DeviceManager:
    """
    Manages one or more LoRaWAN devices. For now, we only create one device
    in main.py, but this can be easily extended.
    """
    def __init__(self, gateway, dev_addr, nwk_skey, app_skey, send_interval):
        self.logger = logging.getLogger(__name__)
        self.gateway = gateway
        # For future expansion, we could store multiple devices in a list.
        self.device = Device(dev_addr, nwk_skey, app_skey, send_interval)

    async def run_single_device_loop(self):
        """
        Asynchronously run a loop that sends an uplink for our single device
        every 'send_interval' seconds.
        """
        while True:
            base64_payload = self.device.build_uplink_payload()
            # Non-blocking send using the Gateway's async method
            await self.gateway.send_uplink_async(base64_payload)

            # Sleep for the device's interval
            await asyncio.sleep(self.device.send_interval)
