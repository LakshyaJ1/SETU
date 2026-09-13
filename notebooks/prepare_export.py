"""Build an export-only Kaggle job that reuses the existing trained checkpoint."""
from pathlib import Path
root = Path(__file__).resolve().parent
model = (root/"setu_model.py").read_text(encoding="utf-8")
code = (root/"export_checkpoint.py").read_text(encoding="utf-8")
code = code.replace("import setu_model as sm", "import types\nsm = types.SimpleNamespace(tf=tf)")
code = code.replace('ROOT = pathlib.Path(__file__).resolve().parent', '''ROOT = pathlib.Path.cwd()
sources = sorted(pathlib.Path("/kaggle/input").rglob("speed_model.keras"))
if not sources:
    raise RuntimeError("Attach the completed SETU training notebook as an input")
shutil.copytree(sources[0].parent, ROOT / "setu-speed-v1", dirs_exist_ok=True)''')
(root/"kaggle_export.py").write_text(model+"\n\n"+code, encoding="utf-8")
print("Built export-only job")
