#!/usr/bin/env bash
set -u

service_name="${1:-unknown.service}"
service_result="${2:-unknown}"

# systemd also invokes ExecStopPost for intentional stops and restarts.
if [[ "${service_result}" == "success" ]]; then
    rm -f "/opt/plc-kpi/alert-state/${service_name//[^a-zA-Z0-9_.-]/_}.alerted"
    exit 0
fi

if [[ -z "${N8N_WEBHOOK:-}" ]]; then
    echo "N8N_WEBHOOK is not configured; service failure alert was not sent" >&2
    exit 0
fi

state_dir="/opt/plc-kpi/alert-state"
latch_file="${state_dir}/${service_name//[^a-zA-Z0-9_.-]/_}.alerted"
mkdir -p "${state_dir}"

if [[ -e "${latch_file}" ]]; then
    echo "An alert was already sent for the current ${service_name} incident" >&2
    exit 0
fi

timestamp="$(date --iso-8601=seconds)"
host_name="$(hostname)"
payload="$(printf \
    '{"service":"%s","status":"service_failed","error":"systemd result: %s","timestamp":"%s","hostname":"%s","workspace":"/opt/plc-kpi"}' \
    "${service_name}" "${service_result}" "${timestamp}" "${host_name}")"

if curl \
    --silent \
    --show-error \
    --fail \
    --max-time 5 \
    --header "Content-Type: application/json" \
    --request POST \
    --data "${payload}" \
    "${N8N_WEBHOOK}" >/dev/null; then
    : > "${latch_file}"
    echo "Sent ${service_name} failure alert to n8n"
else
    echo "Failed to send ${service_name} failure alert to n8n" >&2
fi
