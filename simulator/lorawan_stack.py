import logging
from radio_phy import RadioPHY
from lorawan_protocol import LoRaWANProtocol
from mac_commands import MACCommandHandler, parse_mac_commands
from utils import RadioEnvelope
from channel_simulator import ChannelSimulator

logger = logging.getLogger(__name__)

class LoRaWANStack:
    """
    High-level coordinator that ties together the radio layer, protocol logic,
    and MAC command handling for a single LoRaWAN device.
    """

    def __init__(self, dev_addr, nwk_skey, app_skey, distance, environment, message_bus=None, channel_simulator=None):
        self.dev_addr = dev_addr
        self.distance = distance
        self.environment = environment

        # Core components
        self.radio = RadioPHY()
        self.protocol = LoRaWANProtocol(dev_addr, nwk_skey, app_skey)
        self.mac_handler = MACCommandHandler(self.radio)
        self.channel_simulator = channel_simulator or ChannelSimulator(distance=distance, environment=environment)

        # Uplink interface (e.g. a gateway callback)
        self.rf_interface = None

        # Subscribe to downlink events
        if message_bus:
            message_bus.subscribe(self._handle_radio_message)

        logger.info(f"[LoRaWANStack] Initialized for DevAddr={dev_addr}")

    def set_rf_interface(self, callback):
        """Set async callback used to forward uplinks to the gateway."""
        self.rf_interface = callback

    async def send(self, app_payload: bytes, fport: int = 1, confirmed: bool = False):
        """
        Build and transmit an uplink containing the application payload.
        """
        uplink_bytes = await self.protocol.build_uplink_payload(app_payload, fport, confirmed)

        envelope = RadioEnvelope(
            payload=uplink_bytes,
            devaddr=self.dev_addr,
            freq=self.radio.get_current_frequency() / 1e6,
            spreading_factor=self.radio.get_spreading_factor(),
            bandwidth=self.radio.get_bandwidth(),
            coding_rate=self.radio.coding_rate,
            data_rate=f"SF{self.radio.get_spreading_factor()}BW{self.radio.get_bandwidth()}",
            tx_power=self.radio.tx_power,
            distance=self.distance,
            environment=self.environment
        )
        envelope.enrich()

        envelope = await self.channel_simulator.simulate_uplink(envelope)
        if envelope is None:
            logger.info("[LoRaWANStack] Uplink dropped by channel simulator")
            return

        if self.rf_interface:
            await self.rf_interface(envelope)
            logger.info(f"[LoRaWANStack] Uplink sent for DevAddr={self.dev_addr}")
        else:
            logger.warning("[LoRaWANStack] No RF interface set; uplink not sent")

    async def _handle_radio_message(self, envelope: RadioEnvelope):
        """
        Handle a downlink message delivered via the message bus.
        """
        if len(envelope.payload) < 5:
            return

        devaddr = envelope.payload[1:5][::-1].hex().upper()
        if devaddr != self.dev_addr:
            return

        payload = await self.channel_simulator.simulate_downlink(envelope)
        if payload is None:
            logger.info(f"[LoRaWANStack] Downlink dropped for DevAddr={self.dev_addr}")
            return

        logger.debug(f"[LoRaWANStack] Downlink accepted for DevAddr={self.dev_addr}")
        await self._process_downlink(payload)

    async def _process_downlink(self, raw_bytes: bytes):
        """
        Parse and process a received downlink payload.
        """
        logger.debug(f"[LoRaWANStack] Raw downlink: {raw_bytes.hex()}")
        mtype = raw_bytes[0] >> 5
        if mtype not in (0b011, 0b101):
            logger.info("[LoRaWANStack] Ignoring non-data downlink")
            return False

        devaddr = raw_bytes[1:5][::-1].hex().upper()
        if devaddr != self.dev_addr:
            logger.warning(f"[LoRaWANStack] DevAddr mismatch: got {devaddr}, expected {self.dev_addr}")
            return False

        fctrl = raw_bytes[5]
        fopts_len = fctrl & 0x0F
        fcnt = int.from_bytes(raw_bytes[6:8], 'little')
        fport_index = 8 + fopts_len

        if fport_index >= len(raw_bytes) - 4:
            logger.warning("[LoRaWANStack] Downlink malformed: FPort index exceeds length")
            return False

        fport = raw_bytes[fport_index]
        frmpayload = raw_bytes[fport_index + 1:-4]  # Strip MIC

        if fport == 0:
            decrypted = self.protocol.decrypt_frmpayload(frmpayload, fcnt, is_nwk=True)
            commands = parse_mac_commands(decrypted)
            for cmd in commands:
                self.mac_handler.apply_mac_command(cmd)
        else:
            logger.info(f"[LoRaWANStack] App payload (port {fport}): {frmpayload.hex()}")

        return True
