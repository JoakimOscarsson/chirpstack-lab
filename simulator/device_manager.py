import logging
from device import Device

class DeviceManager:
    """
    Manages one or more LoRaWAN devices. For now, we only create one device
    in main.py, but this can be easily extended.
    """
    def __init__(self, gateway, dev_addr, nwk_skey, app_skey, send_interval):
        self.logger = logging.getLogger(__name__)
        self.gateway = gateway
        self.device = Device(dev_addr, nwk_skey, app_skey)
        self.send_interval = send_interval

    def send_all_uplinks(self):
        """
        In a future version, we'd iterate over multiple devices.
        For now, just build one uplink from the single device and send it.
        """
        base64_payload = self.device.build_uplink_payload()
        self.gateway.send_uplink(base64_payload)
        self.logger.debug("DeviceManager sent an uplink via Gateway.")
