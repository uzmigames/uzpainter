"""Run the Assets3D adapter with --production-round REQUEST or --diagnostic-import."""

import sys

from adapters.assets3d.layer_stack import main

sys.exit(main())
