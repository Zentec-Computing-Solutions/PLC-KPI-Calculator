from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ConnectionException

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None


PLC_IP = "192.168.88.5"
PLC_PORT = 502
COUNTER_REGISTER = 15
STATE_FILE = Path(__file__).with_name("shift_state.json")
EVENT_LOG_FILE = Path(__file__).with_name("shift_event_log.csv")
MAX_STORED_SHIFTS = 200
AUTO_REFRESH_SECONDS = 5

st.set_page_config(page_title="Shift KPI", layout="wide")


def now_dt() -> datetime:
    return datetime.now()


def log_console_event(message: str) -> None:
    print(f"[{now_dt().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def ensure_event_log_file() -> None:
    if EVENT_LOG_FILE.exists():
        return

    with EVENT_LOG_FILE.open("w", encoding="utf-8") as f:
        f.write("timestamp,event,details\n")


def trim_event_log(max_lines: int = 5000) -> None:
    if not EVENT_LOG_FILE.exists():
        return
    
    with EVENT_LOG_FILE.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    
    if len(lines) <= max_lines:
        return
    
    # Keep header + most recent lines
    header = lines[0]
    recent_lines = lines[-(max_lines - 1):]
    
    with EVENT_LOG_FILE.open("w", encoding="utf-8") as f:
        f.write(header)
        f.writelines(recent_lines)


def log_event(event: str, details: str = "") -> None:
    ensure_event_log_file()
    timestamp = now_dt().strftime("%Y-%m-%d %H:%M:%S")
    safe_details = details.replace("\n", " ").replace("\r", " ")
    with EVENT_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f'{timestamp},{event},"{safe_details.replace("\"", "\"\"")}"\n')
    trim_event_log()


def dt_to_iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def iso_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def format_dt(value: str | None) -> str:
    dt_value = iso_to_dt(value)
    if dt_value is None:
        return "-"
    return dt_value.strftime("%Y-%m-%d %H:%M:%S")


def format_time(value: str | None) -> str:
    dt_value = iso_to_dt(value)
    if dt_value is None:
        return "-"
    return dt_value.strftime("%H:%M:%S")


