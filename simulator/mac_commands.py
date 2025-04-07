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
}

CID_LENGTHS = {
    0x02: 0,
    0x03: 4,
    0x04: 1,
    0x05: 4,
    0x06: 0,
    0x07: 5,
    0x08: 1,
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
            "ChMask": ch_mask,
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
    else:
        return {"Raw": payload.hex()}


class MACCommandHandler:
    """
    Applies MAC command logic using decoded MACCommand instances.
    Uses a CID-to-handler registry.
    """

    def __init__(self, radio: RadioPHY, get_battery_callback: Optional[Callable[[], int]] = None):
        self.radio = radio
        self.get_battery_callback = get_battery_callback
        self.registry: dict[int, Callable[[MacCommand], None]] = {
            0x03: self._handle_link_adr_req,
            0x04: self._handle_duty_cycle_req,
            0x05: self._handle_rx_param_setup_req,
            0x07: self._handle_new_channel_req,
            0x08: self._handle_rx_timing_setup_req,
            0x06: self._handle_dev_status_req,
        }
        self.pending_mac_responses = []

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

        status = 0b00000111  # Assume success for now
        self.pending_mac_responses.append((0x03, bytes([status])))

    def _handle_duty_cycle_req(self, cmd: MacCommand):
        val = cmd.payload[0]
        max_duty_cycle = 1 / (2 ** val)
        self.radio.set_max_duty_cycle(max_duty_cycle)
        logger.info(f"                                   \033[92mUpdated MaxDutyCycle: 1/{2 ** val} ({max_duty_cycle:.5f})\033[0m")
        self.pending_mac_responses.append((0x04, b''))

    def _handle_rx_param_setup_req(self, cmd: MacCommand):
        self.radio.set_rx_params(
            rx1_offset=cmd.decoded["RX1_DR_Offset"],
            rx2_datarate=cmd.decoded["RX2_DR"],
            rx2_frequency=int(cmd.decoded["RX2_Frequency"].split()[0]),
            delay=1
        )
        logger.debug("[MAC] Applied RXParamSetupReq")
        # Status bits: bit 0=RX1 offset OK, bit 1=RX2 DR OK, bit 2=RX2 freq OK
        status = 0b00000111  # Assume valid for now
        self.pending_mac_responses.append((0x05, bytes([status])))

    def _handle_new_channel_req(self, cmd: MacCommand):
        self.radio.add_channel(
            index=cmd.decoded["ChannelIndex"],
            freq=int(cmd.decoded["Frequency"].split()[0]),
            dr_min=cmd.decoded["DR_Min"],
            dr_max=cmd.decoded["DR_Max"]
        )
        # Bit 0: Channel index OK
        # Bit 1: DR range OK
        # Bit 2: Channel freq OK
        status = 0b00000111  # Assume OK
        self.pending_mac_responses.append((0x07, bytes([status])))


    def _handle_rx_timing_setup_req(self, cmd: MacCommand):
        self.radio.rx_delay_secs = int(cmd.decoded["RX1_Delay"].split()[0])
        logger.info(f"                                 \033[95mUpdated RX1_Delay: {self.radio.rx_delay_secs}.\033[0m")
        logger.debug("[MAC] Applied RXTimingSetupReq")
        self.pending_mac_responses.append((0x08, b''))

    def _handle_dev_status_req(self, cmd: MacCommand):
        battery = 255
        if self.get_battery_callback:
            try:
                battery = self.get_battery_callback()
            except Exception as e:
                logger.warning(f"[MAC] Failed to get battery status: {e}")
        
        margin = self.radio.last_snr if hasattr(self.radio, 'last_snr') else 0
        margin = max(-32, min(int(margin), 31))  # SNR margin capped as per spec
        payload = bytes([battery, margin & 0xFF])
        
        logger.info(f"                                 \033[95mQueuing DevStatusAns: Battery={battery}, Margin={margin}\033[0m")
        self.pending_mac_responses.append((0x06, payload))  # CID, payload
    
    def get_mac_response_payload(self) -> bytes:
        """
        Build a concatenated MAC payload from all pending MAC responses (e.g., DevStatusAns).
        Clears the pending queue after building the response.
        """
        mac_bytes = b''
        for cid, payload in self.pending_mac_responses:
            mac_bytes += bytes([cid]) + payload
        self.pending_mac_responses.clear()
        return mac_bytes

