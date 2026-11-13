#!/data/data/com.termux/files/usr/bin/sh
# Start Keyfall. Extra arguments go to the server, e.g.  ./start.sh --host 0.0.0.0 --port 9000
cd "$(dirname "$0")" || exit 1
python3 -c "import mido" 2>/dev/null || pip install mido
if [ ! -f data/keyfall.db ]; then
    python3 -I app/seed.py
    # Real album artwork; runs in the background (a few minutes), songs show generated covers meanwhile.
    python3 -I app/fetch_covers.py > data/fetch_covers.log 2>&1 &
fi
exec python3 -I app/server.py "$@"
