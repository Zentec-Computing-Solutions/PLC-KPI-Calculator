from __future__ import annotations

import argparse
import logging
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from threading import Event, Lock, Thread

import cv2
import numpy as np
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ConnectionException


LOGGER = logging.getLogger("shift-monitor")


def env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    plc_ip: str
    plc_port: int
    shift_register: int
    shift_register_count: int
    rtsp_url: str
    frame_width: int
    frame_height: int
    frame_rate: float
    keyframe_interval: float
    poll_interval: float
    connect_timeout: float
    reconnect_delay: float
    ffmpeg_path: str
    mock_plc: bool
    mock_cycle_seconds: float
    mock_shift_length: int

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            plc_ip=os.getenv("PLC_IP", "192.168.88.5"),
            plc_port=env_int("PLC_PORT", 502),
            shift_register=env_int("SHIFT_REGISTER", 15),
            shift_register_count=env_int("SHIFT_REGISTER_COUNT", 5),
            rtsp_url=os.getenv("RTSP_URL", "rtsp://127.0.0.1:8554/shift-count"),
            frame_width=env_int("FRAME_WIDTH", 854),
            frame_height=env_int("FRAME_HEIGHT", 480),
            frame_rate=env_float("FRAME_RATE", 2.0),
            keyframe_interval=env_float("KEYFRAME_INTERVAL", 2.0),
            poll_interval=env_float("PLC_POLL_INTERVAL", 0.5),
            connect_timeout=env_float("PLC_CONNECT_TIMEOUT", 2.0),
            reconnect_delay=env_float("PLC_RECONNECT_DELAY", 2.0),
            ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg"),
            mock_plc=env_bool("MOCK_PLC"),
            mock_cycle_seconds=env_float("MOCK_CYCLE_SECONDS", 2.0),
            mock_shift_length=env_int("MOCK_SHIFT_LENGTH", 100),
        )

    def validate(self) -> None:
        if self.shift_register_count < 5:
            raise ValueError("SHIFT_REGISTER_COUNT must be at least 5")
        if self.frame_width <= 0 or self.frame_height <= 0:
            raise ValueError("Frame dimensions must be positive")
        if self.frame_rate <= 0 or self.keyframe_interval <= 0 or self.poll_interval <= 0:
            raise ValueError(
                "FRAME_RATE, KEYFRAME_INTERVAL, and PLC_POLL_INTERVAL must be positive"
            )
        if self.mock_cycle_seconds <= 0 or self.mock_shift_length <= 0:
            raise ValueError("Mock PLC timing and shift length must be positive")


class SharedState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._current_shift = 0
        self._previous_shifts = [0, 0, 0, 0]
        self._online = False
        self._status = "Connecting..."

    def update(self, current_shift: int, previous_shifts: list[int]) -> None:
        with self._lock:
            self._current_shift = current_shift
            self._previous_shifts = previous_shifts[:4]
            self._online = True
            self._status = "Connected"

    def set_offline(self, status: str) -> None:
        with self._lock:
            self._online = False
            self._status = status

    def snapshot(self) -> tuple[int, list[int], bool, str]:
        with self._lock:
            return (
                self._current_shift,
                list(self._previous_shifts),
                self._online,
                self._status,
            )


def read_shift_registers(client: ModbusTcpClient, settings: Settings) -> tuple[int, list[int]]:
    result = client.read_holding_registers(
        address=settings.shift_register,
        count=settings.shift_register_count,
    )
    if result.isError() or not getattr(result, "registers", None):
        end_register = settings.shift_register + settings.shift_register_count - 1
        raise ConnectionException(
            f"Failed to read holding registers {settings.shift_register}-{end_register}"
        )

    registers = [int(value) for value in result.registers]
    if len(registers) < 5:
        raise ConnectionException(f"PLC returned {len(registers)} registers; expected at least 5")
    return registers[0], registers[1:5]


def update_from_plc(settings: Settings, state: SharedState, stop_event: Event) -> None:
    was_online = False

    while not stop_event.is_set():
        client = ModbusTcpClient(
            settings.plc_ip,
            port=settings.plc_port,
            timeout=settings.connect_timeout,
            retries=0,
        )
        try:
            if not client.connect():
                raise ConnectionException(f"Cannot connect to {settings.plc_ip}:{settings.plc_port}")

            LOGGER.info("Connected to PLC at %s:%s", settings.plc_ip, settings.plc_port)
            while not stop_event.is_set():
                current_shift, previous_shifts = read_shift_registers(client, settings)
                state.update(current_shift, previous_shifts)
                was_online = True
                stop_event.wait(settings.poll_interval)

        except Exception as exc:
            if was_online:
                LOGGER.warning("PLC connection lost: %s", exc)
            else:
                LOGGER.warning("PLC unavailable: %s", exc)
            was_online = False
            state.set_offline(f"Reconnecting... ({type(exc).__name__})")
        finally:
            client.close()

        stop_event.wait(settings.reconnect_delay)


def update_from_mock(settings: Settings, state: SharedState, stop_event: Event) -> None:
    LOGGER.warning("Using mock PLC data; no real PLC connection will be attempted")
    started = time.monotonic()

    while not stop_event.is_set():
        total_cycles = int((time.monotonic() - started) / settings.mock_cycle_seconds)
        current_shift = total_cycles % settings.mock_shift_length
        completed_shifts = total_cycles // settings.mock_shift_length
        previous = [
            max(settings.mock_shift_length - index - (completed_shifts % 4), 0)
            for index in range(4)
        ]
        state.update(current_shift, previous)
        stop_event.wait(settings.poll_interval)


