import asyncio
import json
import random
import time
import logging
import base64
from datetime import datetime
from utils import RadioEnvelope


class GatewayProtocol(asyncio.DatagramProtocol):
    """
    Minimal protocol for sending UDP datagrams.
    """
    def __init__(self, logger, remote_ip, remote_port, downlink_handler, gateway):
        super().__init__()
        self.logger = logger
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.downlink_handler = downlink_handler
        self.gateway = gateway  # reference to Gateway instance
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
        if len(data) < 4:
            self.logger.warning("Received malformed UDP packet.")
            return
        self.logger.debug(f"Received downlink with proto_id: {data[3]}.")

        proto_id = data[3]
        if proto_id == 0x03:  # PULL_RESP
            try:
                payload_json = json.loads(data[4:].decode())
                txpk = payload_json.get("txpk", {})
                b64_payload = txpk.get("data")
                if b64_payload:
                    raw_payload = base64.b64decode(b64_payload)

                    envelope = RadioEnvelope(
                        payload=raw_payload,
                        freq=txpk.get("freq"),
                        data_rate=txpk.get("datr"),
                        tx_power=txpk.get("powe"),
                        timestamp=txpk.get("tmst"),
                    )
                    self.logger.debug("Received downlink from server, dispatching to handler...")
                    asyncio.create_task(self._handle_scheduled_downlink(envelope))
                else:
                    self.logger.warning("PULL_RESP missing 'data' field.")
            except Exception as e:
                self.logger.error(f"Failed to handle PULL_RESP: {e}")

    def get_concentrator_tmst(self):
        return self.gateway.get_concentrator_tmst()
    
    async def _handle_scheduled_downlink(self, envelope: RadioEnvelope):
        now_tmst = self.get_concentrator_tmst()
        wait_us = (envelope.timestamp - now_tmst) % (2**32)
        wait_s = wait_us / 1_000_000
        self.logger.debug(f""
                         f"Received downlink at tmst={envelope.timestamp}, "
                         f"current tmst={now_tmst}, wait_s={wait_s:.3f}"
                         f""
                         )
        self.logger.info(f"                              \033[96mGateway received and scheduled downlink data\033[0m")
        if wait_s > 0:
            self.logger.debug(f"[Gateway] Sleeping {wait_s:.3f}s to match downlink tmst={envelope.timestamp}")
            await asyncio.sleep(wait_s)
        await self.downlink_handler(envelope)

    def error_received(self, exc):
        self.logger.error(f"UDP error received: {exc}")

    def connection_lost(self, exc):
        self.logger.warning("GatewayProtocol connection lost")


class Gateway:
    """
    Simulates the LoRa UDP Packet Forwarder side with fully async UDP.
    """    
    def __init__(self, eui, udp_ip, udp_port, downlink_handler):
        self.logger = logging.getLogger(__name__)
        self.eui = eui
        self.udp_ip = udp_ip
        self.udp_port = udp_port
        self.transport = None
        self.protocol = None
        self.downlink_handler = downlink_handler
        self.concentrator_start_time = time.monotonic()

    def get_concentrator_tmst(self):
        elapsed = time.monotonic() - self.concentrator_start_time
        return int(elapsed * 1_000_000) % (2**32)

    async def setup_async(self):
        """
        Initialize the async UDP transport & protocol via create_datagram_endpoint.
        """
        loop = asyncio.get_running_loop()
        protocol_factory = lambda: GatewayProtocol(
            self.logger,
            self.udp_ip,
            self.udp_port,
            self.downlink_handler,
            self
        )

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


    async def send_uplink_async(self, envelope):
        """
        Build the LoRa packet-forwarder JSON and send it via self.protocol.send(...).
        """
        token = random.randint(0, 65535)
        header = self._create_udp_header(token, push=True)


        rxpk = {
            "tmst": self.get_concentrator_tmst(),  # TODO: Remove timestamp from envelope
            "time": envelope.utc_time,  # datetime.utcnow().isoformat() + "Z",
            "chan": envelope.chan,
            "rfch": 0,
            "freq": envelope.freq,  # 868.1,
            "stat": 1,
            "modu": "LORA",
            "datr": envelope.data_rate,  # "SF7BW125",
            "codr": envelope.coding_rate,  # "4/5",
            "rssi": envelope.rssi,  # -42,
            "lsnr": envelope.snr,  # 5.5,
            "size": envelope.size,  # 32,
            "data": base64.b64encode(envelope.payload).decode()
        }

        payload = {"rxpk": [rxpk]}
        message = header + json.dumps(payload).encode("utf-8")

        # Send via the protocol
        if self.protocol is None:
            self.logger.warning("Gateway protocol not set up; cannot send uplink.")
            return

        self.protocol.send(message)
        self.logger.debug(f"Gateway EUI={self.eui} sent uplink with token={token}.")

    async def pull_data_loop(self):
        while True:
            token = random.randint(0, 65535)
            header = self._create_udp_header(token, push=False)
            self.protocol.send(header)
            self.logger.debug("Sent PULL_DATA to gateway bridge.")
            await asyncio.sleep(5)

    async def close_async(self):
        """
        Close the UDP transport if it's open.
        """
        self.logger.info("Closing gateway UDP transport...")
        if self.transport is not None:
            self.transport.close()
            await asyncio.sleep(0.1)
        self.logger.info("Gateway transport closed.")


    def _create_udp_header(self, token, push):
        # 0x02 = PULL_DATA identifier (for push from gateway to server)
        # 0x00 = This means push uplink (as in the older Semtech protocol doc).
        proto_byte = b'\x00' if push else b'\x02'
        return b'\x02' + token.to_bytes(2, byteorder="big") + proto_byte + bytes.fromhex(self.eui)
