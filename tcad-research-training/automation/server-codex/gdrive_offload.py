#!/usr/bin/env python3
"""Optional Google Drive cold-archive offload and restore for retained TCAD runs.

Never modifies original manifests, locks, or active solver state. Failures fall
back cleanly to local retention without blocking or pausing runtime queues.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid


OFFLOAD_SCHEMA = "tcad-result-gdrive-offload-v1"
OFFLOAD_RECEIPT = "gdrive-offload.json"
OFFLOAD_STATUS = "gdrive-offload-status.json"
DEFAULT_CONFIG_PATH = Path("/var/lib/tcad-autonomy/gdrive/config.json")
DEFAULT_TIMEOUT = 120
CHUNK_SIZE = 4 * 1024 * 1024
TOKEN_URI = "https://oauth2.googleapis.com/token"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"


def resolve_config_path(config_path=None):
    if config_path:
        return Path(config_path)
    env = os.environ.get("TCAD_GDRIVE_CONFIG", "").strip()
    return Path(env) if env else DEFAULT_CONFIG_PATH


def load_config(config_path=None):
    path = resolve_config_path(config_path)
    if path.is_symlink() or not path.is_file():
        return {"enabled": False, "config_path": str(path), "reason": "missing_config"}
    cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(cfg, dict):
        raise ValueError("Drive offload config must be a JSON object")
    cfg.setdefault("enabled", False)
    cfg.setdefault("delete_local_raw", False)
    cfg.setdefault("mode", "oauth")
    cfg.setdefault("timeout_seconds", DEFAULT_TIMEOUT)
    cfg["config_path"] = str(path)
    return cfg


def file_hashes(path):
    """Compute (size, sha256_hex, md5_hex) in a single streaming pass."""
    sha = hashlib.sha256()
    md5 = hashlib.md5()
    size = 0
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(block)
            sha.update(block)
            md5.update(block)
    return size, sha.hexdigest(), md5.hexdigest()


def _build_opener(proxy=None):
    handlers = []
    proxy_url = (proxy or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or "").strip()
    if proxy_url:
        handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    return urllib.request.build_opener(*handlers)


def _request_json(opener, url, headers=None, data=None, method=None, timeout=DEFAULT_TIMEOUT):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with opener.open(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}


def _refresh_access_token(cfg, opener):
    token_path = Path(cfg["token_file"])
    if token_path.is_symlink() or not token_path.is_file():
        raise ValueError("Missing OAuth token file: " + str(token_path))
    token_data = json.loads(token_path.read_text(encoding="utf-8-sig"))
    for key in ("client_id", "client_secret", "refresh_token"):
        if not isinstance(token_data.get(key), str) or not token_data[key].strip():
            raise ValueError("OAuth token file missing field: " + key)
    form = urllib.parse.urlencode({
        "client_id": token_data["client_id"],
        "client_secret": token_data["client_secret"],
        "refresh_token": token_data["refresh_token"],
        "grant_type": "refresh_token",
    }).encode("utf-8")
    result = _request_json(
        opener,
        token_data.get("token_uri") or TOKEN_URI,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=form,
        method="POST",
        timeout=int(cfg.get("timeout_seconds", DEFAULT_TIMEOUT)),
    )
    access = result.get("access_token")
    if not isinstance(access, str) or not access:
        raise ValueError("OAuth token refresh returned no access_token")
    return access


def _drive_escape(value):
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _find_child(opener, token, parent_id, name, mime_type=None, timeout=DEFAULT_TIMEOUT):
    clauses = [
        f"name = '{_drive_escape(name)}'",
        f"'{_drive_escape(parent_id)}' in parents",
        "trashed = false",
    ]
    if mime_type:
        clauses.append(f"mimeType = '{_drive_escape(mime_type)}'")
    query = urllib.parse.urlencode({
        "q": " and ".join(clauses),
        "fields": "files(id,name,size,md5Checksum,mimeType)",
        "pageSize": "10",
    })
    res = _request_json(
        opener,
        f"{DRIVE_FILES_URL}?{query}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    files = res.get("files") or []
    return files[0] if files else None


def _ensure_folder(opener, token, parent_id, name, timeout=DEFAULT_TIMEOUT):
    folder_mime = "application/vnd.google-apps.folder"
    existing = _find_child(opener, token, parent_id, name, mime_type=folder_mime, timeout=timeout)
    if existing:
        return existing["id"]
    payload = json.dumps({"name": name, "mimeType": folder_mime, "parents": [parent_id]}).encode("utf-8")
    created = _request_json(
        opener,
        f"{DRIVE_FILES_URL}?fields=id,name",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        data=payload,
        method="POST",
        timeout=timeout,
    )
    if not created.get("id"):
        raise ValueError("Failed to create Google Drive folder: " + name)
    return created["id"]


def _upload_resumable(opener, token, parent_id, local_path, remote_name, size, md5_hex, timeout=DEFAULT_TIMEOUT):
    existing = _find_child(opener, token, parent_id, remote_name, timeout=timeout)
    if existing and int(existing.get("size") or -1) == size and (existing.get("md5Checksum") or "").lower() == md5_hex:
        return existing

    if existing:
        init_url = f"{DRIVE_UPLOAD_URL}/{urllib.parse.quote(existing['id'])}?uploadType=resumable&fields=id,name,size,md5Checksum"
        init_method = "PATCH"
        meta = json.dumps({"name": remote_name}).encode("utf-8")
    else:
        init_url = f"{DRIVE_UPLOAD_URL}?uploadType=resumable&fields=id,name,size,md5Checksum"
        init_method = "POST"
        meta = json.dumps({"name": remote_name, "parents": [parent_id]}).encode("utf-8")

    init_req = urllib.request.Request(
        init_url,
        data=meta,
        method=init_method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
            "X-Upload-Content-Type": "application/octet-stream",
            "X-Upload-Content-Length": str(size),
        },
    )
    with opener.open(init_req, timeout=timeout) as resp:
        upload_uri = resp.headers.get("Location")
    if not upload_uri:
        raise ValueError("Google Drive resumable session missing Location header")

    if size == 0:
        put_req = urllib.request.Request(
            upload_uri, data=b"", method="PUT", headers={"Content-Length": "0"}
        )
        with opener.open(put_req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    else:
        result = None
        with Path(local_path).open("rb") as stream:
            offset = 0
            while offset < size:
                chunk = stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                end = offset + len(chunk) - 1
                put_req = urllib.request.Request(
                    upload_uri,
                    data=chunk,
                    method="PUT",
                    headers={
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {offset}-{end}/{size}",
                    },
                )
                try:
                    with opener.open(put_req, timeout=timeout) as resp:
                        body = resp.read().decode("utf-8")
                        if body:
                            result = json.loads(body)
                except urllib.error.HTTPError as exc:
                    if exc.code == 308:
                        offset += len(chunk)
                        continue
                    raise
                offset += len(chunk)

    if not isinstance(result, dict) or not result.get("id"):
        raise ValueError("Google Drive upload finished without file metadata")
    remote_size = int(result.get("size") or -1)
    remote_md5 = (result.get("md5Checksum") or "").lower()
    if remote_size != size or remote_md5 != md5_hex:
        raise ValueError(
            f"Google Drive upload verification mismatch: size={remote_size}/{size}, md5={remote_md5}/{md5_hex}"
        )
    return result


def _upload_via_cli(cfg, run_id, artifacts):
    gdrive_bin = cfg.get("cli_binary") or shutil.which("gdrive") or "gdrive"
    parent_id = cfg["folder_id"]
    run_folder_id = None
    search_proc = subprocess.run(
        [gdrive_bin, "readonly", "search", "--name-contains", run_id, "--parent-id", parent_id, "--json"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=int(cfg.get("timeout_seconds", DEFAULT_TIMEOUT)),
    )
    if search_proc.returncode == 0 and search_proc.stdout.strip().startswith("["):
        for item in json.loads(search_proc.stdout):
            if item.get("name") == run_id and item.get("mimeType") == "application/vnd.google-apps.folder":
                run_folder_id = item["id"]
                break
    if not run_folder_id:
        mk_proc = subprocess.run(
            [gdrive_bin, "mutate", "mkdir", run_id, "--parent", parent_id],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=int(cfg.get("timeout_seconds", DEFAULT_TIMEOUT)),
        )
        if mk_proc.returncode != 0:
            raise ValueError("gdrive mkdir failed: " + mk_proc.stderr.strip())
        search2 = subprocess.run(
            [gdrive_bin, "readonly", "search", "--name-contains", run_id, "--parent-id", parent_id, "--json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=int(cfg.get("timeout_seconds", DEFAULT_TIMEOUT)),
        )
        if search2.returncode == 0 and search2.stdout.strip().startswith("["):
            for item in json.loads(search2.stdout):
                if item.get("name") == run_id and item.get("mimeType") == "application/vnd.google-apps.folder":
                    run_folder_id = item["id"]
                    break
    if not run_folder_id:
        raise ValueError("Could not resolve Drive subfolder ID via gdrive CLI")

    uploaded = {}
    for local_path, size, sha256_hex, md5_hex in artifacts:
        up = subprocess.run(
            [gdrive_bin, "mutate", "upload", str(local_path), "--parent", run_folder_id],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=max(300, int(cfg.get("timeout_seconds", DEFAULT_TIMEOUT))),
        )
        if up.returncode != 0:
            raise ValueError(f"gdrive upload failed for {local_path.name}: {up.stderr.strip()}")
        ls_proc = subprocess.run(
            [gdrive_bin, "readonly", "ls", run_folder_id, "--json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=int(cfg.get("timeout_seconds", DEFAULT_TIMEOUT)),
        )
        match = None
        if ls_proc.returncode == 0 and ls_proc.stdout.strip().startswith("["):
            for item in json.loads(ls_proc.stdout):
                if item.get("name") == local_path.name:
                    match = item
        if not match:
            raise ValueError("Uploaded file missing in Drive listing: " + local_path.name)
        info_proc = subprocess.run(
            [gdrive_bin, "readonly", "info", match["id"], "--json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=int(cfg.get("timeout_seconds", DEFAULT_TIMEOUT)),
        )
        info = json.loads(info_proc.stdout) if info_proc.returncode == 0 else match
        r_size = int(info.get("size", -1))
        r_md5 = (info.get("md5Checksum") or "").lower()
        if r_size != size or r_md5 != md5_hex:
            raise ValueError(f"Drive CLI verification mismatch for {local_path.name}")
        uploaded[local_path.name] = {
            "drive_file_id": info["id"],
            "size": size,
            "sha256": sha256_hex,
            "md5": md5_hex,
        }
    return run_folder_id, uploaded


def upload_run_artifacts(run_dir, artifact_names, config_path=None):
    """Upload verified artifacts for a retained run to Google Drive.

    Returns receipt fields on success; raises on config/network/checksum error.
    """
    cfg = load_config(config_path)
    if cfg.get("enabled") is not True:
        raise ValueError("Google Drive offload is disabled in config")
    if not isinstance(cfg.get("folder_id"), str) or not cfg["folder_id"].strip():
        raise ValueError("Google Drive offload config missing folder_id")

    run_dir = Path(run_dir)
    artifacts = []
    for name in artifact_names:
        path = run_dir / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Missing artifact for Drive offload: " + name)
        size, sha256_hex, md5_hex = file_hashes(path)
        artifacts.append((path, size, sha256_hex, md5_hex))

    mode = cfg.get("mode", "oauth")
    if mode == "cli":
        run_folder_id, uploaded = _upload_via_cli(cfg, run_dir.name, artifacts)
    elif mode == "oauth":
        timeout = int(cfg.get("timeout_seconds", DEFAULT_TIMEOUT))
        opener = _build_opener(cfg.get("proxy"))
        token = _refresh_access_token(cfg, opener)
        run_folder_id = _ensure_folder(opener, token, cfg["folder_id"].strip(), run_dir.name, timeout=timeout)
        uploaded = {}
        for path, size, sha256_hex, md5_hex in artifacts:
            meta = _upload_resumable(opener, token, run_folder_id, path, path.name, size, md5_hex, timeout=timeout)
            uploaded[path.name] = {
                "drive_file_id": meta["id"],
                "size": size,
                "sha256": sha256_hex,
                "md5": md5_hex,
            }
    else:
        raise ValueError("Unsupported Google Drive offload mode: " + str(mode))

    return {
        "schema": OFFLOAD_SCHEMA,
        "run_id": run_dir.name,
        "drive_parent_folder_id": cfg["folder_id"].strip(),
        "drive_folder_id": run_folder_id,
        "uploaded": uploaded,
        "utc": datetime.now(timezone.utc).isoformat(),
    }


def download_file(file_id, dest_path, expected_sha256=None, expected_bytes=None, config_path=None):
    """Download a Drive file to dest_path and verify SHA-256 / byte length."""
    cfg = load_config(config_path)
    if not isinstance(file_id, str) or not file_id.strip():
        raise ValueError("Missing Drive file_id for restore")
    dest_path = Path(dest_path)
    mode = cfg.get("mode", "oauth")
    if mode == "cli":
        gdrive_bin = cfg.get("cli_binary") or shutil.which("gdrive") or "gdrive"
        proc = subprocess.run(
            [gdrive_bin, "readonly", "download", file_id.strip(), "--out", str(dest_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=max(300, int(cfg.get("timeout_seconds", DEFAULT_TIMEOUT))),
        )
        if proc.returncode != 0:
            raise ValueError("gdrive download failed: " + proc.stderr.strip())
    elif mode == "oauth":
        timeout = int(cfg.get("timeout_seconds", DEFAULT_TIMEOUT))
        opener = _build_opener(cfg.get("proxy"))
        token = _refresh_access_token(cfg, opener)
        url = f"{DRIVE_FILES_URL}/{urllib.parse.quote(file_id.strip())}?alt=media"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        tmp = dest_path.with_name(dest_path.name + "." + uuid.uuid4().hex + ".dl")
        try:
            with opener.open(req, timeout=max(300, timeout)) as resp, tmp.open("wb") as out:
                for block in iter(lambda: resp.read(1024 * 1024), b""):
                    out.write(block)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, dest_path)
        finally:
            if tmp.exists():
                tmp.unlink()
    else:
        raise ValueError("Unsupported Google Drive offload mode: " + str(mode))

    size, sha256_hex, _ = file_hashes(dest_path)
    if expected_bytes is not None and size != int(expected_bytes):
        raise ValueError(f"Downloaded Drive file size mismatch: {size} != {expected_bytes}")
    if expected_sha256 is not None and sha256_hex != expected_sha256:
        raise ValueError(f"Downloaded Drive file SHA-256 mismatch: {sha256_hex} != {expected_sha256}")
    return {"size": size, "sha256": sha256_hex}


def fetch_backup_from_receipt(run_dir, doc, dest_path, config_path=None):
    """Default fetcher passed to retention.restore()/rehydrate()."""
    offload = doc.get("raw_backup_offload")
    if not isinstance(offload, dict) or not offload.get("evidence_file"):
        raise ValueError("Missing raw_backup_offload pointer in retention.json")
    proof = json.loads((Path(run_dir) / offload["evidence_file"]).read_text(encoding="utf-8"))
    return download_file(
        proof["drive_file_id"],
        dest_path,
        expected_sha256=proof["raw_backup_sha256"],
        expected_bytes=proof["raw_backup_bytes"],
        config_path=config_path,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    check = sub.add_parser("check-config")
    check.add_argument("--config")
    args = parser.parse_args()
    if args.cmd == "check-config":
        cfg = load_config(args.config)
        safe = {k: v for k, v in cfg.items() if k != "token_file"}
        print(json.dumps(safe, ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
