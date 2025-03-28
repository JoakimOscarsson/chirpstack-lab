FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all the simulator modules
COPY main.py .
COPY gateway.py .
#COPY device.py .
COPY iot_device.py .
COPY lorawan_module.py .
COPY device_manager.py .
COPY mac_commands.py .
COPY utils.py .
COPY config.py .

CMD ["python", "-u", "main.py"]
