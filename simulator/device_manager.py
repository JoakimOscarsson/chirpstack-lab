import logging
import asyncio
from iot_device import IotDevice

class DeviceManager:
    """
    Manages one or more IoT devices.
    It starts each device’s uplink cycle and handles downlink dispatch.
    """

    def __init__(self, gateway):
        self.logger = logging.getLogger(__name__)
        self.gateway = gateway
        self.devices = []
        self.device_tasks = []
        self.device_map = {}

    def add_device(self, dev_addr, nwk_skey, app_skey, send_interval):
        device = IotDevice(dev_addr, nwk_skey, app_skey, send_interval)
        # Inject the RF interface callback into the device's LoRaWANModule.
        device.lorawan_module.set_rf_interface(self.gateway.send_uplink_async)
        self.devices.append(device)
        self.device_map[dev_addr.upper()] = device
        self.logger.info(f"Added IotDevice devaddr={dev_addr}, interval={send_interval}")

    async def start_all_devices_async(self):
        """
        Start the uplink cycle for each device.
        """
        loop = asyncio.get_running_loop()
        for device in self.devices:
            task = loop.create_task(device.run_uplink_cycle())
            self.device_tasks.append(task)
        self.logger.info(f"Spawned {len(self.device_tasks)} device task(s).")
        await asyncio.gather(*self.device_tasks)

    def dispatch_downlink(self, raw_payload):
        """
        Stub: Dispatch incoming downlink to the appropriate device based on DevAddr.
        """
        self.logger.debug("dispatch_downlink triggered")
        if len(raw_payload) < 5:
            self.logger.warning("payload < 5 bytes, ignoring.")
            return
        devaddr = raw_payload[1:5][::-1].hex().upper()
        device = self.device_map.get(devaddr).lorawan_module  # TODO: Make unaware of lorawan_modules. make an interface
        if device:
            self.logger.info(f"Forwarding downlink to device {devaddr}")
            #asyncio.create_task(device.receive_downlink(raw_payload))
            asyncio.create_task(device.handle_downlink_payload(raw_payload))
        else:
            self.logger.debug(f"No matching device found for DevAddr={devaddr}")