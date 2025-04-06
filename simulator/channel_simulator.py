import random
import time
import math
import logging

logger = logging.getLogger(__name__)

class ChannelSimulator:
    def __init__(self, snr_threshold=-20, distance=2000, environment="suburban"):
        """
        :param noise_floor: Base noise floor in dBm
        :param snr_threshold: Minimum SNR required for successful demodulation
        """
        self.snr_threshold = snr_threshold
        self.distance = distance
        self.environment = environment
    
    def _lookup_noise_floor(self, environment):
        """
        Estimate noise floor based on environment.
        """
        return {
            "urban": -110,
            "suburban": -120,
            "rural": -125
        }.get(environment.lower(), -120)

    def _calculate_rssi(self, tx_power, distance_m, spreading_factor, bandwidth_khz, environment):
        """
        Estimate RSSI based on distance, SF, BW, and environment.
        """
        # Reference path loss model (Log-distance with some fudge)
        # Path loss exponent n: 2.7 (urban), 2.0 (suburban), 1.6 (rural)
        path_loss_exponent = {
            "urban": 2.7,
            "suburban": 2.0,
            "rural": 1.6
        }.get(environment.lower(), 2.3)

        ref_distance = 1.0  # meters
        path_loss_ref = 40  # dB loss at 1 meter, roughly

        # Path loss (log-distance formula)
        distance = max(distance_m, ref_distance)
        path_loss_db = path_loss_ref + 10 * path_loss_exponent * math.log10(distance)

        # SF-based loss (higher SF = longer range = more conservative)
        sf_penalty = {
            7: 0,
            8: 1.5,
            9: 3.5,
            10: 6.0,
            11: 9.5,
            12: 13.0
        }.get(spreading_factor, 0)

        # Bandwidth penalty (narrow BW = worse performance)
        bw_loss = (125 - bandwidth_khz) * 0.05

        # Random fading
        fading = random.gauss(0, 1.5)

        rssi = tx_power - path_loss_db - sf_penalty - bw_loss + fading

        logger.debug(
            f"RSSI calc → Distance={distance_m}m, Env={environment}, "
            f"Path loss={path_loss_db:.1f}dB, SF penalty={sf_penalty:.1f}, BW loss={bw_loss:.1f}, "
            f"Fading={fading:.2f} → RSSI={rssi:.2f} dBm"
        )

        return int(rssi)

    def _calculate_snr(self, rssi, spreading_factor, bandwidth_khz, environment):
        """
        Estimate SNR from RSSI and environment-based noise floor.
        """
        noise_floor = self._lookup_noise_floor(environment)

        # Simulate base SNR depending on SF (more robust signal at high SF)
        base_snr_margin = {
            7: -7.0,
            8: -10.0,
            9: -13.0,
            10: -15.0,
            11: -17.0,
            12: -18.5
        }.get(spreading_factor, -10.0)

        # More variation for high SF (less reliable)
        jitter = random.uniform(-1.5, 3.0) if spreading_factor >= 11 else random.uniform(-1.0, 2.0)

        # Raw SNR calculation
        snr = rssi - noise_floor + base_snr_margin + jitter

        # SNR cap based on BW
        max_snr = 10 - (bandwidth_khz - 125) / 50
        snr = round(min(snr, max_snr), 1)
        
        logger.debug(
            f"SNR calc → RSSI={rssi}, Noise={noise_floor}, SF margin={base_snr_margin}, "
            f"Jitter={jitter:.2f} → SNR={snr:.1f} dB"
        )

        return snr

    def _parse_data_rate(self, datr_str):
        """
        Parse LoRa data rate string like "SF7BW125"
        """
        if not datr_str or not datr_str.startswith("SF"):
            return 7, 125  # default

        try:
            sf = int(datr_str[2: datr_str.index("BW")])
            bw = int(datr_str[datr_str.index("BW") + 2:])
            return sf, bw
        except Exception as e:
            logger.warning(f"Failed to parse data_rate '{datr_str}': {e}")
            return 7, 125

    def _should_drop(self, rssi, snr, coding_rate="4/5"):
        """
        Decide whether to drop based on signal quality.
        """
        noise_floor = self._lookup_noise_floor(self.environment)
        cr_bonus = {
            "4/5": 0.0,
            "4/6": 1.0,
            "4/7": 2.0,
            "4/8": 3.0
        }.get(coding_rate, 0.0)
        
        snr_threshold = self.snr_threshold - cr_bonus
        if snr < snr_threshold or rssi < noise_floor + 6:
            return True
        drop_margin = (snr - snr_threshold) / 10
        drop_chance = max(0.0, 0.3 - drop_margin * 0.15)
        
        logger.debug(
        f"Drop check → SNR={snr:.1f}, threshold={snr_threshold:.1f}, "
        f"RSSI={rssi}, noise={noise_floor}, chance={drop_chance:.2f}"
        )

        return random.random() < drop_chance

    async def simulate_uplink(self, envelope):
        chan = envelope.chan or 0
        sf, bw = self._parse_data_rate(envelope.data_rate)
        tx_power = envelope.tx_power or 14  # default
        rssi = self._calculate_rssi(tx_power, self.distance,  sf, bw, self.environment)
        snr = self._calculate_snr(rssi, sf, bw, self.environment)
        drop_flag = self._should_drop(rssi, snr, envelope.coding_rate)

        logger.debug(
        f"[ChannelSimulator] UPLINK sim → DevAddr={envelope.devaddr or '??'} | "
        f"TX={tx_power} dBm | SF={sf} | BW={bw}kHz | "
        f"RSSI={rssi} dBm | SNR={snr} dB | Drop={drop_flag}"
        )
        logger.debug(" ")


        envelope.rssi = rssi
        envelope.snr = snr
        envelope.timestamp = int(time.time() * 1e6) % (2**32)

        if drop_flag:
            logger.info(f"                \033[91mUplink dropped on channel {chan} (RSSI={rssi}, SNR={snr})\033[0m")
            return None

        return envelope

    async def simulate_downlink(self, envelope):
        sf, bw = self._parse_data_rate(envelope.data_rate)
        tx_power = envelope.tx_power or 14
        rssi = self._calculate_rssi(tx_power, self.distance,  sf, bw, self.environment)
        snr = self._calculate_snr(rssi, sf, bw, self.environment)
        drop_flag = self._should_drop(rssi, snr, envelope.coding_rate)

        # Note: Device doesn't "see" RSSI/SNR, but useful for sim stats/logging
        envelope.rssi = rssi
        envelope.snr = snr

        logger.debug(
        f"[ChannelSimulator] DOWNLINK sim → DevAddr={envelope.devaddr or '??'} | "
        f"TX={tx_power} dBm | SF={sf} | BW={bw}kHz | "
        f"RSSI={rssi} dBm | SNR={snr} dB | Drop={drop_flag}"
        )

        if drop_flag:
            logger.debug(f"                    \033[91mDownlink dropped. (RSSI={rssi}, SNR={snr})\033[0m")
            return None

        return envelope.payload

    


    # Future expansion: jitter, delay, SNR threshold, etc.
    # Things that could be made to influence signal:
    # Distance
    # Height/Elevation
    # Line of Sight
    # Antenna orientation
    # Antenna gain
    # Device orientation
    # Multipath fading
    # Fresnel zone clearance

    # Weather
    # Temperature gradients
    # Vegetation
    # Urban density
    # Building material

    
    # Coding rate
    # Data rate index
    # Frequency
    # Channel number

    # Simultaneous transmissions
    # Duty cycle limits
    # Gateway load
    # Airtime

    # Noise floor
    # Random drops
    # Clock drift / Timing mismatch
    # Jitter or latency
    # SNR-based probabalistic drop