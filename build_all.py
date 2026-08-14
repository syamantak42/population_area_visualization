import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
for script in ["download_data.py", "build_chart.py"]:
    subprocess.run([sys.executable, str(root / script)], check=True)
