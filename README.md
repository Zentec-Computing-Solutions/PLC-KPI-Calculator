# PLC KPI RTSP Publisher

This project reads a current-shift count and four previous-shift counts from PLC
holding registers and publishes them as an H.264 RTSP video stream. The same Python
publisher is used on Windows and Raspberry Pi OS; only installation and service
management differ.

## Repository layout

```text
common/          Shared Python publisher and PLC diagnostic
config/          Shared MediaMTX configuration and environment example
windows/         Windows MediaMTX binary and supervised batch launchers
raspberry-pi/    Pi installer, launcher, and systemd services
tests/           Configuration and frame-generation tests
```

The Streamlit dashboard and its state/event files have been removed.

## Register mapping

By default, the publisher reads five consecutive holding registers:

| Register | Displayed value |
| --- | --- |
| 15 | Current shift |
| 16 | Previous shift -1 |
| 17 | Previous shift -2 |
| 18 | Previous shift -3 |
| 19 | Previous shift -4 |

Set `SHIFT_REGISTER` and `SHIFT_REGISTER_COUNT` if the PLC mapping changes. At
least five registers are required.

## Windows

The existing top-level `start_shift_monitor.bat` remains as a compatibility
launcher. It now delegates to the scripts in `windows/`, which restart MediaMTX
or the publisher if either exits.

Create the Python environment once from a Command Prompt in the project directory:

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Then run:

```bat
start_shift_monitor.bat
```

`windows/run_publisher.bat` retains the FFmpeg path used by the original PC. If
FFmpeg moves, set `FFMPEG_PATH` in the Windows environment or edit that default.
Other settings can also be set as Windows environment variables using the names
in `config/shift-monitor.env.example`.

The encoder sends an H.264 keyframe every two seconds by default. This lets VLC
and camera software begin displaying the stream promptly instead of waiting for
FFmpeg's much longer default keyframe interval.

For startup after reboot, create a Windows Task Scheduler task that runs
`start_shift_monitor.bat` at system startup, whether or not a user is logged in.

## Raspberry Pi installation

Use Raspberry Pi OS Lite 64-bit and wired Ethernet where possible. Clone or copy
this repository to the Pi, then run:

```bash
chmod +x raspberry-pi/install.sh raspberry-pi/start_shift_monitor.sh
sudo ./raspberry-pi/install.sh
sudo nano /etc/plc-kpi/shift-monitor.env
sudo systemctl start mediamtx.service shift-monitor.service
```

The installer:

- Installs FFmpeg, OpenCV, NumPy, Python, and supporting OS packages.
- Installs the ARM build of MediaMTX.
- Creates an unprivileged `plc-kpi` service account.
- Places application files under `/opt/plc-kpi`.
- Places configuration under `/etc/plc-kpi`.
- Enables both services at boot with automatic restart.

Check status and follow logs with:

```bash
sudo systemctl status mediamtx.service shift-monitor.service
sudo journalctl -u mediamtx -u shift-monitor -f
```

The camera system should use:

```text
rtsp://PI_ADDRESS:8554/shift-count
```

## Offsite test without the PLC

Mock mode exercises frame generation, FFmpeg, MediaMTX, RTSP publishing, and
service recovery without contacting the PLC.

On the Pi, edit `/etc/plc-kpi/shift-monitor.env` and set:

```text
MOCK_PLC=true
```

Restart the publisher:

```bash
sudo systemctl restart shift-monitor.service
```

View `rtsp://PI_ADDRESS:8554/shift-count` in VLC. Return `MOCK_PLC=false` before
connecting the Pi to the real PLC network.

For a manual development run, start MediaMTX and then use:

```bash
python common/rtsp_stream.py --mock-plc
```

## Remote PLC testing with Tailscale

Tailscale is optional. Mock mode is sufficient for nearly all offsite testing.
For a real register read before the Pi is onsite, an onsite Tailscale device would
need to advertise the PLC's subnet (for example `192.168.88.0/24`) as a subnet
router. The route must then be approved in Tailscale and reachable from the Pi.

Do not expose Modbus TCP port 502 directly to the internet. If a subnet route is
used, restrict access to the Pi and PLC subnet with Tailscale access controls, and
coordinate the test with whoever manages the production network.

## Local checks

After installing `requirements.txt`:

```bash
python -m unittest discover -s tests -v
python common/rtsp_stream.py --check
```
