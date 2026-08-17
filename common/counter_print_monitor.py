"""Small PLC connectivity diagnostic; the RTSP publisher does not require it."""

import os
import time
from datetime import datetime

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ConnectionException


PLC_IP = os.getenv("PLC_IP", "192.168.88.5")
PLC_PORT = int(os.getenv("PLC_PORT", "502"))
COUNTER_REGISTER = int(os.getenv("SHIFT_REGISTER", "15"))
POLL_TIME = float(os.getenv("PLC_POLL_INTERVAL", "5"))
RETRY_TIME = float(os.getenv("PLC_RECONNECT_DELAY", "10"))


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_counter(client: ModbusTcpClient) -> int:
    result = client.read_holding_registers(address=COUNTER_REGISTER, count=1)
    if result.isError() or not getattr(result, "registers", None):
        raise ConnectionException(f"Failed to read holding register {COUNTER_REGISTER}")
    return int(result.registers[0])


def main() -> None:
    client = ModbusTcpClient(PLC_IP, port=PLC_PORT)
    last_value = None
    print(f"[{now_str()}] Monitoring register {COUNTER_REGISTER} at {PLC_IP}:{PLC_PORT}")

    while True:
        try:
            if not client.connected and not client.connect():
                raise ConnectionException(f"Cannot connect to {PLC_IP}:{PLC_PORT}")
            current_value = read_counter(client)
            if last_value is None:
                print(f"[{now_str()}] Initial value: {current_value}")
            elif current_value != last_value:
                print(f"[{now_str()}] Value changed: {last_value} -> {current_value}")
            last_value = current_value
            time.sleep(POLL_TIME)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f"[{now_str()}] Read/connect error: {exc}")
            client.close()
            time.sleep(RETRY_TIME)
    client.close()


if __name__ == "__main__":
    main()
