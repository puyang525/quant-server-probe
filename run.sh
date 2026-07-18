#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="${QUANT_PROBE_REPOSITORY:-puyang525/quant-server-probe}"
VERSION="${QUANT_PROBE_VERSION:-main}"
BASE_URL="https://raw.githubusercontent.com/${REPOSITORY}/${VERSION}"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/quant-server-probe.XXXXXXXX")"

normalize_language() {
  local value="${1:-}"
  value="${value%%.*}"
  value="${value//@/-}"
  value="${value//_/-}"
  case "${value,,}" in
    en|en-*) echo "en" ;;
    zh-cn|zh-sg|zh-hans|zh-hans-*) echo "zh-CN" ;;
    zh-tw|zh-hk|zh-mo|zh-hant|zh-hant-*) echo "zh-TW" ;;
    *) return 1 ;;
  esac
}

select_language() {
  local detected="" candidate="${QUANT_PROBE_LANG:-${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}}"
  if detected="$(normalize_language "$candidate" 2>/dev/null)"; then
    printf '%s\n' "$detected"
    return
  fi
  if [[ -r /dev/tty && -w /dev/tty ]]; then
    {
      echo "Unable to detect a supported language / 无法识别支持的语言。"
      echo "1) English"
      echo "2) 简体中文"
      echo "3) 繁體中文"
      printf "Select language [1]: "
    } >/dev/tty
    local choice=""
    IFS= read -r choice </dev/tty || true
    case "$choice" in 2) echo "zh-CN";; 3) echo "zh-TW";; *) echo "en";; esac
  else
    echo "[i] Unsupported or missing locale '${candidate:-unset}'; using English. Set QUANT_PROBE_LANG=en|zh-CN|zh-TW to override." >&2
    echo "en"
  fi
}

export QUANT_PROBE_LANG="$(select_language)"

cleanup() {
  rm -rf -- "$WORK_DIR"
}
trap cleanup EXIT INT TERM HUP

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: Python 3.10+ is required." >&2
  exit 2
fi

python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "Error: Python 3.10+ is required." >&2
  exit 2
}

download() {
  local source="$1" destination="$2"
  if command -v curl >/dev/null 2>&1; then
    curl --fail --silent --show-error --location \
      --connect-timeout 10 --max-time 60 \
      "$source" --output "$destination"
  elif command -v wget >/dev/null 2>&1; then
    wget --quiet --timeout=60 --output-document="$destination" "$source"
  else
    echo "Error: curl or wget is required." >&2
    exit 2
  fi
}

download "$BASE_URL/quant_net_probe.py" "$WORK_DIR/quant_net_probe.py"
download "$BASE_URL/endpoints.json" "$WORK_DIR/endpoints.json"

if (($# == 0)); then
  set -- probe --label "$(hostname 2>/dev/null || echo candidate-server)" --profile balanced
elif [[ "$1" != "probe" && "$1" != "compare" && "$1" != "show" && "$1" != "discover" && "$1" != "public" && "$1" != "aggregate" ]]; then
  set -- probe "$@"
fi

python3 "$WORK_DIR/quant_net_probe.py" "$@"
