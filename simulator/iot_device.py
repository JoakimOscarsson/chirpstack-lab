import logging
import asyncio
#from lorawan_module import LoRaWANModule
from lorawan_stack import LoRaWANStack

logger = logging.getLogger(__name__)

class IotDevice:
    """
    Represents an application-level IoT device.
    It simply generates raw sensor or event data and delegates
    transmission to its LoRaWANModule. The device is unaware of protocol
    details like frame counters, encryption, etc.
    """


    def __init__(self, dev_addr, nwk_skey, app_skey, distance, environment, send_interval=10, message_bus=None):
        """
        :param dev_addr: Device address (e.g. '26011BDA')
        :param nwk_skey: Hex string for network session key
        :param app_skey: Hex string for application session key
        :param send_interval: Uplink send interval (seconds)
        """
        self.send_interval = send_interval
        self.lorawan_module = LoRaWANStack(
            dev_addr=dev_addr,
            nwk_skey=nwk_skey,
            app_skey=app_skey,
            distance=distance,
            environment=environment,
            message_bus=message_bus
        )
        self.lorawan_module.mac_handler.get_battery_callback = self.get_battery_status  # TODO: implement setter instead of this callchain.
        self.lorawan_module.ack_callback = self.on_acc_received
        logger.info(f"[IotDevice] Initialized with DevAddr={dev_addr}")

    def get_battery_status(self) -> int:
        """
        Return battery level:
        - 0: external
        - 1–254: 1–100 (%)
        - 255: unknown
        """
        return 240

    def on_acc_received(self):
        """
        Hook for application-level downlink processing (optional).
        """
        logger.info("                           \033[94mApplication received ACK\033[0m")
        
    async def generate_app_payload(self) -> bytes:
        """
        Simulate application-level data generation (e.g., sensor reading).
        """
        logger.debug("[IotDevice] generate_app_payload() called.")
        return b'\x01\x64'  # Example: sensor type + value

    async def run_uplink_cycle(self):
        """
        Periodically generate and send application payloads via the LoRaWAN stack.
        """
        while True:
            require_ack = True
            raw_payload = await self.generate_app_payload()
            logger.info(f"           \033[94mNew transmission from application. Require ACK: {require_ack}\033[0m")
            await self.lorawan_module.safe_send(raw_payload, confirmed = require_ack)
            await asyncio.sleep(self.send_interval)

    async def receive_downlink(self, data: bytes):
        """
        Hook for application-level downlink processing (optional).
        """
        logger.info(f"[IotDevice] receive_downlink() called, data: {data.hex()}")