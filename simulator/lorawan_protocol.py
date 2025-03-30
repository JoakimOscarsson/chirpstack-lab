import logging
from utils import encrypt_payload, calculate_mic, RadioEnvelope

logger = logging.getLogger(__name__)

class LoRaWANProtocol:
    """
    Handles the LoRaWAN protocol logic: building PHYPayloads, frame counters,
    encryption, and MIC generation. This class is decoupled from the radio layer
    and focuses only on protocol compliance.
    """

    def __init__(self, dev_addr: str, nwk_skey: str, app_skey: str):
        # Device identity and session keys
        self.dev_addr = dev_addr
        self.nwk_skey = nwk_skey
        self.app_skey = app_skey

        # Protocol state
        self.frame_counter = 0
        self.downlink_counter = 0
        self.joined = True  # Assume ABP for now

    async def build_uplink_frame(self, payload: bytes, fport: int = 1, confirmed: bool = False) -> bytes:
        """
        Construct the full PHYPayload for uplink.

        :param payload: Raw application payload (sensor data)
        :param fport: FPort value (0 = MAC-only, >0 = application)
        :param confirmed: Whether to mark as a confirmed uplink
        :return: Full PHYPayload bytes
        """
        devaddr_bytes = bytes.fromhex(self.dev_addr)
        nwk_skey_bytes = bytes.fromhex(self.nwk_skey)
        app_skey_bytes = bytes.fromhex(self.app_skey)

        mhdr = b'\x80' if confirmed else b'\x40'
        fctrl = b'\x00'
        fcnt = self.frame_counter.to_bytes(2, 'little')

        # Encrypt payload depending on port
        if fport == 0:
            encrypted_payload = encrypt_payload(payload, nwk_skey_bytes, devaddr_bytes, self.frame_counter, 0)
        else:
            encrypted_payload = encrypt_payload(payload, app_skey_bytes, devaddr_bytes, self.frame_counter, 0)

        mac_payload = devaddr_bytes[::-1] + fctrl + fcnt + fport.to_bytes(1, 'big') + encrypted_payload
        mic = calculate_mic(mhdr + mac_payload, nwk_skey_bytes, devaddr_bytes, self.frame_counter)

        phy_payload = mhdr + mac_payload + mic
        self.frame_counter += 1

        logger.debug(f"[LoRaWANProtocol] Built uplink payload with FCnt={self.frame_counter - 1}")
        return phy_payload

    def decrypt_downlink_payload(self, raw_bytes: bytes, fcnt: int, is_nwk: bool = False) -> bytes:
        """
        Decrypt the FRMPayload part of a downlink.

        :param raw_bytes: Encrypted FRMPayload (MAC or App data)
        :param fcnt: Frame counter used in MIC/encryption
        :param is_nwk: Whether the payload uses NwkSKey (True) or AppSKey (False)
        :return: Decrypted payload as bytes
        """
        devaddr_bytes = bytes.fromhex(self.dev_addr)
        key = self.nwk_skey if is_nwk else self.app_skey
        key_bytes = bytes.fromhex(key)
        direction = 1  # Downlink
        decrypted = encrypt_payload(raw_bytes, key_bytes, devaddr_bytes, fcnt, direction)
        logger.info(f"[LoRaWANProtocol] Decrypted FRMPayload: {decrypted.hex()}")
        return decrypted