def format_seconds(value: float | None) -> str:
    if value is None:
        return "-"
    if value < 60:
        return f"{value:.1f} s"
    minutes = int(value // 60)
    seconds = int(round(value % 60))
    return f"{minutes}m {seconds}s"


def default_state() -> dict:
    return {"active_shift": None, "shifts": []}


def load_state() -> dict:
    if not STATE_FILE.exists():
        return default_state()

    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            state = json.load(f)
        if "active_shift" not in state or "shifts" not in state:
            return default_state()
        return state
    except (json.JSONDecodeError, OSError):
        return default_state()


def save_state(state: dict) -> None:
    tmp_path = STATE_FILE.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    tmp_path.replace(STATE_FILE)


def build_active_shift(start_time: datetime, counter_value: int, inferred_start: bool) -> dict:
    last_cycle_time = dt_to_iso(start_time) if counter_value > 0 else None
    return {
        "start_time": dt_to_iso(start_time),
        "last_counter": counter_value,
        "cycles_completed": counter_value,
        "last_cycle_time": last_cycle_time,
        "interval_total_seconds": 0.0,
        "interval_count": 0,
        "inferred_start": inferred_start,
    }


def avg_from_shift(shift: dict) -> float | None:
    interval_count = int(shift.get("interval_count", 0))
    if interval_count <= 0:
        return None
    total = float(shift.get("interval_total_seconds", 0.0))
    return total / interval_count


def close_shift(active_shift: dict, end_time: datetime) -> dict:
    return {
        "start_time": active_shift.get("start_time"),
        "end_time": dt_to_iso(end_time),
        "total_cycles": int(active_shift.get("cycles_completed", 0)),
        "avg_cycle_seconds": avg_from_shift(active_shift),
    }


def update_state_with_counter(state: dict, counter_value: int, read_time: datetime) -> str:
    active = state.get("active_shift")

    if active is None:
        if counter_value == 0:
            log_event("WAITING_FOR_NEXT_SHIFT", "Counter is 0 and no shift is active.")
            return "Waiting for first cycle of next shift."

        state["active_shift"] = build_active_shift(read_time, counter_value, inferred_start=False)
        log_event("SHIFT_STARTED", f"New shift started on first cycle at counter {counter_value}.")
        return f"New shift started on first cycle ({counter_value})."

    previous = int(active.get("last_counter", 0))

    if counter_value == previous:
        return "No counter change."

    if counter_value > previous:
        increment = counter_value - previous
        last_cycle_time = iso_to_dt(active.get("last_cycle_time"))

        if last_cycle_time is not None:
            elapsed = (read_time - last_cycle_time).total_seconds()
            if elapsed > 0:
                active["interval_total_seconds"] = float(active.get("interval_total_seconds", 0.0)) + elapsed
                active["interval_count"] = int(active.get("interval_count", 0)) + increment

        active["cycles_completed"] = counter_value
        active["last_counter"] = counter_value
        active["last_cycle_time"] = dt_to_iso(read_time)
        log_event(
            "COUNTER_INCREASE",
            f"Counter increased from {previous} to {counter_value} (+{increment}).",
        )
        return f"Counter increased: {previous} -> {counter_value}"

    completed = close_shift(active, read_time)
    shifts = state.get("shifts", [])
    shifts.append(completed)
    state["shifts"] = shifts[-MAX_STORED_SHIFTS:]

    if counter_value == 0:
        state["active_shift"] = None
        log_event(
            "SHIFT_RESET_TO_ZERO",
            f"Counter reset from {previous} to 0. Previous shift closed with {completed['total_cycles']} cycles.",
        )
        log_console_event(
            f"SHIFT_RESET: Counter reset to 0 from {previous}. Previous shift closed."
        )

        return f"Shift ended at reset ({previous} -> 0). Waiting for first cycle."

    state["active_shift"] = build_active_shift(read_time, counter_value, inferred_start=False)
    log_event(
        "SHIFT_ROLLOVER",
        f"Counter dropped from {previous} to {counter_value}. Previous shift closed and new shift started.",
    )
    return f"Counter dropped ({previous} -> {counter_value}). Closed previous shift and started a new one."





def read_counter(client: ModbusTcpClient) -> int:
    result = client.read_holding_registers(address=COUNTER_REGISTER, count=1)
    if result.isError() or not getattr(result, "registers", None):
        raise ConnectionException(f"Failed to read holding register {COUNTER_REGISTER}")
    return int(result.registers[0])


def poll_plc_and_update(state: dict) -> tuple[dict, str]:
    current_time = now_dt()

    client = ModbusTcpClient(
        PLC_IP,
        port=PLC_PORT,
        timeout=3,
        retries=1,
    )

    try:
        if not client.connect():
            raise ConnectionException(f"Cannot connect to {PLC_IP}:{PLC_PORT}")

        counter = read_counter(client)

    finally:
        client.close()

    status = update_state_with_counter(state, counter, current_time)
    save_state(state)
    return state, status


def shifts_dataframe(shifts: list[dict]) -> pd.DataFrame:
    rows = []
    for shift in reversed(shifts[-10:]):
        rows.append(
            {
                "Start": format_dt(shift.get("start_time")),
                "Finish": format_dt(shift.get("end_time")),
                "Total cycles": int(shift.get("total_cycles", 0)),
                "Avg cycle": format_seconds(shift.get("avg_cycle_seconds")),
            }
        )
    return pd.DataFrame(rows)


st.title("Shift KPI Dashboard")
st.caption("Reads PLC counter, tracks shifts, and persists shift history to JSON.")

if st_autorefresh is None:
    st.warning("Install streamlit-autorefresh to enable automatic updates.")
else:
    st_autorefresh(interval=AUTO_REFRESH_SECONDS * 1000, key="shift_dashboard_autorefresh")

state = load_state()

try:
    state, _ = poll_plc_and_update(state)
except Exception as exc:
    log_console_event(f"PLC_CONNECTION_LOST: {type(exc).__name__}: {exc}")
    log_event("PLC_CONNECTION_LOST", f"{type(exc).__name__}: {exc}")
    st.error(f"PLC read failed: {exc}")

st.caption(f"Last updated: {now_dt().strftime('%H:%M:%S')}")

active_shift = state.get("active_shift")

if active_shift is not None:
    current_cycles = int(active_shift.get("cycles_completed", 0))
    current_avg = avg_from_shift(active_shift)
    current_start = active_shift.get("start_time")

    col1, col2, col3 = st.columns(3)
    col1.metric("Current shift cycles", current_cycles, border=True)
    col2.metric("Current avg cycle time", format_seconds(current_avg), border=True)
    col3.metric("Current shift start", format_time(current_start), border=True)

    if active_shift.get("inferred_start"):
        st.info("Current shift started before this dashboard was running; start time is inferred.")
else:
    st.warning("No active shift yet.")

st.subheader("Last 10 completed shifts")
last_10_df = shifts_dataframe(state.get("shifts", []))
if last_10_df.empty:
    st.info("No completed shifts yet.")
else:
    st.dataframe(last_10_df, hide_index=True, width="stretch")
