import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from datheon_data.signal_cli import run
from datheon_data.signals import SignalConfig


class SignalCliTests(unittest.TestCase):
    def test_parquet_input_to_output_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "processed" / "daily"
            source.mkdir(parents=True)
            bars = pd.DataFrame({
                "adjusted_close": [100.0 + i for i in range(80)],
                "symbol": "TEST", "frequency": "daily",
            }, index=pd.date_range("2024-01-01", periods=80, tz="UTC", name="timestamp"))
            bars.to_parquet(source / "TEST.parquet")
            output = root / "signals"
            self.assertEqual(run(root / "processed", output, SignalConfig()), 0)
            result = pd.read_parquet(output / "daily" / "TEST.parquet")
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(len(result), 80)
            self.assertEqual(result["known_adjusted_close"].iloc[1], 100.0)
            self.assertEqual(manifest["results"][0]["status"], "ok")
            self.assertEqual(len(manifest["results"][0]["source_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
