import struct
from Crypto.Cipher import AES
from Crypto.Hash import CMAC

def encrypt_payload(payload: bytes, app_skey: bytes, devaddr: bytes, fcnt: int) -> bytes:
    """
    LoRaWAN FRMPayload encryption (Appendix A.3 of LoRaWAN spec).
    - payload: the plaintext FRMPayload
    - app_skey: the AppSKey bytes
    - devaddr: 4-byte DevAddr
    - fcnt: frame counter
    Returns the XOR-encrypted FRMPayload as bytes.
    """
    cipher = AES.new(app_skey, AES.MODE_ECB)
    size = len(payload)
    enc = bytearray()
    i = 1

    while len(enc) < size:
        a_block = bytearray(16)
        a_block[0] = 0x01
        a_block[5] = 0x00
        # DevAddr in little-endian
        a_block[6:10] = devaddr[::-1]
        # Frame counter in little-endian
        a_block[10:12] = struct.pack('<H', fcnt)
        a_block[15] = i

        s_block = cipher.encrypt(bytes(a_block))

        for b in s_block:
            if len(enc) < size:
                enc.append(b)

        i += 1

    # XOR with payload to get encrypted data
    return bytes([p ^ s for p, s in zip(payload, enc)])


def calculate_mic(phy: bytes, nwk_skey: bytes, devaddr: bytes, fcnt: int) -> bytes:
    """
    LoRaWAN MIC calculation (Appendix A.1 of LoRaWAN spec).
    - phy: The entire PHY payload except for the MIC (MHDR + MACPayload)
    - nwk_skey: The NwkSKey bytes
    - devaddr: 4-byte DevAddr
    - fcnt: frame counter
    Returns the 4-byte MIC as bytes.
    """
    b0 = bytearray(16)
    b0[0] = 0x49
    b0[5] = 0x00
    b0[6:10] = devaddr[::-1]
    b0[10:12] = struct.pack('<H', fcnt)
    b0[15] = len(phy)

    cmac = CMAC.new(nwk_skey, ciphermod=AES)
    cmac.update(b0 + phy)
    return cmac.digest()[:4]
