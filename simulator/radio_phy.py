import time
import logging
from utils import dr_to_sf_bw
from typing import Optional
from collections import defaultdict
from utils import calculate_airtime

logger = logging.getLogger(__name__)

class RadioPHY:
    """
    Models radio parameters and behavior in a LoRaWAN environment.
    This class simulates the physical layer configuration including
    transmission power, modulation settings, and enabled channels.
    """

    def __init__(self):
        # Channel configuration
        self.enabled_channels = {
            0: {"freq": 868100000, "dr_min": 0, "dr_max": 5, "duty_cycle": 0.01},
            1: {"freq": 868300000, "dr_min": 0, "dr_max": 5, "duty_cycle": 0.01},
            2: {"freq": 868500000, "dr_min": 0, "dr_max": 5, "duty_cycle": 0.01},
        }
        self.current_channel_index = 0
        self.last_uplink_freq = 868100000

        # Modulation settings
        self.data_rate = 0  # LoRa DR index (e.g., 0 = SF12BW125)
        self.coding_rate = "4/5"

        # Transmission settings
        self.tx_power = 14  # dBm
        self.max_eirp = 16  # Region-defined cap
        self.dwell_time_enabled = False

        self.rx1_dr_offset = 0
        self.rx2_datarate = 0
        self.rx2_frequency = 869525000
        self.rx_delay_secs = 1
        self.nb_trans = 3
        self.max_ack_retries = 8
        self.nbtrans_backoff_range = (0.5, 2.0)
        self.retry_backoff_range = (2.0, 6.0)

        self.next_tx_time = defaultdict(lambda: 0.0)

    def get_spreading_factor(self, dr: int = None):
        """Return the spreading factor based on the current data rate."""
        sf, _ = dr_to_sf_bw(self.data_rate if dr is None else dr)
        return sf

    def get_bandwidth(self, dr: int = None):
        """Return the bandwidth in kHz based on the current data rate."""
        _, bw = dr_to_sf_bw(self.data_rate if dr is None else dr)
        return bw

    def get_current_frequency(self):
        """Return the frequency of the currently selected channel (Hz)."""
        return self.enabled_channels[self.current_channel_index]["freq"]

    def set_rx_params(self, rx1_offset: int, rx2_datarate: int, rx2_frequency: int, delay: int):
        """
        Set RX window parameters typically controlled via MAC commands.

        :param rx1_offset: RX1 data rate offset
        :param rx2_datarate: RX2 data rate index
        :param rx2_frequency: RX2 frequency in Hz
        :param delay: RX1 delay in seconds
        """
        self.rx1_dr_offset = rx1_offset
        self.rx2_datarate = rx2_datarate
        self.rx2_frequency = rx2_frequency
        self.rx_delay_secs = delay
        logger.debug(
            f"[RadioPHY] RX Params updated: RX1 Offset={rx1_offset}, "
            f"RX2 DR={rx2_datarate}, RX2 Freq={rx2_frequency}, Delay={delay}s"
        )
        logger.info(f"                                    \033[95mUpdated rx1 dr offset to {self.rx1_dr_offset}.\033[0m")
        logger.info(f"                                    \033[95mUpdated rx2 dr to {self.rx2_datarate}.\033[0m")
        logger.info(f"                                    \033[95mUpdated rx2 frequency to {self.rx2_frequency}.\033[0m")
        logger.info(f"                                    \033[95mUpdated rx delay to {self.rx_delay_secs}.\033[0m")

    def get_symbol_duration(self, sf: int, bw_khz: int) -> float:
        """
        Calculate the duration of one LoRa symbol in seconds.
        """
        return (2 ** sf) / (bw_khz * 1000)

    def get_window_duration(self, sf: int, bw_khz: int, symbols: int = 8) -> float:
        """
        Calculate RX1 window duration based on symbol time.
        """
        symbol_time = self.get_symbol_duration(sf, bw_khz)
        return symbol_time * symbols

    def update_link_adr(self, data_rate_tx_power: int, nb_trans = None):
        """
        Apply data rate and TX power configuration from LinkADRReq.

        :param data_rate_tx_power: Encoded byte with DR (upper 4 bits) and TX power (lower 4 bits)
        """
        self.data_rate = data_rate_tx_power >> 4
        self.tx_power = data_rate_tx_power & 0x0F
        if nb_trans is not None:
            self.nb_trans = max(1, min(nb_trans, 15))
        logger.debug(f"[RadioPHY] DR updated to {self.data_rate}, TX power to {self.tx_power} dBm, NbTrans={self.nb_trans}")
        logger.info(f"                                    \033[95mUpdated DR to {self.data_rate}.\033[0m")
        logger.info(f"                                    \033[95mUpdated TX power to {self.tx_power} dBm.\033[0m")
        logger.info(f"                                    \033[95mUpdated NbTrans to {self.nb_trans}.\033[0m")

    def add_channel(self, index: int, freq: int, dr_min: int, dr_max: int):
        """
        Add or update a channel in the enabled channel list.

        :param index: Channel index
        :param freq: Frequency in Hz
        :param dr_min: Minimum data rate index
        :param dr_max: Maximum data rate index
        """
        duty_cycle = 0.10 if freq == 869525000 else 0.01
        self.enabled_channels[index] = {
            "freq": freq,
            "dr_min": dr_min,
            "dr_max": dr_max,
            "duty_cycle": duty_cycle,
        } 
        logger.info(f"                                    \033[95mAdded/Updated channel {index}.\033[0m")
        logger.debug(f"[RadioPHY] Channel {index} set to {freq}Hz, DR {dr_min}-{dr_max}, duty cycle={duty_cycle}")

    def apply_channel_mask(self, ch_mask: int):
        for i in range(16):
            enabled = (ch_mask >> i) & 0x01
            if enabled:
                if i not in self.enabled_channels:
                    logger.warning(f"[RadioPHY] ChMask tried to enable unknown channel {i}")
            else:
                if i in self.enabled_channels:
                    logger.debug(f"[RadioPHY] Disabling channel {i}")
                    self.enabled_channels.pop(i)
        logger.info(f"                                    \033[95mApplied channel mask {ch_mask:016b}.\033[0m")

    def rotate_channel(self):
        available_channels = list(self.enabled_channels.keys())
        if not available_channels:
            logger.warning("[RadioPHY] No enabled channels to rotate through.")
            return
        idx = available_channels.index(self.current_channel_index) if self.current_channel_index in available_channels else 0
        self.current_channel_index = available_channels[(idx + 1) % len(available_channels)]
        logger.debug(f"[RadioPHY] Hopped to channel index {self.current_channel_index}")
        
    def can_transmit(self, channel_index: int, airtime_s: float) -> tuple[bool, Optional[float]]:
        now = time.time()
        ready = now >= self.next_tx_time[channel_index]
        channel = self.enabled_channels.get(channel_index)
        if not channel:
            return False, None

        if not (channel["dr_min"] <= self.data_rate <= channel["dr_max"]):
            logger.debug(
                f"[RadioPHY] DR {self.data_rate} not supported on channel {channel_index} "
                f"(allowed range: DR{channel['dr_min']}–DR{channel['dr_max']})"
            )
            return False, None

        limit = channel.get("duty_cycle", 1.0)
        if ready:
            logger.debug(
                f"[RadioPHY] Channel {channel_index} ({channel['freq']} Hz) ready for TX"
            )
            return True, None
        else:
            wait_for = self.next_tx_time[channel_index] - now
            logger.debug(
                f"[RadioPHY] Duty cycle wait on channel {channel_index} ({channel['freq']} Hz): {wait_for:.2f}s remaining"
            )
            return ready, wait_for

    def record_transmission(self, channel_index: int, airtime_s: float):
        now = time.time()
        duty_cycle = self.enabled_channels[channel_index].get("duty_cycle", 1.0)
        off_time = airtime_s * (1.0 / duty_cycle - 1.0)
        self.next_tx_time[channel_index] = now + off_time
        logger.debug(f"[RadioPHY] TX on channel {channel_index} ({self.enabled_channels[channel_index]['freq']} Hz) — Airtime: {airtime_s:.2f}s, Next TX after: {off_time:.2f}s")
