#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run this installer with sudo: sudo ./raspberry-pi/install.sh" >&2
    exit 1
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "${script_dir}/.." && pwd)"
mediamtx_version="${MEDIAMTX_VERSION:-1.19.3}"

case "$(uname -m)" in
    aarch64|arm64) mediamtx_arch="arm64" ;;
    armv7l) mediamtx_arch="armv7" ;;
    *)
        echo "Unsupported architecture: $(uname -m). Expected arm64 or armv7." >&2
        exit 1
        ;;
esac

apt-get update
apt-get install -y ca-certificates curl ffmpeg python3 python3-numpy python3-opencv python3-venv

if ! id plc-kpi >/dev/null 2>&1; then
    useradd --system --home-dir /opt/plc-kpi --shell /usr/sbin/nologin plc-kpi
fi

install -d -o plc-kpi -g plc-kpi /opt/plc-kpi
install -d -m 0755 /etc/plc-kpi
install -m 0644 "${project_dir}/common/rtsp_stream.py" /opt/plc-kpi/rtsp_stream.py
install -m 0644 "${project_dir}/config/mediamtx.yml" /etc/plc-kpi/mediamtx.yml

if [[ ! -f /etc/plc-kpi/shift-monitor.env ]]; then
    install -m 0644 "${project_dir}/config/shift-monitor.env.example" /etc/plc-kpi/shift-monitor.env
fi

python3 -m venv --system-site-packages /opt/plc-kpi/.venv
/opt/plc-kpi/.venv/bin/pip install --upgrade pip
/opt/plc-kpi/.venv/bin/pip install 'pymodbus>=3.8,<4'
chown -R plc-kpi:plc-kpi /opt/plc-kpi

download_dir="$(mktemp -d)"
archive="${download_dir}/mediamtx.tar.gz"
curl --fail --location --output "${archive}" \
    "https://github.com/bluenviron/mediamtx/releases/download/v${mediamtx_version}/mediamtx_v${mediamtx_version}_linux_${mediamtx_arch}.tar.gz"
tar -xzf "${archive}" -C "${download_dir}" mediamtx
install -m 0755 "${download_dir}/mediamtx" /usr/local/bin/mediamtx
rm -rf "${download_dir}"

install -m 0644 "${script_dir}/systemd/mediamtx.service" /etc/systemd/system/mediamtx.service
install -m 0644 "${script_dir}/systemd/shift-monitor.service" /etc/systemd/system/shift-monitor.service
systemctl daemon-reload
systemctl enable mediamtx.service shift-monitor.service

echo
echo "Installation complete."
echo "Edit /etc/plc-kpi/shift-monitor.env, then start with:"
echo "  sudo systemctl start mediamtx.service shift-monitor.service"
echo "View logs with:"
echo "  sudo journalctl -u mediamtx -u shift-monitor -f"
