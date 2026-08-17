#!/usr/bin/env bash
set -euo pipefail

sudo systemctl start mediamtx.service shift-monitor.service
sudo systemctl --no-pager --full status mediamtx.service shift-monitor.service
