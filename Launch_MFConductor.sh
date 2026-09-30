#!/bin/sh
cd "$(dirname "$0")"
PYTHON=python3
if [ -x "../../../python_embeded/python" ]; then
    PYTHON="../../../python_embeded/python"
elif [ -x "../../../python_embeded/bin/python" ]; then
    PYTHON="../../../python_embeded/bin/python"
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
fi
exec "$PYTHON" standalone_server.py --host localhost --port 8199
