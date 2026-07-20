"""Entry point: ``python -m drawing_analyzer`` launches the Drawing Context Analyzer GUI."""
from __future__ import annotations

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()

    # Import the GUI only after multiprocessing has installed the frozen-app
    # bootstrap.  Importing it earlier lets spawned annotation workers execute
    # GUI module initialization before ``freeze_support()`` on Windows.
    from .gui import main

    main()
