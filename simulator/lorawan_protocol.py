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

    async def build_uplink_frame(self, payload: bytes, fport: int = 1, confirmed: bool = False, fopts: bytes = b'') -> bytes:
        """
        Construct the full PHYPayload for uplink, with optional FOpts for MAC commands.

        :param payload: Raw application payload (FRMPayload)
        :param fport: FPort value (0 = MAC-only, >0 = application)
        :param confirmed: Whether to mark as a confirmed uplink
        :param fopts: Optional MAC command response bytes to include in FOpts (max 15 bytes)
        :return: Full PHYPayload bytes
        """
        if len(fopts) > 15:
            raise ValueError("FOpts too long (max 15 bytes allowed)")

        devaddr_bytes = bytes.fromhex(self.dev_addr)
        nwk_skey_bytes = bytes.fromhex(self.nwk_skey)
        app_skey_bytes = bytes.fromhex(self.app_skey)

        mhdr = b'\x80' if confirmed else b'\x40'
        fcnt = self.frame_counter.to_bytes(2, 'little')
        fctrl = bytes([len(fopts)])  # FOptsLen in lower 4 bits

        # Choose correct key for encryption based on FPort
        key = nwk_skey_bytes if fport == 0 else app_skey_bytes

        # Encrypt FRMPayload
        encrypted_payload = encrypt_payload(payload, key, devaddr_bytes, self.frame_counter, 0)

        # Build MACPayload: FHDR + optional FOpts + FPort + FRMPayload
        mac_payload = (
            devaddr_bytes[::-1] +
            fctrl +
            fcnt +
            fopts +
            fport.to_bytes(1, 'big') +
            encrypted_payload
        )

        mic = calculate_mic(mhdr + mac_payload, nwk_skey_bytes, devaddr_bytes, self.frame_counter)
        phy_payload = mhdr + mac_payload + mic

        logger.debug(f"[LoRaWANProtocol] Built uplink payload with FCnt={self.frame_counter}, FOptsLen={len(fopts)}")
        self.frame_counter += 1

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
        logger.debug(f"[LoRaWANProtocol] Decrypted FRMPayload: {decrypted.hex()}")
        return decrypted