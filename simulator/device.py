import struct
import base64
import logging
from utils import encrypt_payload, calculate_mic
from mac_commands import parse_mac_commands

class Device:
    """
    Represents a single LoRaWAN device.
    Stores DevAddr, NWK_SKEY, APP_SKEY, and frame counter.
    Builds the uplink PHYPayload (encrypted, MIC'd) as base64.
    """
    def __init__(self, dev_addr, nwk_skey, app_skey, send_interval=10):
        self.logger = logging.getLogger(__name__)
        self.dev_addr = dev_addr
        self.nwk_skey = nwk_skey
        self.app_skey = app_skey
        self.send_interval = send_interval
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
        payload = b'Simulator says hello!'

        encrypted = encrypt_payload(payload, app_skey_bytes, devaddr_bytes, self.frame_counter, 0)
        mac_payload = devaddr_bytes[::-1] + fctrl + fcnt + fport + encrypted
        mic = calculate_mic(mhdr + mac_payload, nwk_skey_bytes, devaddr_bytes, self.frame_counter)

        phy_payload = mhdr + mac_payload + mic
        encoded = base64.b64encode(phy_payload).decode()

        self.logger.info(f"Device {self.dev_addr} built uplink with FCnt={self.frame_counter}.")
        self.frame_counter += 1

        return encoded

    def handle_downlink_payload(self, raw_bytes):
        self.logger.debug(f"{self.dev_addr} received raw downlink: {raw_bytes.hex()}")
        mtype = raw_bytes[0] >> 5
        if mtype not in (0b011, 0b101):
            self.logger.info("Downlink rejected: not an Unconfirmed/Confirmed Down")
            return False

        devaddr = raw_bytes[1:5][::-1].hex().upper()
        self.logger.debug(f"Extracted DevAddr from downlink: {devaddr}")
        if devaddr != self.dev_addr:
            self.logger.warning(f"DevAddr mismatch: got {devaddr}, expected {self.dev_addr}")
            return False

        fctrl = raw_bytes[5]
        fopts_len = fctrl & 0x0F
        fcnt_bytes = raw_bytes[6:8]
        fcnt = struct.unpack('<H', fcnt_bytes)[0]

        fport_index = 8 + fopts_len
        if fport_index >= len(raw_bytes) - 4:
            self.logger.warning("Downlink malformed: FPort index exceeds payload length")
            return False

        fport = raw_bytes[fport_index]
        payload = raw_bytes[fport_index + 1:-4]  # Strip MIC

        if fport == 0:
            decrypted = self._decrypt_frmpayload(payload, fcnt=fcnt, is_nwk=True)
            commands = parse_mac_commands(decrypted)
            for cmd in commands:
                self.logger.info(
                    f"MAC Command {cmd.name} (CID 0x{cmd.cid:02X}) → {cmd.decoded}"
                )
        else:
            self.logger.info(f"Device {self.dev_addr} received app payload (port {fport}): {payload}")

        return True

    def _decrypt_frmpayload(self, data: bytes, fcnt: int, is_nwk: bool = False) -> bytes:
        devaddr_bytes = bytes.fromhex(self.dev_addr)
        key = self.nwk_skey if is_nwk else self.app_skey
        key_bytes = bytes.fromhex(key)
        direction = 1  # downlink
        decrypted = encrypt_payload(data, key_bytes, devaddr_bytes, fcnt, direction)
        self.logger.info(f"Decrypted FRMPayload: {decrypted.hex()}")
        return decrypted

