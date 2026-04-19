# -*- coding: utf-8 -*-
import sys

MIN_PYTHON = (3, 10)
major = sys.version_info[0]
minor = sys.version_info[1]
if sys.version_info < MIN_PYTHON:
    raise RuntimeError(
        "Python %d.%d+ is required to run the frontend. Current version: %d.%d." % (
            MIN_PYTHON[0],
            MIN_PYTHON[1],
            major,
            minor,
        )
    )

from webapp import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
