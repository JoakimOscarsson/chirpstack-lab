import os
import json
import base64
import paho.mqtt.client as mqtt

# === ENV config ===
MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
TOPIC = "application/+/device/+/event/up"

def on_subscribe(client, userdata, mid, reason_code_list, properties):
    if reason_code_list[0].is_failure:
        print(f"Broker rejected you subscription: {reason_code_list[0]}")
    else:
        print(f"Broker granted the following QoS: {reason_code_list[0].value}")

def on_unsubscribe(client, userdata, mid, reason_code_list, properties):
    if len(reason_code_list) == 0 or not reason_code_list[0].is_failure:
        print("unsubscribe succeeded (if SUBACK is received in MQTTv3 it success)")
    else:
        print(f"Broker replied with failure: {reason_code_list[0]}")
    client.disconnect()

def decode_base64_data(encoded_str):
    try:
        decoded_bytes = base64.b64decode(encoded_str)
        return decoded_bytes.decode('utf-8')
    except Exception as e:
        return f"[Error decoding data: {e}]"

def on_message(client, userdata, message):
    print(f"\n📬 Topic: {message.topic}")
    try:
        payload_dict = json.loads(message.payload.decode())
        #print("📦 Raw Payload JSON:", json.dumps(payload_dict, indent=2))

        if "data" in payload_dict:
            decoded_data = decode_base64_data(payload_dict["data"])
            print(f"🔍 Decoded `data`: {decoded_data}", flush=True)
        else:
            print("⚠️ No `data` field in payload.")
    except Exception as e:
        print(f"❌ Failed to parse message: {e}")
    
    userdata.append(message.payload)

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"Failed to connect: {reason_code}. loop_forever() will retry connection")
    else:
        client.subscribe(TOPIC)

mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqttc.on_connect = on_connect
mqttc.on_message = on_message
mqttc.on_subscribe = on_subscribe
mqttc.on_unsubscribe = on_unsubscribe

mqttc.user_data_set([])
mqttc.connect(MQTT_HOST, MQTT_PORT)
mqttc.loop_forever()
