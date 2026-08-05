from datetime import datetime
import time

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ConnectionException


PLC_IP = "192.168.88.5"
PLC_PORT = 502
COUNTER_REGISTER = 15
POLL_TIME = 5.0
RETRY_TIME = 10.0


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_counter(client):
    result = client.read_holding_registers(address=COUNTER_REGISTER, count=1)
    if result.isError() or not getattr(result, "registers", None):
        raise ConnectionException(f"Failed to read holding register {COUNTER_REGISTER}")
    return int(result.registers[0])


def main():
    client = ModbusTcpClient(PLC_IP, port=PLC_PORT)
    last_value = None

    print(f"[{now_str()}] Monitoring %MW15 at {PLC_IP}:{PLC_PORT}")

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
            print(f"\n[{now_str()}] Stopped by user")
            break

        except Exception as e:
            print(f"[{now_str()}] Read/connect error: {e}")
            try:
                client.close()
            except Exception:
                pass
            time.sleep(RETRY_TIME)


if __name__ == "__main__":
    main()
