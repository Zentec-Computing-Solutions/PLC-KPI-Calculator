from __future__ import annotations

import subprocess
import time
from threading import Lock, Thread

import cv2
import numpy as np
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ConnectionException


PLC_IP = "192.168.88.5"
PLC_PORT = 502
SHIFT_REGISTER = 15
SHIFT_REGISTER_COUNT = 6

RTSP_URL = "rtsp://127.0.0.1:8554/shift-count"

FRAME_WIDTH = 854
FRAME_HEIGHT = 480
FRAME_RATE = 2

CONNECT_TIMEOUT_SECONDS = 2
READ_RETRIES = 3
RETRY_DELAY_SECONDS = 0.5


state_lock = Lock()
shared_state = {
    "current_shift": 0,
    "previous_shifts": [0, 0, 0, 0],
    "online": False,
    "status": "Connecting...",
    "last_update": 0.0,
}


def read_shift_registers_once() -> tuple[int, list[int]]:
    client = ModbusTcpClient(
        PLC_IP,
        port=PLC_PORT,
        timeout=CONNECT_TIMEOUT_SECONDS,
        retries=0,
    )

    try:
        if not client.connect():
            raise ConnectionException(f"Cannot connect to {PLC_IP}:{PLC_PORT}")

        result = client.read_holding_registers(
            address=SHIFT_REGISTER,
            count=SHIFT_REGISTER_COUNT,
        )

        if result.isError() or not getattr(result, "registers", None):
            raise ConnectionException(
                f"Failed to read holding registers {SHIFT_REGISTER}-{SHIFT_REGISTER + SHIFT_REGISTER_COUNT - 1}"
            )

        registers = [int(value) for value in result.registers]
        return registers[0], registers[1:5]

    finally:
        client.close()


def read_shift_registers_with_retries() -> tuple[int, list[int]]:
    last_error: Exception | None = None

    for attempt in range(1, READ_RETRIES + 1):
        try:
            return read_shift_registers_once()
        except Exception as exc:
            last_error = exc
            if attempt < READ_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS)

    if last_error is not None:
        raise last_error

    raise ConnectionException("Unknown PLC read failure")


def update_counter() -> None:
    while True:
        try:
            current_shift, previous_shifts = read_shift_registers_with_retries()

            with state_lock:
                shared_state["current_shift"] = current_shift
                shared_state["previous_shifts"] = previous_shifts
                shared_state["online"] = True
                shared_state["status"] = "Connected"
                shared_state["last_update"] = time.time()

        except Exception as exc:
            with state_lock:
                shared_state["online"] = False
                shared_state["status"] = f"Reconnecting... ({type(exc).__name__})"

        time.sleep(1.0 / FRAME_RATE)


def generate_frame() -> np.ndarray:
    with state_lock:
        current_shift = shared_state["current_shift"]
        previous_shifts = list(shared_state["previous_shifts"])
        online = shared_state["online"]
        status = shared_state["status"]

    frame = np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)

    bg_color = (0, 95, 0) if online else (28, 20, 50)
    frame[:, :] = bg_color

    cv2.rectangle(frame, (18, 18), (FRAME_WIDTH - 18, FRAME_HEIGHT - 18), (255, 255, 255), 2)

    left_panel_x = 42
    right_panel_x = FRAME_WIDTH // 2 + 30

    cv2.putText(
        frame,
        "CURRENT SHIFT",
        (left_panel_x, 82),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.3,
        (255, 255, 255),
        3,
    )

    cv2.putText(
        frame,
        str(current_shift),
        (left_panel_x, 295),
        cv2.FONT_HERSHEY_SIMPLEX,
        5.6,
        (0, 255, 100) if online else (100, 100, 255),
        10,
    )

    cv2.putText(
        frame,
        "PREVIOUS SHIFTS",
        (right_panel_x, 82),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.3,
        (255, 255, 255),
        3,
    )

    row_start_y = 145
    row_gap = 72

    for index, shift_value in enumerate(previous_shifts):
        y = row_start_y + index * row_gap

        cv2.putText(
            frame,
            f"-{index + 1}",
            (right_panel_x, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (180, 220, 255),
            2,
        )

        cv2.putText(
            frame,
            str(shift_value),
            (right_panel_x + 90, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.6,
            (255, 255, 255),
            3,
        )

    status_color = (100, 255, 100) if online else (100, 150, 255)

    cv2.putText(
        frame,
        status,
        (42, FRAME_HEIGHT - 32),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.95,
        status_color,
        2,
    )

    return frame


def start_ffmpeg_process() -> subprocess.Popen:
    command = [
        r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe",

        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{FRAME_WIDTH}x{FRAME_HEIGHT}",
        "-r", str(FRAME_RATE),
        "-i", "-",

        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-crf", "30",

        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        RTSP_URL,
    ]

    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def stream_to_rtsp() -> None:
    while True:
        print(f"Starting RTSP stream to {RTSP_URL}")

        process = start_ffmpeg_process()

        try:
            while process.stdin:
                frame = generate_frame()
                process.stdin.write(frame.tobytes())
                process.stdin.flush()
                time.sleep(1.0 / FRAME_RATE)

        except BrokenPipeError:
            print("FFmpeg pipe broke. Restarting...")

        except Exception as exc:
            print(f"RTSP stream error: {exc}")

        finally:
            if process.stdin:
                process.stdin.close()

            process.terminate()
            process.wait(timeout=5)

        time.sleep(2)


if __name__ == "__main__":
    update_thread = Thread(target=update_counter, daemon=True)
    update_thread.start()

    stream_to_rtsp()