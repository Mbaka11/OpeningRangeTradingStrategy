import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_config_loads_dotenv_from_explicit_cloud_mount_path(tmp_path):
    dotenv_path = tmp_path / "cloud-run.env"
    dotenv_path.write_text("OANDA_INSTRUMENT=TEST_CLOUD_INSTRUMENT\n", encoding="utf-8")

    environment = os.environ.copy()
    environment["DOTENV_PATH"] = str(dotenv_path)
    environment.pop("OANDA_INSTRUMENT", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from opening_range_bot.config import OANDA_INSTRUMENT; print(OANDA_INSTRUMENT)",
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        text=True,
        capture_output=True,
    )

    assert result.stdout.strip() == "TEST_CLOUD_INSTRUMENT"
