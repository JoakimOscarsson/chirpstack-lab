import asyncio
import logging
from radio_phy import RadioPHY
from lorawan_protocol import LoRaWANProtocol
from mac_commands import MACCommandHandler, parse_mac_commands
from utils import RadioEnvelope, calculate_airtime
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
        self.uplink_interface = None

        # Subscribe to downlink events
        if message_bus:
            message_bus.subscribe(self._receive_downlink_message)

        # Track confirmed
        self.waiting_for_ack = False
        self.pending_fcnt = None
        self.ack_event = None
        self.ack_callback = None


        logger.info(f"[LoRaWANStack] Initialized for DevAddr={dev_addr}")

    def set_uplink_interface(self, callback):
        """Set async callback used to forward uplinks to the gateway."""
        self.uplink_interface = callback

    async def send(self, app_payload: bytes, fport: int = 1, confirmed: bool = False):
        """
        Build and transmit an uplink containing the application payload.
        """
        nb_trans = self.radio.nb_trans or 1
        fcnt = self.protocol.frame_counter

        if confirmed:
            self.waiting_for_ack = True
            self.pending_fcnt = fcnt
            self.ack_event = asyncio.Event()

        uplink_bytes = await self.protocol.build_uplink_frame(app_payload, fport, confirmed)
        
        for attempt in range(nb_trans):
            if confirmed and self.ack_event.is_set():
                logger.info(f"[LoRaWANStack] ACK received — stopping retransmissions at attempt {attempt}")
                break
            
            freq_hz = self.radio.get_current_frequency()
            sf = self.radio.get_spreading_factor()
            bw = self.radio.get_bandwidth()
            payload_size = len(uplink_bytes)
            airtime = calculate_airtime(payload_size, sf, bw)


            available_channel_found = False
            for _ in range(len(self.radio.enabled_channels)): 
                if self.radio.can_transmit(self.radio.current_channel_index, airtime):
                    available_channel_found = True 
                    break
                self.radio.rotate_channel()
    
            if not available_channel_found:
                logger.warning(f"[LoRaWANStack] No available channel for transmission. Waiting before retry...")
                await asyncio.sleep(2)
                continue
             
            envelope = RadioEnvelope(
                payload=uplink_bytes,
                devaddr=self.dev_addr,
                freq=self.radio.get_current_frequency() / 1e6,
                chan=self.radio.current_channel_index,
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
                logger.info("[LoRaWANStack] Uplink dropped by channel simulator.")
                continue

            if self.uplink_interface:
                await self.uplink_interface(envelope)
                self.radio.record_transmission(self.radio.current_channel_index, airtime)
                logger.info(f"[LoRaWANStack] Uplink attempt {attempt + 1}/{nb_trans} sent for DevAddr={self.dev_addr} "
                        f"on channel {self.radio.current_channel_index} ({self.radio.get_current_frequency()} Hz)")

            self.radio.rotate_channel()

            # Check where the can send is called, and if we should calculcate airtime here and there?


            if confirmed and attempt < nb_trans - 1:
                await asyncio.sleep(self.radio.rx_delay_secs + 1)

        if confirmed and self.ack_event and not self.ack_event.is_set():
            try:
                timeout = self.radio.rx_delay_secs + 1.1  # small buffer over RX2
                logger.debug(f"[LoRaWANStack] Waiting for final ACK (timeout={timeout}s)")
                await asyncio.wait_for(self.ack_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"[LoRaWANStack] ACK not received after {nb_trans} attempts.")
    
        self.waiting_for_ack = False
        self.pending_fcnt = None
        self.ack_event = None


    async def _receive_downlink_message(self, envelope: RadioEnvelope):  # TODO: Maybe this is more of a incoming transmision attempt, rather than received?
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

        logger.debug(" ")
        logger.debug(f"Checking ack_flag now. fctrl={fctrl}, waiting_for_ack={self.waiting_for_ack}")
        ack_flag = (fctrl & 0b00100000) != 0
        if self.waiting_for_ack and ack_flag:
            logger.info(f"[LoRaWANStack] ACK received in downlink FCnt={fcnt}.")
            self.ack_event.set()
            if self.ack_callback:
                self.ack_callback()
        logger.debug("Done checking ack_flag.")

        fport_index = 8 + fopts_len

        if fport_index >= len(raw_bytes) - 4:
            logger.warning("[LoRaWANStack] Downlink malformed: FPort index exceeds length")
            return False

        fport = raw_bytes[fport_index]
        frmpayload = raw_bytes[fport_index + 1:-4]  # Strip MIC

        if fport == 0:
            decrypted = self.protocol.decrypt_downlink_payload(frmpayload, fcnt, is_nwk=True)
            commands = parse_mac_commands(decrypted)
            for cmd in commands:
                self.mac_handler.apply_mac_command(cmd)
        else:
            logger.info(f"[LoRaWANStack] App payload (port {fport}): {frmpayload.hex()}")

        return True
