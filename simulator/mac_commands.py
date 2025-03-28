import struct
import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

@dataclass
class MacCommand:
    cid: int
    name: str
    payload: bytes
    decoded: Optional[dict] = None


CID_NAMES = {
    0x02: "LinkCheckReq",
    0x03: "LinkADRReq",
    0x04: "DutyCycleReq",
    0x05: "RXParamSetupReq",
    0x06: "DevStatusReq",
    0x07: "NewChannelReq",
    0x08: "RXTimingSetupReq",
    0x0D: "PingSlotChannelReq",
}

CID_LENGTHS = {
    0x02: 0,
    0x03: 4,
    0x04: 1,
    0x05: 4,
    0x06: 0,
    0x07: 5,
    0x08: 1,
    0x0D: 3,
}

def parse_mac_commands(data: bytes) -> List[MacCommand]:
    logger.debug(f"Parsing MAC commands: {data.hex()}")
    commands = []
    i = 0
    while i < len(data):
        cid = data[i]
        name = CID_NAMES.get(cid, f"Unknown_0x{cid:02X}")
        length = CID_LENGTHS.get(cid, None)
        i += 1

        if length is None:
            logger.warning(f"Unknown MAC CID 0x{cid:02X}, skipping 1 byte")
            continue

        if i + length > len(data):
            logger.warning(f"Payload too short for CID 0x{cid:02X}")
            break

        payload = data[i:i+length]
        decoded = decode_mac_command(cid, payload)

        commands.append(MacCommand(cid, name, payload, decoded))
        i += length

    return commands


def decode_mac_command(cid: int, payload: bytes) -> dict:
    if cid == 0x03:  # LinkADRReq
        dr_tx = payload[0]
        ch_mask = int.from_bytes(payload[1:3], 'little')
        redundancy = payload[3]
        return {
            "DataRate_TXPower": dr_tx,
            "ChMask": f"0x{ch_mask:04X}",
            "Redundancy": redundancy,
        }
    elif cid == 0x04:  # DutyCycleReq
        val = payload[0]
        return {"MaxDutyCycle": f"1/{2 ** val}"}
    elif cid == 0x05:  # RXParamSetupReq
        dl_settings = payload[0]
        freq = int.from_bytes(payload[1:4], 'little') * 100
        rx1_dr_offset = (dl_settings & 0x70) >> 4
        rx2_dr = dl_settings & 0x0F
        return {
            "RX1_DR_Offset": rx1_dr_offset,
            "RX2_DR": rx2_dr,
            "RX2_Frequency": f"{freq} Hz",
        }
    elif cid == 0x06:  # DevStatusReq
        return {"Note": "No payload (respond with battery/SNR)"}
    elif cid == 0x07:  # NewChannelReq
        ch_index = payload[0]
        freq = int.from_bytes(payload[1:4], 'little') * 100
        dr_range = payload[4]
        min_dr = dr_range & 0x0F
        max_dr = (dr_range & 0xF0) >> 4
        return {
            "ChannelIndex": ch_index,
            "Frequency": f"{freq} Hz",
            "DR_Min": min_dr,
            "DR_Max": max_dr,
        }
    elif cid == 0x08:  # RXTimingSetupReq
        return {"RX1_Delay": f"{payload[0]} seconds"}
    elif cid == 0x0D:  # PingSlotChannelReq
        freq = int.from_bytes(payload[0:3], 'little') * 100
        return {"PingSlotFrequency": f"{freq} Hz"}
    else:
        return {"Raw": payload.hex()}

