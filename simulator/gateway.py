import asyncio
import json
import random
import time
import logging
from datetime import datetime


class GatewayProtocol(asyncio.DatagramProtocol):
    """
    Minimal protocol for sending (and potentially receiving) UDP datagrams.
    """
    def __init__(self, logger, remote_ip, remote_port):
        super().__init__()
        self.logger = logger
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.transport = None

    def connection_made(self, transport):
        """
        Called when the UDP socket is created and connected.
        For a client, 'remote_addr' might be None if not connected by default.
        """
        self.transport = transport
        self.logger.info("GatewayProtocol connection established.")

    def send(self, data: bytes):
        """
        Send raw bytes to the configured remote IP/port.
        """
        if self.transport is None:
            self.logger.warning("Transport not ready; cannot send data.")
            return
        self.transport.sendto(data, (self.remote_ip, self.remote_port))

    def datagram_received(self, data, addr):
        """
        If you want to handle inbound messages (downlinks), parse them here.
        """
        self.logger.info(f"Received data from {addr}: {data}")  # TODO: change to debug or implement passing to device

    def error_received(self, exc):
        self.logger.error(f"UDP error received: {exc}")

    def connection_lost(self, exc):
        self.logger.warning("GatewayProtocol connection lost")


class Gateway:
    """
    Simulates the LoRa UDP Packet Forwarder side with fully async UDP.
    """    
    def __init__(self, eui, udp_ip, udp_port):
        self.logger = logging.getLogger(__name__)
        self.eui = eui
        self.udp_ip = udp_ip
        self.udp_port = udp_port

        self.transport = None
        self.protocol = None


    async def setup_async(self):
        """
        Initialize the async UDP transport & protocol via create_datagram_endpoint.
        """
        loop = asyncio.get_running_loop()
        # Create our custom protocol instance
        protocol_factory = lambda: GatewayProtocol(self.logger, self.udp_ip, self.udp_port)

        # local_addr: we can bind to 0.0.0.0, ephemeral port if we just want to send
        # remote_addr: can be omitted or used for a "connected" UDP socket
        # We'll do "unconnected" style and specify remote on each send
        transport, protocol = await loop.create_datagram_endpoint(
            protocol_factory,
            local_addr=('0.0.0.0', 0) 
        )

        self.transport = transport
        self.protocol = protocol
        self.logger.info(f"Gateway EUI={self.eui} async transport setup complete.")


    async def send_uplink_async(self, base64_payload):
        """
        Build the LoRa packet-forwarder JSON and send it via self.protocol.send(...).
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

        # Send via the protocol
        if self.protocol is None:
            self.logger.warning("Gateway protocol not set up; cannot send uplink.")
            return

        self.protocol.send(message)
        self.logger.info(f"Gateway EUI={self.eui} sent uplink with token={token}.")



    async def close_async(self):
        """
        Close the UDP transport if it's open.
        """
        self.logger.info("Closing gateway UDP transport...")
        if self.transport is not None:
            self.transport.close()
            await asyncio.sleep(0.1)
        self.logger.info("Gateway transport closed.")


    def _create_udp_header(self, token):
        # 0x02 = PULL_DATA identifier (for push from gateway to server)
        # 0x00 = This means push uplink (as in the older Semtech protocol doc).
        return b'\x02' + token.to_bytes(2, byteorder="big") + b'\x00' + bytes.fromhex(self.eui)
