import logging
import struct
import base64
from utils import encrypt_payload, calculate_mic
from mac_commands import parse_mac_commands
from channel_simulator import ChannelSimulator

logger = logging.getLogger(__name__)

class LoRaWANModule:
    """
    Simulates a reusable LoRaWAN transceiver module.
    Handles protocol state, frame counters, MAC commands, and downlink handling.
    """

    def __init__(self, dev_addr: str, nwk_skey: str, app_skey: str,  message_bus=None):
        """
        :param dev_addr: Device address (e.g. '26011BDA')
        :param nwk_skey: Network session key (hex string)
        :param app_skey: Application session key (hex string)
        """
        # Device identity and session keys
        self.dev_addr = dev_addr
        self.nwk_skey = nwk_skey
        self.app_skey = app_skey

        # LoRaWAN protocol state
        self.frame_counter = 0
        self.downlink_counter = 0
        self.joined = True  # For ABP simulation, assume joined

        # RX and MAC configuration
        self.rx1_delay_secs = 1  # For future timing simulations
        self.mac_response_queue = []  # For future mac responses

        # self.radio = RadioPHY()  # To simulate the physical radio parameters
        # TODO: Rename rf_interface to make it clear that its just for uplinks
        # TODO: Rename message_bus to make it clear that its the downlink interface
        self.rf_interface = None  # Callback to an async function that accepts a Base64-encoded packet.
        self.channel_simulator = ChannelSimulator(0.1)

        if message_bus:
            message_bus.subscribe(self._handle_radio_message)

        logger.info(f"[LoRaWANModule] Initialized with DevAddr={dev_addr}")

    def set_rf_interface(self, interface_callback):
        """
        Set the RF interface callback used to send uplink packets.
        """
        self.rf_interface = interface_callback

    async def send_app_payload(self, app_payload: bytes, fport: int = 1, confirmed: bool = False):
        """
        Integrates the uplink flow: receives raw application data from the device,
        builds the complete PHYPayload, and sends it using the RF interface.
        """
        uplink_bytes = await self.build_uplink_payload(app_payload, fport, confirmed)
        await self.send_uplink(uplink_bytes)

    async def build_uplink_payload(self, payload: bytes, fport: int = 1, confirmed: bool = False) -> bytes:
        """
        Construct the full uplink PHYPayload:
          - Build MHDR, FCtrl, FCnt, FPort, encrypt FRMPayload, calculate MIC.
          - Return the Base64-encoded PHYPayload.
        """
        devaddr_bytes = bytes.fromhex(self.dev_addr)
        nwk_skey_bytes = bytes.fromhex(self.nwk_skey)
        app_skey_bytes = bytes.fromhex(self.app_skey)

        mhdr = b'\x80' if confirmed else b'\x40'
        fctrl = b'\x00'
        fcnt = struct.pack('<H', self.frame_counter)

        if fport == 0:
            encrypted_payload = encrypt_payload(payload, nwk_skey_bytes, devaddr_bytes, self.frame_counter, 0)
        else:
            encrypted_payload = encrypt_payload(payload, app_skey_bytes, devaddr_bytes, self.frame_counter, 0)

        mac_payload = devaddr_bytes[::-1] + fctrl + fcnt + struct.pack('B', fport) + encrypted_payload
        mic = calculate_mic(mhdr + mac_payload, nwk_skey_bytes, devaddr_bytes, self.frame_counter)

        phy_payload = mhdr + mac_payload + mic
        self.frame_counter += 1
        
        logger.info(f"[LoRaWANModule] Built uplink for FCnt={self.frame_counter - 1}")
        return phy_payload

    async def send_uplink(self, uplink_bytes: bytes):
        """
        Transmit the uplink packet using the RF interface.
        In a real system, this might simulate RF channel effects before handing
        the packet to the gateway.
        """
        if self.channel_simulator:
            uplink_bytes = await self.channel_simulator.simulate_link(uplink_bytes)
        if uplink_bytes is None:
            logger.debug(f"[LoRaWANModule] Uplink dropped by channel simulator")
            return

        if self.rf_interface:
            await self.rf_interface(uplink_bytes)
            logger.info("[LoRaWANModule] Uplink packet sent via RF interface.")
        else:
            logger.warning("[LoRaWANModule] No RF interface set; uplink not sent.")

    async def _handle_radio_message(self, raw: bytes):
        if len(raw) < 5:
            return
        devaddr = raw[1:5][::-1].hex().upper()
        if devaddr != self.dev_addr:
            return

        if self.channel_simulator:
            raw = await self.channel_simulator.simulate_link(raw)
        if raw is None:
            logger.info(f"[LoRaWANModule] Downlink dropped by channel simulator (DevAddr={self.dev_addr})")
            return

        logger.debug(f"[LoRaWANModule] Downlink accepted for {self.dev_addr}")
        await self.handle_downlink_payload(raw)

    async def handle_downlink_payload(self, raw_bytes):
        logger.debug(f"{self.dev_addr} received raw downlink: {raw_bytes.hex()}")
        mtype = raw_bytes[0] >> 5
        if mtype not in (0b011, 0b101):
            logger.info("Downlink rejected: not an Unconfirmed/Confirmed Down")
            return False

        devaddr = raw_bytes[1:5][::-1].hex().upper()
        logger.debug(f"Extracted DevAddr from downlink: {devaddr}")
        if devaddr != self.dev_addr:
            logger.warning(f"DevAddr mismatch: got {devaddr}, expected {self.dev_addr}")
            return False

        fctrl = raw_bytes[5]
        fopts_len = fctrl & 0x0F
        fcnt_bytes = raw_bytes[6:8]
        fcnt = struct.unpack('<H', fcnt_bytes)[0]

        fport_index = 8 + fopts_len
        if fport_index >= len(raw_bytes) - 4:
            logger.warning("Downlink malformed: FPort index exceeds payload length")
            return False

        fport = raw_bytes[fport_index]
        payload = raw_bytes[fport_index + 1:-4]  # Strip MIC

        if fport == 0:
            decrypted = self._decrypt_frmpayload(payload, fcnt=fcnt, is_nwk=True)
            commands = parse_mac_commands(decrypted)
            for cmd in commands:
                logger.info(
                    f"MAC Command {cmd.name} (CID 0x{cmd.cid:02X}) → {cmd.decoded}"
                )
        else:
            logger.info(f"Device {self.dev_addr} received app payload (port {fport}): {payload}")

        return True

    def _decrypt_frmpayload(self, data: bytes, fcnt: int, is_nwk: bool = False) -> bytes:
        devaddr_bytes = bytes.fromhex(self.dev_addr)
        key = self.nwk_skey if is_nwk else self.app_skey
        key_bytes = bytes.fromhex(key)
        direction = 1  # downlink
        decrypted = encrypt_payload(data, key_bytes, devaddr_bytes, fcnt, direction)
        logger.info(f"Decrypted FRMPayload: {decrypted.hex()}")
        return decrypted

    def queue_mac_response(self, cid: int, payload: bytes):
        logger.info(f"[LoRaWANModule] queue_mac_response() not implemented for CID 0x{cid:02X}")


    def get_pending_mac_responses(self) -> bytes:
        logger.info("[LoRaWANModule] get_pending_mac_responses() not implemented")
        return b""

    def clear_mac_responses(self):
        logger.info("[LoRaWANModule] clear_mac_responses() not implemented")
        self.mac_response_queue.clear()


class RadioPHY:
    """Models radio parameters and TX-related behavior."""

    def __init__(self):
        self.enabled_channels = {
            0: {"freq": 868100000, "dr_min": 0, "dr_max": 5},
            1: {"freq": 868300000, "dr_min": 0, "dr_max": 5},
            2: {"freq": 868500000, "dr_min": 0, "dr_max": 5},
        }
        self.current_channel_index = 0
        self.last_uplink_freq = 868100000
        self.rx2_frequency = 869525000  # EU868 default RX2 freq
        self.rx2_datarate = 0           # DR0 typically
        self.rx1_dr_offset = 0
        self.dl_freq_map = {}

        self.data_rate = 0              # DR0
        self.tx_power = 0               # TX power index 0 (max power)
        self.max_eirp = 16              # dBm
        self.dwell_time_enabled = False

        # Link quality tracking
        self.last_rssi = -70            # dBm
        self.last_snr = 10.0            # dB

    def select_next_channel(self):
        logger.info("[RadioPHY] select_next_channel() not implemented")

    def get_current_frequency(self):
        logger.info("[RadioPHY] get_current_frequency() not implemented")

    def calculate_rx1_params(self, uplink_freq):
        logger.info("[RadioPHY] calculate_rx1_params() not implemented")
