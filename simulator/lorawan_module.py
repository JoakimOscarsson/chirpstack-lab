import logging
import base64
from utils import encrypt_payload, calculate_mic, RadioEnvelope, dr_to_sf_bw
from channel_simulator import ChannelSimulator
from mac_commands import MacCommand, parse_mac_commands


logger = logging.getLogger(__name__)

class LoRaWANModule:
    """
    Simulates a reusable LoRaWAN transceiver module.
    Handles protocol state, frame counters, MAC commands, and downlink handling.
    """

    def __init__(self, dev_addr: str, nwk_skey: str, app_skey: str, distance: int, environment: str, message_bus=None, channel_simulator=None):  # todo: make conditions into an enum.
        """
        :param dev_addr: Device address (e.g. '26011BDA')
        :param nwk_skey: Network session key (hex string)
        :param app_skey: Application session key (hex string)
        """
        # Device location
        self.distance = distance
        self.environment = environment

        # Device identity and session keys
        self.dev_addr = dev_addr
        self.nwk_skey = nwk_skey
        self.app_skey = app_skey

        # LoRaWAN protocol state
        self.frame_counter = 0
        self.downlink_counter = 0
        self.joined = True  # For ABP simulation, assume joined

        # RX and MAC configuration
        self.data_rate = 0
        self.rx1_dr_offset = 0
        self.rx2_frequency = 869525000
        self.rx_delay_secs = 1
        self.channel_mask = 0xFFFF
        self.adr_ack_req = False
        self.battery_level = 100  # TODO: implement function to fetch from device
        self.mac_response_queue = []  # For future mac responses

        # Radio abstraction
        self.radio = RadioPHY()

        # Interfaces
        # TODO: Rename rf_interface to make it clear that its just for uplinks
        # TODO: Rename message_bus to make it clear that its the downlink interface
        self.rf_interface = None  # Callback to an async function that accepts a Base64-encoded packet.
        self.channel_simulator = channel_simulator or ChannelSimulator(distance=distance, environment=environment)

        if message_bus:
            message_bus.subscribe(self._handle_radio_message)
            # TODO: implement printout if no message bus was provided

        logger.info(f"[LoRaWANModule] Initialized with DevAddr={dev_addr}")

    def set_rf_interface(self, interface_callback):
        """
        Set the RF interface callback used to send uplink packets.
        """
        self.rf_interface = interface_callback

    async def send_app_payload(self, app_payload: bytes, fport: int = 1, confirmed: bool = False):
        # TODO: change name to send uplink payload
        uplink_bytes = await self.build_uplink_payload(app_payload, fport, confirmed)

        # Wrap into RadioEnvelope
        envelope = RadioEnvelope(  # TODO: change into {addr, metadata, payload}
            payload=uplink_bytes,
            devaddr=self.dev_addr,
            freq=self.radio.get_current_frequency() / 1e6,
            spreading_factor=self.radio.get_spreading_factor(),
            bandwidth=self.radio.get_bandwidth(),
            coding_rate=self.radio.coding_rate,
            data_rate=f"SF{self.radio.get_spreading_factor()}BW{self.radio.get_bandwidth()}",
            tx_power=self.radio.tx_power,
            distance=self.distance,
            environment=self.environment
        )
        envelope.enrich()

        # Pass through channel simulation
        envelope = await self.channel_simulator.simulate_uplink(envelope)
        if envelope is None:
            logger.info("[LoRaWANModule] Uplink dropped by channel simulator.")
            return

        # Forward to gateway
        if self.rf_interface:
            await self.rf_interface(envelope)
            logger.info(f"[LoRaWANModule] Uplink sent from DevAddr={self.dev_addr}")
        else:
            logger.warning("[LoRaWANModule] No RF interface set; uplink not sent.")

    async def build_uplink_payload(self, payload: bytes, fport: int = 1, confirmed: bool = False) -> bytes:
        """
        Construct the full uplink PHYPayload:
          - Build MHDR, FCtrl, FCnt, FPort, encrypt FRMPayload, calculate MIC.
        """
        devaddr_bytes = bytes.fromhex(self.dev_addr)
        nwk_skey_bytes = bytes.fromhex(self.nwk_skey)
        app_skey_bytes = bytes.fromhex(self.app_skey)

        mhdr = b'\x80' if confirmed else b'\x40'
        fctrl = b'\x00'
        fcnt = self.frame_counter.to_bytes(2, 'little')

        if fport == 0:
            encrypted_payload = encrypt_payload(payload, nwk_skey_bytes, devaddr_bytes, self.frame_counter, 0)
        else:
            encrypted_payload = encrypt_payload(payload, app_skey_bytes, devaddr_bytes, self.frame_counter, 0)

        mac_payload = devaddr_bytes[::-1] + fctrl + fcnt + fport.to_bytes(1, 'big') + encrypted_payload
        mic = calculate_mic(mhdr + mac_payload, nwk_skey_bytes, devaddr_bytes, self.frame_counter)

        phy_payload = mhdr + mac_payload + mic
        self.frame_counter += 1
        
        logger.info(f"[LoRaWANModule] Built uplink for FCnt={self.frame_counter - 1}")
        return phy_payload

    async def _handle_radio_message(self, envelope:RadioEnvelope):
        if len(envelope.payload) < 5:
            return
        devaddr = envelope.payload[1:5][::-1].hex().upper()
        if devaddr != self.dev_addr:
            return

        payload = await self.channel_simulator.simulate_downlink(envelope)

        if payload is None:
            logger.info(f"[LoRaWANModule] Downlink dropped by channel simulator (DevAddr={self.dev_addr})")
            return

        logger.debug(f"[LoRaWANModule] Downlink accepted for {self.dev_addr}")
        await self.handle_downlink_payload(payload)

    async def handle_downlink_payload(self, raw_bytes):
        logger.debug(f"{self.dev_addr} received raw downlink: {raw_bytes.hex()}")
        mtype = raw_bytes[0] >> 5
        if mtype not in (0b011, 0b101):
            logger.info("Downlink rejected: not an Unconfirmed/Confirmed Down")
            return False

        devaddr = raw_bytes[1:5][::-1].hex().upper()
        logger.debug(f"Extracted DevAddr from downlink: {devaddr}")
        if devaddr != self.dev_addr:
            logger.warning(f"DevAddr mismatch: got {devaddr}, expected {self.dev_addr}")
            return False

        fctrl = raw_bytes[5]
        fopts_len = fctrl & 0x0F
        fcnt_bytes = raw_bytes[6:8]
        fcnt = int.from_bytes(fcnt_bytes, 'little')

        fport_index = 8 + fopts_len
        if fport_index >= len(raw_bytes) - 4:
            logger.warning("Downlink malformed: FPort index exceeds payload length")
            return False

        fport = raw_bytes[fport_index]
        payload = raw_bytes[fport_index + 1:-4]  # Strip MIC

        if fport == 0:
            decrypted = self._decrypt_frmpayload(payload, fcnt=fcnt, is_nwk=True)
            commands = parse_mac_commands(decrypted)
            for cmd in commands:
                logger.info(
                    f"MAC Command {cmd.name} (CID 0x{cmd.cid:02X}) → {cmd.decoded}"
                )
                self.apply_mac_command(cmd)
        else:
            logger.info(f"Device {self.dev_addr} received app payload (port {fport}): {payload}")

        return True

    def _decrypt_frmpayload(self, data: bytes, fcnt: int, is_nwk: bool = False) -> bytes:
        devaddr_bytes = bytes.fromhex(self.dev_addr)
        key = self.nwk_skey if is_nwk else self.app_skey
        key_bytes = bytes.fromhex(key)
        direction = 1  # downlink
        decrypted = encrypt_payload(data, key_bytes, devaddr_bytes, fcnt, direction)
        logger.info(f"Decrypted FRMPayload: {decrypted.hex()}")
        return decrypted


    def apply_mac_command(self, cmd: MacCommand):
        if not self.radio:
            logger.warning("No radio attached; skipping MAC command handling.")
            return

        if cmd.cid == 0x03:  # LinkADRReq
            parsed = cmd.decoded
            dr_tx = parsed["DataRate_TXPower"]
            ch_mask = parsed["ChMask"]  # Why this??
            redundancy = parsed["Redundancy"]  # Why this??

            self.radio.data_rate = dr_tx >> 4
            self.radio.tx_power = dr_tx & 0x0F
            logger.info(f"[MAC] Applied LinkADRReq → DR={self.radio.data_rate}, TXPower={self.radio.tx_power}")

        elif cmd.cid == 0x04:  # DutyCycleReq
            # Not yet used in sim
            logger.error(f"[MAC] Wanted to apply Applied DutyCycleReq, but it is not yet simulated")

        elif cmd.cid == 0x05:  # RXParamSetupReq
            self.radio.rx1_dr_offset = cmd.decoded["RX1_DR_Offset"]
            self.radio.rx2_datarate = cmd.decoded["RX2_DR"]
            self.radio.rx2_frequency = int(cmd.decoded["RX2_Frequency"].split()[0])
            logger.warning(f"[MAC] Applied RXParamSetupReq, but sim is not handling those yet!")

        elif cmd.cid == 0x07:  # NewChannelReq
            ch_idx = cmd.decoded["ChannelIndex"]
            freq = int(cmd.decoded["Frequency"].split()[0])
            dr_min = cmd.decoded["DR_Min"]
            dr_max = cmd.decoded["DR_Max"]
            self.radio.enabled_channels[ch_idx] = {
                "freq": freq,
                "dr_min": dr_min,
                "dr_max": dr_max
            }
            logger.info(f"[MAC] Added new channel → Index={ch_idx}, Freq={freq}, DR={dr_min}-{dr_max}")

        elif cmd.cid == 0x08:  # RXTimingSetupReq
            self.radio.rx_delay_secs = int(cmd.decoded["RX1_Delay"].split()[0])
            logger.warning(f"[MAC] Applied RXTimingSetupReq → RX1 Delay={self.radio.rx_delay_secs}s, but the sim is not considering timing yet!")

        elif cmd.cid == 0x06:  # DevStatusReq
            # For now, no actual response queued, but you could
            logger.error("[MAC] Received DevStatusReq. Not yet implemented! (would normally queue response)")

        else:
            logger.error(f"[MAC] No handler for CID 0x{cmd.cid:02X}")


    def queue_mac_response(self, cid: int, payload: bytes):
        logger.info(f"[LoRaWANModule] queue_mac_response() not implemented for CID 0x{cid:02X}")


    def get_pending_mac_responses(self) -> bytes:
        logger.info("[LoRaWANModule] get_pending_mac_responses() not implemented")
        return b""

    def clear_mac_responses(self):
        logger.info("[LoRaWANModule] clear_mac_responses() not implemented")
        self.mac_response_queue.clear()



class RadioPHY:
    """Models radio parameters and behavior."""

    def __init__(self):
        self.enabled_channels = {
            0: {"freq": 868100000, "dr_min": 0, "dr_max": 5},
            1: {"freq": 868300000, "dr_min": 0, "dr_max": 5},
            2: {"freq": 868500000, "dr_min": 0, "dr_max": 5},
        }
        self.current_channel_index = 0
        self.last_uplink_freq = 868100000

        # TX config (can be changed via MAC)
        self.tx_power = 14  # dBm
        self.max_eirp = 16  # Region-defined cap
        self.dwell_time_enabled = False

        # DR / modulation
        self.data_rate = 0
        self.coding_rate = "4/5"

    def get_spreading_factor(self):
        sf, _ = dr_to_sf_bw(self.data_rate)
        return sf

    def get_bandwidth(self):
        _, bw = dr_to_sf_bw(self.data_rate)
        return bw

    def get_current_frequency(self):
        return self.enabled_channels[self.current_channel_index]["freq"]

