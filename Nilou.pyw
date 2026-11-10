"""Launch Nilou from source (double-click or `pythonw Nilou.pyw`)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nilou.main import main  # noqa: E402

if __name__ == '__main__':
    main(sys.argv[1:])