def generate_frame(settings: Settings, state: SharedState) -> np.ndarray:
    current_shift, previous_shifts, online, status = state.snapshot()
    frame = np.zeros((settings.frame_height, settings.frame_width, 3), dtype=np.uint8)
    frame[:, :] = (0, 95, 0) if online else (28, 20, 50)

    scale_x = settings.frame_width / 854
    scale_y = settings.frame_height / 480
    scale = min(scale_x, scale_y)

    def point(x: int, y: int) -> tuple[int, int]:
        return int(x * scale_x), int(y * scale_y)

    cv2.rectangle(
        frame,
        point(18, 18),
        point(854 - 18, 480 - 18),
        (255, 255, 255),
        max(1, int(2 * scale)),
    )
    cv2.putText(frame, "CURRENT SHIFT", point(42, 82), cv2.FONT_HERSHEY_SIMPLEX,
                1.3 * scale, (255, 255, 255), max(1, int(3 * scale)))
    cv2.putText(frame, str(current_shift), point(42, 295), cv2.FONT_HERSHEY_SIMPLEX,
                5.6 * scale, (0, 255, 100) if online else (100, 100, 255),
                max(1, int(10 * scale)))
    cv2.putText(frame, "PREVIOUS SHIFTS", point(457, 82), cv2.FONT_HERSHEY_SIMPLEX,
                1.3 * scale, (255, 255, 255), max(1, int(3 * scale)))

    for index, shift_value in enumerate(previous_shifts):
        y = 145 + index * 72
        cv2.putText(frame, f"-{index + 1}", point(457, y), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0 * scale, (180, 220, 255), max(1, int(2 * scale)))
        cv2.putText(frame, str(shift_value), point(547, y), cv2.FONT_HERSHEY_SIMPLEX,
                    1.6 * scale, (255, 255, 255), max(1, int(3 * scale)))

    status_color = (100, 255, 100) if online else (100, 150, 255)
    cv2.putText(frame, status, point(42, 448), cv2.FONT_HERSHEY_SIMPLEX,
                0.95 * scale, status_color, max(1, int(2 * scale)))
    return frame


def resolve_ffmpeg(configured_path: str) -> str:
    resolved = shutil.which(configured_path)
    if resolved:
        return resolved
    if os.path.isfile(configured_path):
        return configured_path
    raise FileNotFoundError(
        f"FFmpeg was not found at '{configured_path}'. Install it or set FFMPEG_PATH."
    )


def start_ffmpeg(settings: Settings, ffmpeg_path: str) -> subprocess.Popen[bytes]:
    keyframe_frames = max(1, round(settings.frame_rate * settings.keyframe_interval))
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel", "warning",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{settings.frame_width}x{settings.frame_height}",
        "-r", str(settings.frame_rate),
        "-i", "-",
        "-an",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-g", str(keyframe_frames),
        "-keyint_min", str(keyframe_frames),
        "-sc_threshold", "0",
        "-bf", "0",
        "-pix_fmt", "yuv420p",
        "-crf", "30",
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        settings.rtsp_url,
    ]
    return subprocess.Popen(command, stdin=subprocess.PIPE)


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.stdin:
        try:
            process.stdin.close()
        except BrokenPipeError:
            pass
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def stream_to_rtsp(settings: Settings, state: SharedState, stop_event: Event) -> None:
    ffmpeg_path = resolve_ffmpeg(settings.ffmpeg_path)
    frame_interval = 1.0 / settings.frame_rate

    while not stop_event.is_set():
        LOGGER.info("Starting RTSP publisher to %s", settings.rtsp_url)
        process = start_ffmpeg(settings, ffmpeg_path)
        try:
            next_frame = time.monotonic()
            while not stop_event.is_set():
                if process.poll() is not None:
                    raise RuntimeError(f"FFmpeg exited with status {process.returncode}")
                if process.stdin is None:
                    raise RuntimeError("FFmpeg stdin is unavailable")

                process.stdin.write(generate_frame(settings, state).tobytes())
                process.stdin.flush()
                next_frame += frame_interval
                stop_event.wait(max(0.0, next_frame - time.monotonic()))
        except (BrokenPipeError, RuntimeError) as exc:
            if not stop_event.is_set():
                LOGGER.error("RTSP publisher stopped: %s", exc)
        finally:
            stop_process(process)

        stop_event.wait(settings.reconnect_delay)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish PLC shift counts as an RTSP video stream")
    parser.add_argument("--mock-plc", action="store_true", help="generate sample counts without a PLC")
    parser.add_argument("--check", action="store_true", help="validate configuration and dependencies, then exit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.mock_plc:
        os.environ["MOCK_PLC"] = "true"

    settings = Settings.from_environment()
    settings.validate()
    ffmpeg_path = resolve_ffmpeg(settings.ffmpeg_path)
    LOGGER.info("Using FFmpeg at %s", ffmpeg_path)
    if args.check:
        LOGGER.info("Configuration check passed")
        return 0

    state = SharedState()
    stop_event = Event()

    def request_stop(signum: int, _frame: object) -> None:
        LOGGER.info("Received signal %s; stopping", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    updater = update_from_mock if settings.mock_plc else update_from_plc
    update_thread = Thread(target=updater, args=(settings, state, stop_event), daemon=True)
    update_thread.start()

    try:
        stream_to_rtsp(settings, state, stop_event)
    finally:
        stop_event.set()
        update_thread.join(timeout=settings.connect_timeout + 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
