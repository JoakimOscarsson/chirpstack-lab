import asyncio
import logging
import random
from radio_phy import RadioPHY
from lorawan_protocol import LoRaWANProtocol
from mac_commands import MACCommandHandler, parse_mac_commands
from utils import RadioEnvelope, calculate_airtime, dr_to_sf_bw
from typing import Optional
from channel_simulator import ChannelSimulator

logger = logging.getLogger(__name__)

class LoRaWANStack:
    """
    High-level coordinator that ties together the radio layer, protocol logic,
    and MAC command handling for a single LoRaWAN device.
    """

    def __init__(self, dev_addr, nwk_skey, app_skey, distance, environment, message_bus=None, channel_simulator=None):
        self.dev_addr = dev_addr
        self.distance = distance
        self.environment = environment

        # Core components
        self.radio = RadioPHY()
        self.protocol = LoRaWANProtocol(dev_addr, nwk_skey, app_skey)
        self.mac_handler = MACCommandHandler(self.radio)
        self.channel_simulator = channel_simulator or ChannelSimulator(distance=distance, environment=environment)

        # Uplink interface (e.g. a gateway callback)
        self.uplink_interface = None

        # Subscribe to downlink events
        if message_bus:
            message_bus.subscribe(self._receive_downlink_message)

        # Track confirmed
        self.waiting_for_ack = False
        self.pending_fcnt = None
        self.ack_event = None
        self.ack_callback = None

        # Timing
        self.rx1_open = False
        self.rx2_open = False

        self.send_lock = asyncio.Lock()

        self.pending_mac_response_bytes = None

        logger.info(f"    Initialized for DevAddr={dev_addr}")

    def set_uplink_interface(self, callback):
        """Set async callback used to forward uplinks to the gateway."""
        self.uplink_interface = callback


    async def safe_send(self, app_payload: bytes, fport: int = 1, confirmed: bool = False):
        """
        Send an uplink payload with a lock to ensure thread safety.
        """
        async with self.send_lock:
            await self._send(app_payload, fport, confirmed)

    async def _send(self, app_payload: bytes, fport: int = 1, confirmed: bool = False):
        """
        Build and transmit an uplink containing the application payload.
        """
        max_ack_attempts = self.radio.max_ack_retries if confirmed else 1
        nb_trans = self.radio.nb_trans or 1
        fcnt = self.protocol.frame_counter

        if confirmed:
            self.waiting_for_ack = True
            self.pending_fcnt = fcnt
            self.ack_event = asyncio.Event()
        
        if self.pending_mac_response_bytes and len(self.pending_mac_response_bytes) <= 15:
            fopts = self.pending_mac_response_bytes
            logger.info(f"        \033[94mIncluding MAC response in FOpts: {fopts.hex()}\033[0m")
            self.pending_mac_response_bytes = None
            uplink_bytes = await self.protocol.build_uplink_frame(
                app_payload, fport=fport, confirmed=confirmed, fopts=fopts
            )

        elif self.pending_mac_response_bytes:
            uplink_bytes = await self.protocol.build_uplink_frame(
                self.pending_mac_response_bytes, fport=0, confirmed=False
            )
            self.pending_mac_response_bytes = None
        else:
            uplink_bytes = await self.protocol.build_uplink_frame(
                app_payload, fport, confirmed
            )


        sf, bw = self.radio.get_spreading_factor(), self.radio.get_bandwidth()
        payload_size = len(uplink_bytes)
        airtime = calculate_airtime(payload_size, sf, bw)

        for ack_attempt in range(max_ack_attempts):
            logger.info(f"            Sending uplink (Attempt {ack_attempt+1}/{max_ack_attempts})")
            await self._send_nb_transmissions(
                uplink_bytes, nb_trans, sf, bw, airtime, ack_attempt, confirmed
            )
            if not confirmed:
                break
            if self.ack_event.is_set():
                logger.info(f"            \033[92mTransmission successful after {ack_attempt+1} attempt(s).\033[0m")
                break
            await self._handle_ack_timeout_and_backoff(ack_attempt)

        self.waiting_for_ack = False
        self.pending_fcnt = None
        self.ack_event = None
    
    async def _send_nb_transmissions(self, uplink_bytes, nb_trans, sf, bw, airtime, ack_attempt, confirmed):
        for nb_attempt in range(nb_trans):
            logger.info(f"                Transmission number {nb_attempt+1}/{nb_trans}")   
            while True:
                available, time_to_ready = await self._check_channel_availability(airtime)
                if available:
                    break
                if time_to_ready is not None and time_to_ready != float("inf"):
                    logger.info(f"                    All channels busy. Waiting {time_to_ready:.2f}s.")
                    await asyncio.sleep(time_to_ready)
                else:
                    logger.error("                    No available channel for transmission. Waiting fallback 1s.")
                    await asyncio.sleep(1.0)

            envelope = await self._build_envelope(uplink_bytes, sf, bw)
            envelope = await self.channel_simulator.simulate_uplink(envelope)
            if envelope is not None:  # Uplink dropped by channel simulator
                if self.uplink_interface:  # TODO: Change design so this is mandatory when initializing the stack
                    logger.info(f"                    Uplink sent to gateway on channel {self.radio.current_channel_index} ")
                    await self.uplink_interface(envelope)
                    logger.debug(
                        f"[LoRaWANStack] Sent nbTrans {nb_attempt + 1}/{nb_trans} (retry {ack_attempt}) "
                        f"on channel {self.radio.current_channel_index} ({self.radio.get_current_frequency()} Hz)"
                    )

            self.radio.record_transmission(self.radio.current_channel_index, airtime)  # For calculating time to next allowed transmission
            asyncio.create_task(self._control_tx1_window())
            await asyncio.sleep(self.radio.rx_delay_secs + 1 + random.uniform(*self.radio.nbtrans_backoff_range))
            self.radio.rotate_channel()
            if confirmed and self.ack_event.is_set():
                logger.info(f"                \033[92mACK received after nb_trans number {nb_attempt + 1}.\033[0m")
                break

    async def _check_channel_availability(self, airtime) -> tuple[bool, Optional[float]]:
        agg_ok, agg_wait = self.radio.can_transmit_aggregated(airtime)
        if not agg_ok:
            logger.info(f"                    Aggregated duty cycle exceeded, wait {agg_wait:.2f}s.")
            return False, agg_wait        


        shortest_time_to_ready = float("inf")

        for _ in range(len(self.radio.enabled_channels)):
            ready, time_to_ready = self.radio.can_transmit(self.radio.current_channel_index, airtime)
            if ready:
                logger.debug(f"                    Channel {self.radio.current_channel_index} is available for transmission.")
                return True, None
            elif time_to_ready is not None:
                shortest_time_to_ready = min(shortest_time_to_ready, time_to_ready)
            self.radio.rotate_channel()
        
        if shortest_time_to_ready != float("inf"):
            logger.info(f"                    No channel available for another {shortest_time_to_ready:.2f}s.")
            return False, shortest_time_to_ready
        else:
            logger.error("                    No available channel for transmission.")
            return False, None
            
    async def _build_envelope(self, payload, sf, bw) -> RadioEnvelope:
        envelope = RadioEnvelope(
            payload=payload,
            devaddr=self.dev_addr,
            freq=self.radio.get_current_frequency() / 1e6,
            chan=self.radio.current_channel_index,
            spreading_factor=sf,
            bandwidth=bw,
            coding_rate=self.radio.coding_rate,
            data_rate=f"SF{sf}BW{bw}",
            tx_power=self.radio.tx_power,
            distance=self.distance,
            environment=self.environment
        )
        envelope.enrich()
        return envelope
    
    async def _handle_ack_timeout_and_backoff(self, ack_attempt):
        try:
            timeout = self.radio.rx_delay_secs + 1.1
            logger.debug(f"[LoRaWANStack] Waiting for ACK (retry {ack_attempt + 1}) timeout={timeout}s")
            await asyncio.wait_for(self.ack_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"         \033[93mACK not received after attempt {ack_attempt + 1}/{self.radio.max_ack_retries}\033[0m")
            backoff = random.uniform(*self.radio.retry_backoff_range) * (ack_attempt + 1)
            logger.debug(f"[LoRaWANStack] Backing off {backoff:.1f}s before retrying confirmed uplink")
            await asyncio.sleep(backoff)

    async def _control_tx1_window(self):
        """
        Control RX1 window for downlink reception.
        """
        rx1_delay = self.radio.rx_delay_secs  # usually 1s
        rx1_jitter_tolerance = 0.02  # 20ms early open
        rx1_duration = self.radio.get_window_duration(self.radio.get_spreading_factor(), self.radio.get_bandwidth())

        await asyncio.sleep(rx1_delay - rx1_jitter_tolerance)
        self.rx1_open = True
        asyncio.create_task(self._control_tx2_window(rx1_jitter_tolerance))
        logger.info(f"                    RX1 window opened for DevAddr={self.dev_addr}")
        
        await asyncio.sleep(rx1_jitter_tolerance + rx1_duration)
        self.rx1_open = False
        logger.info(f"                    RX1 window closed for DevAddr={self.dev_addr}")

    async def _control_tx2_window(self, jitter_tolerance):
        """
        Control TX2 window for downlink reception.
        """
        jitter_tolerance = 0.02  # 20ms early
        rx2_sf = self.radio.get_spreading_factor(self.radio.rx2_datarate)
        rx2_bw = self.radio.get_bandwidth(self.radio.rx2_datarate)
        rx2_duration = self.radio.get_window_duration(rx2_sf, rx2_bw)

        await asyncio.sleep(1 - jitter_tolerance)
        self.rx2_open = True
        logger.info(f"                    RX2 window opened for DevAddr={self.dev_addr}")
        await asyncio.sleep(rx2_duration + jitter_tolerance)
        self.rx2_open = False
        logger.info(f"                    RX2 window closed for DevAddr={self.dev_addr}")

    async def _receive_downlink_message(self, envelope: RadioEnvelope):  # TODO: Maybe this is more of a incoming transmision attempt, rather than received?
        """
        Handle a downlink message delivered via the message bus.
        """
        if len(envelope.payload) < 5:
            return

        devaddr = envelope.payload[1:5][::-1].hex().upper()
        if devaddr != self.dev_addr:
            return

        payload = await self.channel_simulator.simulate_downlink(envelope)
        if payload is None:
            logger.info(f"                        \033[91mDownlink dropped for DevAddr={self.dev_addr}\033[0m")
            return
        
        uplink_dr_index = self.radio.data_rate
        expected_rx1_dr = self.radio.get_rx1_datarate(uplink_dr_index)
        rx1_sf, rx1_bw = dr_to_sf_bw(expected_rx1_dr)
        expected_rx1_datr = f"SF{rx1_sf}BW{rx1_bw}"

        rx1_freq = self.radio.get_current_frequency()
        rx2_freq = self.radio.rx2_frequency
        if self.rx1_open and int(envelope.freq * 1e6) == rx1_freq and envelope.data_rate == expected_rx1_datr:
            window = "RX1"
        elif self.rx2_open and int(envelope.freq * 1e6) == rx2_freq:
            window = "RX2"
        else:
            logger.warning(
                f"[LoRaWANStack] Downlink ignored (no window open or freq/DR mismatch) for Devaddr={devaddr}: "
                f"Freq={envelope.freq * 1e6} MHz, DR={envelope.data_rate}, expected RX1 DR={expected_rx1_datr}, RX1={rx1_freq}, RX2={rx2_freq}"
                f"RX1 open={self.rx1_open}, RX2 open={self.rx2_open}"
            )
            return
        
        logger.info(f"                        Downlink accepted in {window} for DevAddr={self.dev_addr}")
        self.radio.last_snr = envelope.snr
        await self._process_downlink(payload)

    async def _process_downlink(self, raw_bytes: bytes):
        """
        Parse and process a received downlink payload.
        """
        logger.debug(f"[LoRaWANStack] Raw downlink: {raw_bytes.hex()}")
        mtype = raw_bytes[0] >> 5
        if mtype not in (0b011, 0b101):
            logger.info("[LoRaWANStack] Ignoring non-data downlink")
            return False

        devaddr = raw_bytes[1:5][::-1].hex().upper()
        if devaddr != self.dev_addr:
            logger.warning(f"[LoRaWANStack] DevAddr mismatch: got {devaddr}, expected {self.dev_addr}")
            return False

        fctrl = raw_bytes[5]
        fopts_len = fctrl & 0x0F
        fcnt = int.from_bytes(raw_bytes[6:8], 'little')


        # Apply MAC commands in FOpts (if present)
        fopts = raw_bytes[8:8 + fopts_len]
        if fopts:
            commands = parse_mac_commands(fopts)
            for cmd in commands:
                logger.info(f"                            Received MAC command (FOpts): {cmd.name} ({cmd.cid})")
                self.mac_handler.apply_mac_command(cmd)

        # Handle ACK flag (even if there's no payload)
        ack_flag = (fctrl & 0b00100000) != 0
        if self.waiting_for_ack and ack_flag:
            logger.debug(f"[LoRaWANStack] ACK received in downlink FCnt={fcnt}.")
            self.ack_event.set()
            if self.ack_callback:
                self.ack_callback()

        # Only try to extract FPort/FRMPayload if long enough
        fport_index = 8 + fopts_len
        has_frmpayload = fport_index < len(raw_bytes) - 4

        if not has_frmpayload:
            logger.info("                        No FPort/FRMPayload in downlink — MAC-only via FOpts.")
            mac_response = self.mac_handler.get_mac_response_payload()
            if mac_response:
                logger.info("                            Queuing MAC response for next uplink")
                self.pending_mac_response_bytes = mac_response
    
            return True


        fport = raw_bytes[fport_index]
        frmpayload = raw_bytes[fport_index + 1:-4]  # Strip MIC

        if fport == 0:
            decrypted = self.protocol.decrypt_downlink_payload(frmpayload, fcnt, is_nwk=True)
            commands = parse_mac_commands(decrypted)
            for cmd in commands:
                logger.info(f"                            Received MAC command: {cmd.name} ({cmd.cid})")
                self.mac_handler.apply_mac_command(cmd)
            
            mac_response = self.mac_handler.get_mac_response_payload()
            if mac_response:
                logger.info("                            Queuing MAC response for next uplink")
                self.pending_mac_response_bytes = mac_response

        else:
            logger.info(f"[LoRaWANStack] App payload (port {fport}): {frmpayload.hex()}")

        return True
