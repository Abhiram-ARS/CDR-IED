import sys
from pathlib import Path
import webview

import CDRIED_backend

def main():
    if webview is None:
        raise RuntimeError('pywebview is required to run the dashboard UI.')

    backend = CDRIED_backend.Functions()
    webview.create_window(
        "CDR-IED: Call Detail Record Dashboard",
        "fend.html",
        js_api=backend
    )
    webview.start()


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--matplotlib-statistic':
        CDRIED_backend.Statistics(Path(sys.argv[3]).resolve().parent).show_window(sys.argv[2], sys.argv[3])
    else:
        main()