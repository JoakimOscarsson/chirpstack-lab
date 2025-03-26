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
            self._parse_mac_commands(decrypted)
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

    def _parse_mac_commands(self, data: bytes):
        self.logger.info(f"Parsing MAC commands: {data.hex()}")

        cmd_lengths = {
            0x02: 0,  # LinkCheckReq
            0x03: 4,  # LinkADRReq
            0x04: 1,  # DutyCycleReq
            0x05: 4,  # RXParamSetupReq
            0x06: 0,  # DevStatusReq
            0x07: 5,  # NewChannelReq
            0x08: 1,  # RXTimingSetupReq
            0x0D: 3,  # PingSlotChannelReq
        }

        i = 0
        while i < len(data):
            cid = data[i]
            self.logger.info(f"MAC Command CID: 0x{cid:02X}")
            i += 1
            length = cmd_lengths.get(cid, None)

            if length is None:
                self.logger.warning(f"Unhandled or unknown MAC command CID: 0x{cid:02X}, skipping 1 byte")
                continue

            if i + length > len(data):
                self.logger.warning(f"Payload for CID 0x{cid:02X} is too short")
                break

            payload = data[i:i+length]
            self.logger.info(f"CID 0x{cid:02X} payload: {payload.hex()}")

            if cid == 0x02:  # LinkCheckReq
                self.logger.info("LinkCheckReq → No payload (expect LinkCheckAns with margin/gw count)")

            elif cid == 0x03:  # LinkADRReq
                dr_tx = payload[0]
                ch_mask = int.from_bytes(payload[1:3], 'little')
                redundancy = payload[3]
                self.logger.info(
                    f"LinkADRReq → DataRate_TXPower: {dr_tx}, ChMask: 0x{ch_mask:04X}, Redundancy: {redundancy}"
                )

            elif cid == 0x04:  # DutyCycleReq
                max_duty_cycle = payload[0]
                self.logger.info(f"DutyCycleReq → MaxDutyCycle: 1/{2 ** max_duty_cycle}")

            elif cid == 0x05:  # RXParamSetupReq
                dl_settings = payload[0]
                frequency = int.from_bytes(payload[1:4], 'little') * 100
                rx1_dr_offset = (dl_settings & 0x70) >> 4
                rx2_dr = dl_settings & 0x0F
                self.logger.info(
                    f"RXParamSetupReq → RX1 DR Offset: {rx1_dr_offset}, RX2 DR: {rx2_dr}, RX2 Frequency: {frequency} Hz"
                )

            elif cid == 0x06:  # DevStatusReq
                self.logger.info("DevStatusReq → No payload (expect DevStatusAns with battery/SNR)")

            elif cid == 0x07:  # NewChannelReq
                ch_index = payload[0]
                freq = int.from_bytes(payload[1:4], 'little') * 100
                dr_range = payload[4]
                min_dr = dr_range & 0x0F
                max_dr = (dr_range & 0xF0) >> 4
                self.logger.info(
                    f"NewChannelReq → Index: {ch_index}, Freq: {freq} Hz, DR Min: {min_dr}, Max: {max_dr}"
                )

            elif cid == 0x08:  # RXTimingSetupReq
                delay = payload[0] * 1  # in seconds
                self.logger.info(f"RXTimingSetupReq → RX1 Delay: {delay} seconds")

            elif cid == 0x0D:  # PingSlotChannelReq
                freq = int.from_bytes(payload[0:3], 'little') * 100
                self.logger.info(f"PingSlotChannelReq → Frequency: {freq} Hz")

            else:
                self.logger.info(f"Unhandled payload for CID 0x{cid:02X}: {payload.hex()}")

            i += length
