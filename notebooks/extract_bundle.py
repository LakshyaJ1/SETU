"""Extract the downloaded training bundle strictly inside notebooks."""
import pathlib, sys
import zipfile

root = pathlib.Path(__file__).resolve().parent
destination = (root / "setu-speed-v1").resolve()
destination.mkdir(exist_ok=True)
archive_path = (root / (sys.argv[1] if len(sys.argv) > 1 else "setu-speed-v1.zip")).resolve()
if not archive_path.is_relative_to(root):
    raise ValueError("Archive must be inside notebooks")
with zipfile.ZipFile(archive_path) as archive:
    for member in archive.infolist():
        if not (destination / member.filename).resolve().is_relative_to(destination):
            raise ValueError("Archive member escapes output directory")
    archive.extractall(destination)
print("Extracted", len(list(destination.iterdir())), "artifacts to", destination)
