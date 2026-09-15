"""Publish a verified beta APK as an immutable GitHub Release asset."""

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = "Aj242005/setu-website"
TAG = "android-beta"


def github_token():
    try:
        result = subprocess.run(
            ["git", "credential", "fill"],
            input=f"protocol=https\nhost=github.com\npath={REPOSITORY}.git\n\n",
            text=True, capture_output=True, timeout=30,
            env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never"),
        )
    except subprocess.TimeoutExpired:
        raise ValueError("GitHub authentication timed out; previous release is unchanged") from None
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if result.returncode or not fields.get("password"):
        raise ValueError("Sign in to GitHub through Git Credential Manager before publishing")
    return fields["password"]


def publish_asset(apk, checksum):
    token = github_token()

    def request(endpoint, method="GET", body=None, upload=False):
        host = "uploads.github.com" if upload else "api.github.com"
        data = body if upload else json.dumps(body).encode() if body is not None else None
        query = urllib.request.Request(
            f"https://{host}/repos/{REPOSITORY}/{endpoint}", data=data, method=method,
            headers={"Authorization": f"Bearer {token}", "User-Agent": "SETU-beta-publisher",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "Content-Type": "application/octet-stream" if upload else "application/json"},
        )
        with urllib.request.urlopen(query, timeout=180) as response:
            return json.load(response)

    try:
        release = request(f"releases/tags/{TAG}")
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        releases = request("releases?per_page=100")
        release = next((item for item in releases if item["tag_name"] == TAG), None)
        if release is None:
            release = request("releases", "POST", {
                "tag_name": TAG, "target_commitish": "main", "draft": True, "prerelease": True,
                "name": "SETU Android development beta",
                "body": "Verified, hash-named Android beta APKs. See the website release.json for "
                        "the current APK SHA-256 and test report. GPS-free navigation and "
                        "background capture are not approved. Recordings are not uploaded here.",
            })
    filename = f"{checksum[:16]}.apk"
    asset = next((item for item in release["assets"] if item["name"] == filename), None)
    if asset is None:
        asset = request(
            f"releases/{release['id']}/assets?name={urllib.parse.quote(filename)}",
            "POST", apk.read_bytes(), upload=True,
        )
    if (asset.get("state") != "uploaded" or asset.get("size") != apk.stat().st_size
            or asset.get("digest") != f"sha256:{checksum}"):
        raise ValueError("GitHub asset does not match the verified APK; no asset is overwritten")
    if release["draft"]:
        request(f"releases/{release['id']}", "PATCH", {"draft": False})
    return f"https://github.com/{REPOSITORY}/releases/download/{TAG}/{filename}"
