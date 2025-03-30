import logging
from utils import dr_to_sf_bw

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
            0: {"freq": 868100000, "dr_min": 0, "dr_max": 5},
            1: {"freq": 868300000, "dr_min": 0, "dr_max": 5},
            2: {"freq": 868500000, "dr_min": 0, "dr_max": 5},
        }
        self.current_channel_index = 0
        self.last_uplink_freq = 868100000

        # Transmission settings
        self.tx_power = 14  # dBm
        self.max_eirp = 16  # Region-defined cap
        self.dwell_time_enabled = False

        # Modulation settings
        self.data_rate = 0  # LoRa DR index (e.g., 0 = SF12BW125)
        self.coding_rate = "4/5"

        # MAC command-configurable parameters
        self.rx1_dr_offset = 0
        self.rx2_datarate = 0
        self.rx2_frequency = 869525000
        self.rx_delay_secs = 1

    def get_spreading_factor(self):
        """Return the spreading factor based on the current data rate."""
        sf, _ = dr_to_sf_bw(self.data_rate)
        return sf

    def get_bandwidth(self):
        """Return the bandwidth in kHz based on the current data rate."""
        _, bw = dr_to_sf_bw(self.data_rate)
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

    def update_link_adr(self, data_rate_tx_power: int):
        """
        Apply data rate and TX power configuration from LinkADRReq.

        :param data_rate_tx_power: Encoded byte with DR (upper 4 bits) and TX power (lower 4 bits)
        """
        self.data_rate = data_rate_tx_power >> 4
        self.tx_power = data_rate_tx_power & 0x0F
        logger.debug(f"[RadioPHY] DR updated to {self.data_rate}, TX power to {self.tx_power} dBm")

    def add_channel(self, index: int, freq: int, dr_min: int, dr_max: int):
        """
        Add or update a channel in the enabled channel list.

        :param index: Channel index
        :param freq: Frequency in Hz
        :param dr_min: Minimum data rate index
        :param dr_max: Maximum data rate index
        """
        self.enabled_channels[index] = {
            "freq": freq,
            "dr_min": dr_min,
            "dr_max": dr_max
        }
        logger.debug(f"[RadioPHY] Channel {index} set to {freq}Hz, DR {dr_min}-{dr_max}")
