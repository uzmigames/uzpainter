"""`python -m adapters.assets3d [--pin FILE=SHA256]... <painter_layer_stack.py> <its arguments>`."""

import sys

from adapters.assets3d.layer_stack import main

sys.exit(main())
