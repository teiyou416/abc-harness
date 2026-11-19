"""Copy BlockSim's Excel result to result.xlsx and write one CSV per sheet.

Usage: python xlsx_to_csv.py <directory holding exactly one .xlsx> <output directory>
"""

import shutil
import sys
from pathlib import Path

import pandas as pd

source_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
workbooks = sorted(source_dir.glob("*.xlsx"))
if len(workbooks) != 1:
    sys.exit(f"expected exactly one .xlsx in {source_dir}, found {len(workbooks)}")
out_dir.mkdir(parents=True, exist_ok=True)
shutil.copyfile(workbooks[0], out_dir / "result.xlsx")
for sheet, frame in pd.read_excel(workbooks[0], sheet_name=None, index_col=0).items():
    frame.to_csv(out_dir / f"{sheet}.csv", index=False)
