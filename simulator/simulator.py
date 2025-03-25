import os
import socket
import time
import json
import base64
import random
import struct
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Hash import CMAC

# === ENV CONFIG ===
UDP_IP = os.getenv("UDP_IP", "chirpstack-gateway-bridge")
UDP_PORT = int(os.getenv("UDP_PORT", "1700"))
GATEWAY_EUI = os.getenv("GATEWAY_EUI", "0102030405060708")
DEVADDR = os.getenv("DEVADDR", "26011BDA")
NWK_SKEY = os.getenv("NWK_SKEY", "00000000000000000000000000000000")
APP_SKEY = os.getenv("APP_SKEY", "00000000000000000000000000000000")
SEND_INTERVAL = int(os.getenv("SEND_INTERVAL", "10"))

frame_counter = 0
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def create_udp_header(token):
    return b'\x02' + token.to_bytes(2, byteorder="big") + b'\x00' + bytes.fromhex(GATEWAY_EUI)

def encrypt_payload(payload, app_skey, devaddr, fcnt):
    # LoRaWAN payload encryption algorithm (Appendix A.3)
    cipher = AES.new(app_skey, AES.MODE_ECB)
    size = len(payload)
    enc = bytearray()
    i = 1
    while len(enc) < size:
        a_block = bytearray(16)
        a_block[0] = 0x01
        a_block[5] = 0x00
        a_block[6:10] = devaddr[::-1]
        a_block[10:12] = struct.pack('<H', fcnt)
        a_block[15] = i
        s_block = cipher.encrypt(bytes(a_block))
        for b in s_block:
            if len(enc) < size:
                enc.append(b)
        i += 1
    return bytes([p ^ s for p, s in zip(payload, enc)])

def calculate_mic(phy, nwk_skey, devaddr, fcnt):
    # LoRaWAN MIC calculation (Appendix A.1)
    b0 = bytearray(16)
    b0[0] = 0x49
    b0[5] = 0x00
    b0[6:10] = devaddr[::-1]
    b0[10:12] = struct.pack('<H', fcnt)
    b0[15] = len(phy)
    cmac = CMAC.new(nwk_skey, ciphermod=AES)
    cmac.update(b0 + phy)
    return cmac.digest()[:4]

def build_lorawan_payload():
    global frame_counter

    devaddr = bytes.fromhex(DEVADDR)
    nwk_skey = bytes.fromhex(NWK_SKEY)
    app_skey = bytes.fromhex(APP_SKEY)

    mhdr = b'\x40'  # UnconfirmedDataUp
    fctrl = b'\x00'
    fcnt = struct.pack('<H', frame_counter)
    fport = b'\x01'
    payload = b'Simulator says hello through ChripStack!'

    encrypted = encrypt_payload(payload, app_skey, devaddr, frame_counter)

    mac_payload = devaddr[::-1] + fctrl + fcnt + fport + encrypted
    mic = calculate_mic(mhdr + mac_payload, nwk_skey, devaddr, frame_counter)

    frame_counter += 1

    return base64.b64encode(mhdr + mac_payload + mic).decode()

def send_uplink():
    token = random.randint(0, 65535)
    header = create_udp_header(token)

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
        "data": build_lorawan_payload()
    }

    payload = {
        "rxpk": [rxpk]
    }

    message = header + json.dumps(payload).encode("utf-8")
    sock.sendto(message, (UDP_IP, UDP_PORT))

    print(f"[{datetime.now()}] Uplink sent with FCnt={frame_counter - 1}")

if __name__ == "__main__":
    print("🚀 Starting minimal LoRaWAN simulator")
    try:
        while True:
            print("Sent message")
            send_uplink()
            time.sleep(SEND_INTERVAL)
    except KeyboardInterrupt:
        print("🛑 Simulator stopped.")
