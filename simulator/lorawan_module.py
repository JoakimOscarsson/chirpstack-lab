import logging
import struct
import base64
from utils import encrypt_payload, calculate_mic

logger = logging.getLogger(__name__)

class LoRaWANModule:
    """
    Simulates a reusable LoRaWAN transceiver module.
    Handles protocol state, frame counters, MAC commands, and downlink handling.
    """

    def __init__(self, dev_addr: str, nwk_skey: str, app_skey: str):
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

        # PHY and regional behavior
        # To be introduced later!
        # self.radio = RadioPHY()  # To simulate the physical radio parameters
        self.rf_interface = None  # Callback to an async function that accepts a Base64-encoded packet.

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
        uplink_packet = await self.build_uplink_payload(app_payload, fport, confirmed)
        await self.send_uplink(uplink_packet)

    async def build_uplink_payload(self, payload: bytes, fport: int = 1, confirmed: bool = False) -> str:
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
        encoded = base64.b64encode(phy_payload).decode()

        logger.info(f"[LoRaWANModule] Built uplink for FCnt={self.frame_counter}")
        self.frame_counter += 1

        return encoded

    async def send_uplink(self, uplink_packet: str):
        """
        Transmit the uplink packet using the RF interface.
        In a real system, this might simulate RF channel effects before handing
        the packet to the gateway.
        """
        if self.rf_interface:
            await self.rf_interface(uplink_packet)
            logger.info("[LoRaWANModule] Uplink packet sent via RF interface.")
        else:
            logger.warning("[LoRaWANModule] No RF interface set; uplink not sent.")

    def handle_downlink_payload(self, raw_bytes: bytes) -> bool:
        logger.info("[LoRaWANModule] handle_downlink_payload() not implemented")
        return False

    def parse_mac_commands(self, payload: bytes):
        logger.info("[LoRaWANModule] parse_mac_commands() not implemented")

    def queue_mac_response(self, cid: int, payload: bytes):
        logger.info(f"[LoRaWANModule] queue_mac_response() not implemented for CID 0x{cid:02X}")

    # TODO: Move to utils if not already
    def decrypt_payload(self, data: bytes, fcnt: int, fport: int) -> bytes:
        logger.info("[LoRaWANModule] decrypt_payload() not implemented")
        return data

    def parse_packet(self, raw: bytes):
        logger.info("[LoRaWANModule] parse_packet() not implemented")
        return {}

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
