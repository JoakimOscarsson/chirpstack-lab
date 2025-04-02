import struct
import logging
from dataclasses import dataclass
from typing import List, Optional, Callable
from radio_phy import RadioPHY

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

# CLASS_A_MAC_COMMANDS_LORAWAN_1_0_X = {
#     # Bidirectional (request/response)
#     0x02: {"name": "LinkCheckReq/Ans", "direction": "bidirectional"},
#     0x03: {"name": "LinkADRReq/Ans", "direction": "bidirectional"},
#     0x04: {"name": "DutyCycleReq/Ans", "direction": "bidirectional"},
#     0x05: {"name": "RXParamSetupReq/Ans", "direction": "bidirectional"},
#     0x06: {"name": "DevStatusReq/Ans", "direction": "bidirectional"},
#     0x07: {"name": "NewChannelReq/Ans", "direction": "bidirectional"},
#     0x08: {"name": "RXTimingSetupReq/Ans", "direction": "bidirectional"},
#     0x09: {"name": "TXParamSetupReq/Ans", "direction": "bidirectional"},
#     0x0A: {"name": "DLChannelReq/Ans", "direction": "bidirectional"},
# }

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
        nbTrans = redundancy & 0x0F
        return {
            "DataRate_TXPower": dr_tx,
            "ChMask": f"0x{ch_mask:04X}",
            "Redundancy": redundancy,
            "NbTrans": nbTrans, 
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


class MACCommandHandler:
    """
    Applies MAC command logic using decoded MACCommand instances.
    Uses a CID-to-handler registry.
    """

    def __init__(self, radio: RadioPHY):
        self.radio = radio
        self.registry: dict[int, Callable[[MacCommand], None]] = {
            0x03: self._handle_link_adr_req,
            0x04: self._handle_duty_cycle_req,
            0x05: self._handle_rx_param_setup_req,
            0x07: self._handle_new_channel_req,
            0x08: self._handle_rx_timing_setup_req,
            0x06: self._handle_dev_status_req,
        }

    def apply_mac_command(self, cmd: MacCommand):
        handler = self.registry.get(cmd.cid)
        if handler:
            handler(cmd)
        else:
            logger.warning(f"[MAC] No handler for MAC command CID 0x{cmd.cid:02X}")

    def _handle_link_adr_req(self, cmd: MacCommand):
        dr_tx = cmd.decoded["DataRate_TXPower"]
        nb_trans = cmd.decoded["NbTrans"]
        ch_mask = cmd.decoded["ChMask"]    
        self.radio.update_link_adr(dr_tx, nb_trans)
        self.radio.apply_channel_mask(ch_mask)

    def apply_channel_mask(self, ch_mask: int):
        """
        Apply a 16-bit ChMask to enable/disable channels.
        """
        for i in range(16):
            enabled = (ch_mask >> i) & 0x01
            if enabled:
                if i not in self.enabled_channels:
                    logger.warning(f"[RadioPHY] ChMask tried to enable unknown channel {i}")
            else:
                if i in self.enabled_channels:
                    logger.debug(f"[RadioPHY] Disabling channel {i}")
                    self.enabled_channels.pop(i)
    
    def _handle_duty_cycle_req(self, cmd: MacCommand):
        logger.warning("[MAC] DutyCycleReq received, but not yet simulated")

    def _handle_rx_param_setup_req(self, cmd: MacCommand):
        self.radio.set_rx_params(
            rx1_offset=cmd.decoded["RX1_DR_Offset"],
            rx2_datarate=cmd.decoded["RX2_DR"],
            rx2_frequency=int(cmd.decoded["RX2_Frequency"].split()[0]),
            delay=1
        )
        logger.info("[MAC] Applied RXParamSetupReq")

    def _handle_new_channel_req(self, cmd: MacCommand):
        self.radio.add_channel(
            index=cmd.decoded["ChannelIndex"],
            freq=int(cmd.decoded["Frequency"].split()[0]),
            dr_min=cmd.decoded["DR_Min"],
            dr_max=cmd.decoded["DR_Max"]
        )

    def _handle_rx_timing_setup_req(self, cmd: MacCommand):
        self.radio.rx_delay_secs = int(cmd.decoded["RX1_Delay"].split()[0])
        logger.info("[MAC] Applied RXTimingSetupReq")

    def _handle_dev_status_req(self, cmd: MacCommand):
        logger.error("[MAC] DevStatusReq not yet implemented (would normally queue response)")

