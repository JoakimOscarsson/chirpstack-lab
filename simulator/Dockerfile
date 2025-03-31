FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all the simulator modules
COPY main.py .
COPY gateway.py .
COPY iot_device.py .
COPY mac_commands.py .
COPY utils.py .
COPY config.py .
COPY message_bus.py .
COPY channel_simulator.py .
COPY radio_phy.py .
COPY lorawan_protocol.py .
COPY lorawan_stack.py .

CMD ["python", "-u", "main.py"]
