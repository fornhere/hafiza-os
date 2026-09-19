#!/usr/bin/env bash
set -euo pipefail
command -v curl >/dev/null || { echo 'curl gerekli.' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'Python 3.10+ kurup bu komutu tekrar çalıştır.' >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else "Python 3.10+ gerekli")'
hafiza_tmp="$(mktemp -d)"
trap 'rm -rf -- "$hafiza_tmp"' EXIT
curl -fsSL https://api.github.com/repos/fornhere/hafiza-os/commits/main -o "$hafiza_tmp/revision.json"
hafiza_revision="$(python3 -c 'import json,re,sys; s=json.load(open(sys.argv[1]))["sha"]; assert re.fullmatch("[a-f0-9]{40}",s); print(s)' "$hafiza_tmp/revision.json")"
curl -fsSL "https://raw.githubusercontent.com/fornhere/hafiza-os/$hafiza_revision/baslat.py" -o "$hafiza_tmp/baslat.py"
# pipe ile gelen script stdin'ini anahtar sorularına karıştırma.
if [[ " $* " == *" --non-interactive "* ]]; then
  python3 "$hafiza_tmp/baslat.py" --revision "$hafiza_revision" "$@"
else
  python3 "$hafiza_tmp/baslat.py" --revision "$hafiza_revision" "$@" </dev/tty
fi
