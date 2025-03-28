import logging
import asyncio
from lorawan_module import LoRaWANModule

logger = logging.getLogger(__name__)

class IotDevice:
    """
    Represents an application-level IoT device.
    It simply generates raw sensor or event data and delegates
    transmission to its LoRaWANModule. The device is unaware of protocol
    details like frame counters, encryption, etc.
    """

    def __init__(self, dev_addr, nwk_skey, app_skey, send_interval=10):
        """
        :param dev_addr: Device address (e.g. '26011BDA')
        :param nwk_skey: Hex string for network session key
        :param app_skey: Hex string for application session key
        :param send_interval: Uplink send interval (seconds)
        """
        self.send_interval = send_interval
        self.lorawan_module = LoRaWANModule(dev_addr, nwk_skey, app_skey)
        logger.info(f"[IotDevice] Initialized with DevAddr={dev_addr}")

    async def generate_app_payload(self) -> bytes:
        """
        Generate raw application data.
        In a real device, this would be sensor readings or event data.
        Here, we simply return a fixed sensor reading.
        """
        logger.debug("[IotDevice] generate_app_payload() called.")
        # For example: sensor type 0x01 and a dummy reading 0x64 (100 decimal)
        return b'\x01\x64'

    async def run_uplink_cycle(self):
        """
        Periodically generate raw application data and instruct the LoRaWANModule
        to build and send the full uplink PHYPayload. The device never handles
        protocol-level details.
        """
        while True:
            raw_payload = await self.generate_app_payload()
            logger.debug(f"[IotDevice] Generated raw payload: {raw_payload.hex()}")
            await self.lorawan_module.send_app_payload(raw_payload)  # Could add fport and confirmed here if needed.
            await asyncio.sleep(self.send_interval)

    async def receive_downlink(self, data: bytes):
        """
        Stub for handling downlinks.
        """
        logger.info(f"[IotDevice] receive_downlink() called, data: {data.hex()}")