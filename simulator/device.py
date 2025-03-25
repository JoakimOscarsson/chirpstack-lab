import struct
import base64
import logging
from utils import encrypt_payload, calculate_mic

class Device:
    """
    Represents a single LoRaWAN device.
    Stores DevAddr, NWK_SKEY, APP_SKEY, and frame counter.
    Builds the uplink PHYPayload (encrypted, MIC'd) as base64.
    """
    def __init__(self, dev_addr, nwk_skey, app_skey):
        self.logger = logging.getLogger(__name__)
        self.dev_addr = dev_addr
        self.nwk_skey = nwk_skey
        self.app_skey = app_skey
        self.frame_counter = 0

    def build_uplink_payload(self):
        """
        Constructs the LoRaWAN PHYPayload, then base64-encodes it.
        """
        devaddr_bytes = bytes.fromhex(self.dev_addr)
        nwk_skey_bytes = bytes.fromhex(self.nwk_skey)
        app_skey_bytes = bytes.fromhex(self.app_skey)

        mhdr = b'\x40'  # UnconfirmedDataUp
        fctrl = b'\x00'
        fcnt = struct.pack('<H', self.frame_counter)
        fport = b'\x01'
        payload = b'Simulator says hello through ChripStack!'

        encrypted = encrypt_payload(payload, app_skey_bytes, devaddr_bytes, self.frame_counter)
        mac_payload = devaddr_bytes[::-1] + fctrl + fcnt + fport + encrypted
        mic = calculate_mic(mhdr + mac_payload, nwk_skey_bytes, devaddr_bytes, self.frame_counter)

        phy_payload = mhdr + mac_payload + mic
        encoded = base64.b64encode(phy_payload).decode()

        self.logger.info(f"Device {self.dev_addr} built uplink with FCnt={self.frame_counter}.")
        self.frame_counter += 1

        return encoded
