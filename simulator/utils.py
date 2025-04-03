import struct
from dataclasses import dataclass
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Hash import CMAC
from typing import Optional

def encrypt_payload(payload: bytes, app_skey: bytes, devaddr: bytes, fcnt: int, direction: int) -> bytes:
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
        a_block[5] = direction  # 0 = uplink, 1 = downlink
        a_block[6:10] = devaddr[::-1]
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


# EU868 region DR index to (SF, BW)
EU868_DR_MAP = {
    0: (12, 125),  # SF12BW125
    1: (11, 125),
    2: (10, 125),
    3: (9, 125),
    4: (8, 125),
    5: (7, 125),
    6: (7, 250),
    7: (50, 0),    # FSK
}

def dr_to_sf_bw(dr_index: int, region: str = "EU868") -> tuple[int, int]:
    if region == "EU868":
        return EU868_DR_MAP.get(dr_index, (None, None))
    raise NotImplementedError(f"Region '{region}' not supported.")

def calculate_airtime(payload_size: int, sf: int, bw: int) -> float:
    """
    Estimate airtime of a LoRa packet in seconds.
    Assumes typical values: CR=4/5, header enabled, explicit mode.
    """
    bw_hz = bw * 1000
    symbol_time = (2 ** sf) / bw_hz
    preamble_symbols = 8

    payload_symb_nb = 8 + max(
        int((8 * payload_size - 4 * sf + 28 + 16) / (4 * (sf - 2))) * 4,
        0
    )

    total_symbols = preamble_symbols + payload_symb_nb
    airtime = total_symbols * symbol_time
    return airtime

@dataclass
class RadioEnvelope:
    payload: bytes
    devaddr: Optional[str] = None
    freq: Optional[float] = None
    chan: Optional[int] = None
    spreading_factor: Optional[int] = None
    bandwidth: Optional[int] = None
    coding_rate: Optional[str] = None
    data_rate: Optional[str] = None
    tx_power: Optional[int] = None
    rssi: Optional[int] = None
    snr: Optional[float] = None
    size: Optional[int] = None
    timestamp: Optional[int] = None
    utc_time: Optional[str] = None
    distance: Optional[int] = None
    environment: Optional[str] = None

    def enrich(self):
        if self.size is None:
            self.size = len(self.payload)
        if not self.data_rate and self.spreading_factor and self.bandwidth:
            self.data_rate = f"SF{self.spreading_factor}BW{self.bandwidth}"
        if not self.utc_time:
            self.utc_time = datetime.utcnow().isoformat() + "Z"