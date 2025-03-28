import random
import logging

logger = logging.getLogger(__name__)

class ChannelSimulator:
    def __init__(self, drop_rate=0.0):
        """
        :param drop_rate: Chance to drop a packet [0.0, 1.0]
        """
        self.drop_rate = drop_rate

    async def simulate_link(self, raw: bytes) -> bytes | None:
        """
        Simulate the downlink or uplink path.
        - May drop packets based on drop_rate
        - Future: apply noise, delay, SNR, etc.
        """
        logger.debug("in simulate_link")
        if random.random() < self.drop_rate:
            logger.info("[ChannelSimulator] Packet dropped.")
            return None
        return raw