import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# isolated data dir + offline provider for every test run (set before server.config is imported)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="ebook-test-")
os.environ["LLM_PROVIDER"] = "mock"
SAMPLE = ROOT / "sample" / "1706.03762v7.pdf"
