"""Atomically update the local beta website from an APK and matching verification evidence."""

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from tools.publish_github_apk import publish_asset


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def publish(apk, verification, site, report=None, github_release=False):
    evidence = json.loads(verification.read_text(encoding="utf-8-sig"))
    checksum = digest(apk)
    required = ("signatureVerified", "zip16KiBAligned", "installedSha256Matches")
    if (not isinstance(evidence, dict) or evidence.get("sha256") != checksum
            or evidence.get("bytes") != apk.stat().st_size
            or not all(evidence.get(key) is True for key in required)):
        raise ValueError("APK must match signature, alignment and installed-device verification")
    if not (site / "index.html").is_file():
        raise ValueError("The beta site must exist before publishing")
    qa = json.loads(report.read_text(encoding="utf-8-sig")) if report else None
    if report is not None and (not isinstance(qa, dict) or qa.get("apkSha256") != checksum):
        raise ValueError("QA report belongs to a different APK")
    if qa and not report.with_suffix(".md").is_file():
        raise ValueError("QA Markdown report is required for the website link")
    if qa:
        artifacts = qa.get("artifacts")
        if not isinstance(artifacts, dict):
            raise ValueError("Report files lack hashes; regenerate the QA report")
        for suffix, key in ((".md", "markdownSha256"), (".pdf", "pdfSha256")):
            artifact = report.with_suffix(suffix)
            if (not artifact.is_file() or
                    artifacts.get(key) != digest(artifact)):
                raise ValueError("Report files changed or lack hashes; regenerate the QA report")
    downloads = site / "downloads"
    downloads.mkdir(exist_ok=True)
    destination = downloads / f"{checksum[:16]}.apk"
    if destination.exists() and digest(destination) != checksum:
        raise ValueError("Refusing to overwrite a conflicting versioned artifact")
    if not destination.exists():
        descriptor, staging = tempfile.mkstemp(dir=downloads, suffix=".partial")
        os.close(descriptor)
        try:
            shutil.copyfile(apk, staging)
            if digest(Path(staging)) != checksum:
                raise ValueError("Copied APK failed verification")
            os.replace(staging, destination)
        finally:
            Path(staging).unlink(missing_ok=True)
    release = {"channel": "development beta", "publishedAt": datetime.now(timezone.utc).isoformat(),
               "apk": f"downloads/{destination.name}", "sha256": checksum,
               "bytes": destination.stat().st_size, "navigationAccuracyApproved": False,
               "verification": evidence, "qa": qa}
    if qa:
        reports = site / "reports"
        reports.mkdir(exist_ok=True)
        report_hash = digest(report.with_suffix(".md"))
        target = reports / f"{report_hash[:16]}.md"
        if not target.exists():
            shutil.copyfile(report.with_suffix(".md"), target)
        if digest(target) != report_hash:
            raise ValueError("Conflicting published report")
        release["report"] = f"reports/{target.name}"
        release["reportSha256"] = report_hash
        pdf = report.with_suffix(".pdf")
        if pdf.is_file():
            pdf_hash = digest(pdf)
            pdf_target = reports / f"{pdf_hash[:16]}.pdf"
            if not pdf_target.exists():
                shutil.copyfile(pdf, pdf_target)
            if digest(pdf_target) != pdf_hash:
                raise ValueError("Conflicting published PDF")
            release["reportPdf"] = f"reports/{pdf_target.name}"
    if github_release:
        publish_asset(destination, checksum)
    descriptor, staging = tempfile.mkstemp(dir=site, suffix=".partial")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(release, stream, indent=2)
            stream.write("\n")
        os.replace(staging, site / "release.json")
    finally:
        Path(staging).unlink(missing_ok=True)
    return release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("verification", type=Path)
    parser.add_argument("--site", type=Path, default=Path("../setu-website"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--github-release", action="store_true",
                        help="Upload the verified APK to GitHub Releases before publishing")
    parser.add_argument("--watch", type=int, metavar="SECONDS")
    args = parser.parse_args()
    if args.watch is not None and not 5 <= args.watch <= 3600:
        parser.error("--watch must be between 5 and 3600 seconds")
    sources = [args.apk, args.verification]
    if args.report:
        sources.extend([args.report, args.report.with_suffix(".md"),
                        args.report.with_suffix(".pdf")])
    previous = None
    while True:
        try:
            current = [(path.stat().st_mtime_ns, path.stat().st_size)
                       if path.exists() else None for path in sources]
            if current != previous:
                release = publish(args.apk, args.verification, args.site, args.report,
                                  args.github_release)
                print(f"Updated {args.site / 'release.json'}: {release['sha256']}", flush=True)
                previous = current
        except (OSError, ValueError) as error:
            if args.watch is None:
                raise
            print(f"Keeping previous release; waiting for verified artifacts: {error}", flush=True)
        if args.watch is None:
            break
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
