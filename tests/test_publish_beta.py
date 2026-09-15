import hashlib
import io
import json
import urllib.error

import pytest

from tools import publish_beta, publish_github_apk
from tools.publish_beta import publish


def test_publish_checks_evidence_and_never_replaces_latest_on_failure(tmp_path, monkeypatch):
    apk = tmp_path / "test.apk"
    apk.write_bytes(b"test fixture")
    verification = tmp_path / "verification.json"
    evidence = {"sha256": hashlib.sha256(apk.read_bytes()).hexdigest(), "bytes": apk.stat().st_size,
                "signatureVerified": True, "zip16KiBAligned": True, "installedSha256Matches": True}
    verification.write_text(json.dumps(evidence))
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("test")
    original = apk.read_bytes()
    copy_file = publish_beta.shutil.copyfile

    def copy_then_rebuild(source, destination):
        copy_file(source, destination)
        apk.write_bytes(b"a new build is replacing the source file")

    with monkeypatch.context() as patch:
        patch.setattr(publish_beta.shutil, "copyfile", copy_then_rebuild)
        release = publish(apk, verification, site)
    assert release["bytes"] == len(original)
    apk.write_bytes(original)
    assert (site / release["apk"]).read_bytes() == apk.read_bytes()
    previous = (site / "release.json").read_bytes()
    verification.write_text("[]")
    with pytest.raises(ValueError, match="must match"):
        publish(apk, verification, site)
    verification.write_text(json.dumps(evidence))
    report = tmp_path / "report.json"
    report.write_text("{}")
    with pytest.raises(ValueError, match="different APK"):
        publish(apk, verification, site, report)
    assert (site / "release.json").read_bytes() == previous
    report.with_suffix(".md").write_text("QA fixture")
    report.with_suffix(".pdf").write_bytes(b"PDF fixture")
    report.write_text(json.dumps({"apkSha256": evidence["sha256"], "artifacts": {
        "markdownSha256": hashlib.sha256(report.with_suffix(".md").read_bytes()).hexdigest(),
        "pdfSha256": hashlib.sha256(report.with_suffix(".pdf").read_bytes()).hexdigest(),
    }}))
    publish(apk, verification, site, report)
    previous = (site / "release.json").read_bytes()
    report.with_suffix(".md").write_text("Part of another report generation")
    with pytest.raises(ValueError, match="Report files changed"):
        publish(apk, verification, site, report)
    assert (site / "release.json").read_bytes() == previous
    apk.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="must match"):
        publish(apk, verification, site)
    assert (site / "release.json").read_bytes() == previous


def test_failed_github_upload_never_updates_latest_metadata(tmp_path, monkeypatch):
    apk = tmp_path / "test.apk"
    apk.write_bytes(b"verified fixture")
    verification = tmp_path / "verification.json"
    verification.write_text(json.dumps({
        "sha256": hashlib.sha256(apk.read_bytes()).hexdigest(), "bytes": apk.stat().st_size,
        "signatureVerified": True, "zip16KiBAligned": True, "installedSha256Matches": True,
    }))
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("fixture")
    publish(apk, verification, site)
    previous = (site / "release.json").read_bytes()

    def fail_upload(*args):
        raise ValueError("GitHub asset mismatch")

    monkeypatch.setattr(publish_beta, "publish_asset", fail_upload)
    with pytest.raises(ValueError, match="GitHub asset mismatch"):
        publish(apk, verification, site, github_release=True)
    assert (site / "release.json").read_bytes() == previous


def test_github_publishes_draft_only_after_asset_digest_matches(tmp_path, monkeypatch):
    apk = tmp_path / "test.apk"
    apk.write_bytes(b"verified fixture")
    checksum = hashlib.sha256(apk.read_bytes()).hexdigest()
    release = {"id": 7, "tag_name": "android-beta", "draft": True, "assets": []}
    requests = []
    asset_checksum = checksum
    monkeypatch.setattr(publish_github_apk, "github_token", lambda: "test-credential")

    def respond(request, timeout):
        assert timeout == 180
        requests.append((request.method, request.full_url))
        if "/tags/" in request.full_url:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
        if "?per_page" in request.full_url:
            value = []
        elif "/assets?" in request.full_url:
            assert request.data == apk.read_bytes()
            value = {"state": "uploaded", "size": apk.stat().st_size,
                     "digest": f"sha256:{asset_checksum}"}
        else:
            if request.method == "POST":
                assert json.loads(request.data)["draft"] is True
            if request.method == "PATCH":
                assert json.loads(request.data) == {"draft": False}
            value = release
        return io.BytesIO(json.dumps(value).encode())

    monkeypatch.setattr(publish_github_apk.urllib.request, "urlopen", respond)
    url = publish_github_apk.publish_asset(apk, checksum)
    assert url.endswith(f"/android-beta/{checksum[:16]}.apk")
    assert requests[-1][0] == "PATCH"
    requests.clear()
    asset_checksum = "0" * 64
    with pytest.raises(ValueError, match="does not match"):
        publish_github_apk.publish_asset(apk, checksum)
    assert all(method != "PATCH" for method, endpoint in requests)


def test_watch_retries_mismatch_without_republishing_unchanged_inputs(tmp_path, monkeypatch):
    apk = tmp_path / "test.apk"
    apk.write_bytes(b"first fixture")
    verification = tmp_path / "verification.json"
    evidence = {"sha256": hashlib.sha256(apk.read_bytes()).hexdigest(), "bytes": apk.stat().st_size,
                "signatureVerified": True, "zip16KiBAligned": True, "installedSha256Matches": True}
    verification.write_text(json.dumps(evidence))
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("test")
    monkeypatch.setattr("sys.argv", ["publish_beta", str(apk), str(verification),
                                    "--site", str(site), "--watch", "5"])
    publications = []
    waits = []

    def observe(*args):
        release = publish(*args)
        publications.append(release["sha256"])
        return release

    def advance(seconds):
        assert seconds == 5
        waits.append(seconds)
        if len(waits) == 2:
            apk.write_bytes(b"new fixture, different size")
        elif len(waits) == 3:
            assert len(publications) == 1
            assert json.loads((site / "release.json").read_text())["sha256"] == publications[0]
            evidence.update(sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),
                            bytes=apk.stat().st_size)
            verification.write_text(json.dumps(evidence))
        elif len(waits) == 4:
            raise KeyboardInterrupt

    monkeypatch.setattr(publish_beta, "publish", observe)
    monkeypatch.setattr(publish_beta.time, "sleep", advance)
    with pytest.raises(KeyboardInterrupt):
        publish_beta.main()
    assert len(publications) == 2
    assert publications[-1] == evidence["sha256"]
