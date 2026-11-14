import atexit
import os
import shutil
import tempfile

# Installed hooks run by the tests inherit this environment; without it they write session
# locks and events into the developer's real ~/.harness/telemetry.
_DIR = tempfile.mkdtemp(prefix="harness-test-telemetry-")
os.environ["HARNESS_TELEMETRY_DIR"] = _DIR
atexit.register(shutil.rmtree, _DIR, True)
