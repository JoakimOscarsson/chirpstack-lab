import socket
import json
import random
import time
import logging
import asyncio
from datetime import datetime

class Gateway:
    """
    Simulates the LoRa UDP Packet Forwarder side:
      - Sends uplinks (rxpk) via UDP to the network server (ChirpStack)
      - Could be extended later to listen for downlinks (txpk) as well
    """
    def __init__(self, eui, udp_ip, udp_port):
        self.logger = logging.getLogger(__name__)
        self.eui = eui
        self.udp_ip = udp_ip
        self.udp_port = udp_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _create_udp_header(self, token):
        # 0x02 = PULL_DATA identifier (for push from gateway to server)
        # 0x00 = This means push uplink (as in the older Semtech protocol doc).
        return b'\x02' + token.to_bytes(2, byteorder="big") + b'\x00' + bytes.fromhex(self.eui)

    def send_uplink_blocking(self, base64_payload):
        """
        Blocking method: builds the message and sends it via UDP. 
        """
        token = random.randint(0, 65535)
        header = self._create_udp_header(token)

        rxpk = {
            "tmst": int(time.time() * 1e6) % (2**32),
            "time": datetime.utcnow().isoformat() + "Z",
            "chan": 0,
            "rfch": 0,
            "freq": 868.1,
            "stat": 1,
            "modu": "LORA",
            "datr": "SF7BW125",
            "codr": "4/5",
            "rssi": -42,
            "lsnr": 5.5,
            "size": 32,
            "data": base64_payload
        }

        payload = {"rxpk": [rxpk]}
        message = header + json.dumps(payload).encode("utf-8")
        self.sock.sendto(message, (self.udp_ip, self.udp_port))

        self.logger.info(f"Gateway EUI={self.eui} sent uplink with token={token}.")


    async def send_uplink_async(self, base64_payload):
        """
        Async wrapper that offloads the blocking 'send_uplink_blocking' call 
        to a ThreadPoolExecutor, so it doesn't block the event loop.
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,  # default executor
            self.send_uplink_blocking, 
            base64_payload
        )
