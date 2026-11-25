#!/usr/bin/env python3
"""Carousel Studio: local setup, content-addressed assets, snapshots and QA.

Python 3.10+, standard library only. Does not render images or call cloud APIs.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import sys
import tempfile
import zlib
from urllib.parse import urlsplit
from datetime import datetime, timezone

VERSION = "1.0.0"
KINDS = ("photo", "icon", "stock", "graphic", "reference")
DIRECTORIES = (
    "brands", "styles", "projects", "assets/originals", "assets/derived",
    "assets/references", "registry", "registry/backups", "inbox", "logs",
)
UNKNOWN_RIGHTS = {"", "unknown", "nieznane", "nieustalone", "pending", "tbd"}


class StudioError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fail(message):
    raise StudioError(message)


def valid_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", value):
        fail("ID musi mieć 1–64 małe litery ASCII, cyfry lub łączniki.")
    if "--" in value or value.endswith("-"):
        fail("ID nie może zawierać podwójnych łączników ani kończyć się łącznikiem.")
    if value.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?:com|lpt)[1-9]", value):
        fail("ID jest zarezerwowaną nazwą systemową.")
    return value


def is_link(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def reject_links(path):
    # Check lexical ancestors before resolve() could hide a junction or symlink.
    for candidate in reversed((path, *path.parents)):
        if is_link(candidate):
            fail(f"Odmowa dostępu przez dowiązanie / junction: {candidate}")


def root_path(value, create=False):
    path = Path(os.path.abspath(os.path.expanduser(value)))
    reject_links(path)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        fail(f"Nie istnieje katalog roboczy: {path}")
    return path


def managed(root, relative):
    relative = str(relative).replace("\\", "/")
    parts = relative.split("/")
    if not relative or relative.startswith("/") or any(p in {"", ".", ".."} for p in parts) or ":" in relative:
        fail(f"Nieprawidłowa ścieżka względna: {relative!r}")
    result = root.joinpath(*parts)
    reject_links(result)
    if os.path.commonpath([str(root), str(result)]) != str(root):
        fail("Ścieżka wykracza poza katalog roboczy.")
    return result


def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def read_json(path):
    reject_links(path)
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            return json.load(stream)
    except (OSError, ValueError) as exc:
        fail(f"Nie można odczytać JSON {path}: {exc}")


def atomic_json(path, value, overwrite=True):
    reject_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        fail(f"Plik już istnieje: {path}")
    handle, temporary = tempfile.mkstemp(prefix=".carousel-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            # Exclusive destination avoids replacing a file created between checks.
            with path.open("xb") as target, open(temporary, "rb") as source:
                shutil.copyfileobj(source, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def locked(root):
    path = managed(root, ".carousel.lock")
    try:
        stream = path.open("x", encoding="utf-8")
    except FileExistsError:
        fail("Katalog jest zablokowany (.carousel.lock). Zakończ drugi proces; po awarii sprawdź PID w pliku przed ręcznym usunięciem blokady.")
    try:
        with stream:
            json.dump({"pid": os.getpid(), "started_at": now()}, stream)
            stream.flush()
            yield
    finally:
        path.unlink(missing_ok=True)


def event(root, action, **details):
    path = managed(root, "registry/events.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps({"at": now(), "action": action, **details}, ensure_ascii=False) + "\n")


def registry(root, name="assets"):
    data = read_json(managed(root, f"registry/{name}.json"))
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get(name), list):
        fail(f"Nieprawidłowy rejestr {name}.")
    return data


def cmd_init(args):
    root = root_path(args.root, create=True)
    package = Path(__file__).resolve().parents[1]
    templates = package / "assets" / "templates" / "workspace"
    with locked(root):
        for relative in DIRECTORIES:
            managed(root, relative).mkdir(parents=True, exist_ok=True)
        created, preserved = [], []
        if templates.is_dir():
            for source in sorted(templates.rglob("*")):
                reject_links(source)
                if not source.is_file():
                    continue
                relative = source.relative_to(templates).as_posix()
                target = managed(root, relative)
                if target.exists():
                    preserved.append(relative)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open("rb") as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                created.append(relative)
        defaults = {
            "config.json": {"schema_version": 1, "studio_version": VERSION,
                            "root_hint": str(root), "language": "pl", "originals_policy": "immutable",
                            "near_duplicate_detection": "manual", "created_at": now()},
            "registry/assets.json": {"schema_version": 1, "assets": []},
            "registry/references.json": {"schema_version": 1, "references": []},
        }
        for relative, data in defaults.items():
            target = managed(root, relative)
            if not target.exists():
                atomic_json(target, data, overwrite=False)
                created.append(relative)
        # Never replace a pre-existing file or convert drafts into approved records.
        event(root, "init", created=created, preserved=preserved, version=VERSION)
    return {"status": "ok", "root": str(root), "created": created, "preserved": preserved,
            "next": "Przeprowadź onboarding marki i stylu; szablony draft wymagają uzupełnienia i akceptacji."}


def cmd_doctor(args):
    root = root_path(args.root)
    problems = []
    for relative in DIRECTORIES:
        try:
            if not managed(root, relative).is_dir():
                problems.append(f"Brak katalogu: {relative}")
        except StudioError as exc:
            problems.append(str(exc))
    for name in ("assets", "references"):
        try:
            registry(root, name)
        except StudioError as exc:
            problems.append(str(exc))
    try:
        config = read_json(managed(root, "config.json"))
        if not isinstance(config, dict) or config.get("schema_version") != 1:
            problems.append("Nieprawidłowy config.json")
    except StudioError as exc:
        problems.append(str(exc))
    try:
        with locked(root):
            probe = managed(root, "registry/.doctor-probe")
            if probe.exists():
                fail("Istnieje plik testu .doctor-probe; nie zostanie nadpisany.")
            with probe.open("xb") as stream:
                stream.write(b"carousel-studio\n")
            if probe.read_bytes() != b"carousel-studio\n":
                fail("Nieudany test odczytu pliku.")
            probe.unlink()
    except (StudioError, OSError) as exc:
        problems.append(str(exc))
    return {"status": "fail" if problems else "ok", "python": sys.version.split()[0],
            "root": str(root), "issues": problems,
            "capabilities": {"local_files": not problems, "cloud_ai": "not_tested", "canva": "not_tested"}}


def cmd_import(args):
    root = root_path(args.root)
    source = Path(os.path.abspath(os.path.expanduser(args.file)))
    reject_links(source)
    if not source.is_file():
        fail(f"Brak pliku źródłowego: {source}")
    if source.stat().st_size == 0:
        fail("Nie można importować pustego pliku.")
    brand = valid_id(args.brand) if args.brand else None
    with locked(root):
        data = registry(root)
        parent = None
        parent_id = getattr(args, "parent", None)
        if parent_id:
            parent = next((a for a in data["assets"] if a.get("id") == parent_id), None)
            if parent is None:
                fail("Nie znaleziono zasobu źródłowego --parent.")
            parent_path = managed(root, parent["canonical_path"])
            if not parent_path.is_file() or digest(parent_path) != parent["sha256"]:
                fail("Oryginał źródłowy nie przeszedł weryfikacji integralności.")
            if not args.recipe.strip():
                fail("Derywat wymaga opisu --recipe.")
            if args.rights == "inherited":
                args.rights = parent.get("rights", "unknown")
        sha = digest(source)
        asset_id = "asset-" + sha
        if parent_id == asset_id:
            fail("Derywat ma identyczne bajty jak rodzic. Użyj istniejącego asset_id zamiast tworzyć kopię.")
        matches = [item for item in data["assets"] if item.get("sha256") == sha]
        if len(matches) > 1:
            fail("Rejestr zawiera zduplikowane sumy SHA256; napraw go przed importem.")
        occurrence = {"imported_at": now(), "original_name": source.name, "source": args.source,
                      "rights": args.rights, "kind": args.kind, "brand": brand,
                      "tags": [tag.strip() for tag in args.tags.split(",") if tag.strip()]}
        if parent:
            occurrence.update(parent_asset_id=parent_id, recipe=args.recipe)
        if matches:
            asset = matches[0]
            canonical = managed(root, asset["canonical_path"])
            if not canonical.is_file() or digest(canonical) != sha:
                fail("Oryginał w bibliotece nie zgadza się z rejestrem; import wstrzymany.")
            asset.setdefault("occurrences", []).append(occurrence)
            if asset.get("rights", "unknown").strip().lower() in UNKNOWN_RIGHTS and args.rights.strip().lower() not in UNKNOWN_RIGHTS:
                asset["rights"] = args.rights
            duplicate = True
        else:
            suffix = source.suffix.lower()
            if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
                suffix = ".bin"
            storage = "derived" if parent else "originals"
            relative = f"assets/{storage}/{sha}{suffix}"
            canonical = managed(root, relative)
            canonical.parent.mkdir(parents=True, exist_ok=True)
            if canonical.exists():
                if digest(canonical) != sha:
                    fail("Kolizja pliku biblioteki: istniejący oryginał ma inną sumę.")
            else:
                handle, temporary = tempfile.mkstemp(prefix=".import-", dir=canonical.parent)
                try:
                    with os.fdopen(handle, "wb") as outgoing, source.open("rb") as incoming:
                        shutil.copyfileobj(incoming, outgoing)
                        outgoing.flush()
                        os.fsync(outgoing.fileno())
                    if digest(Path(temporary)) != sha or digest(source) != sha:
                        fail("Plik źródłowy zmienił się w trakcie importu.")
                    # lock serializes legitimate Studio writers; exclusive open still protects originals.
                    with canonical.open("xb") as outgoing, open(temporary, "rb") as incoming:
                        shutil.copyfileobj(incoming, outgoing)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            asset = {"id": asset_id, "sha256": sha, "canonical_path": relative,
                     "size_bytes": canonical.stat().st_size, "kind": args.kind,
                     "rights": args.rights, "created_at": now(), "occurrences": [occurrence],
                     "derived": []}
            if parent:
                asset.update(parent_asset_id=parent_id, recipe=args.recipe)
            data["assets"].append(asset)
            duplicate = False
        if parent and not any(d.get("asset_id") == asset["id"] for d in parent.setdefault("derived", [])):
            parent["derived"].append({"asset_id": asset["id"], "recipe": args.recipe, "registered_at": now()})
        atomic_json(managed(root, "registry/assets.json"), data)
        if args.kind == "reference":
            refs = registry(root, "references")
            reference_id = "ref-" + hashlib.sha256((asset_id + "\n" + args.source).encode()).hexdigest()
            record = {"id": reference_id, "asset_id": asset_id, "source": args.source,
                      "title": source.stem, "rights": args.rights, "tags": occurrence["tags"],
                      "added_at": now(), "usage": "inspiration_only"}
            old = next((r for r in refs["references"] if r.get("id") == reference_id), None)
            if old is None:
                refs["references"].append(record)
            atomic_json(managed(root, "registry/references.json"), refs)
        event(root, "import_asset", asset_id=asset["id"], duplicate=duplicate, kind=args.kind)
    return {"status": "ok", "asset_id": asset["id"], "canonical_path": asset["canonical_path"],
            "duplicate": duplicate, "sha256": sha, "rights": asset["rights"]}


def cmd_derived(args):
    args.kind = "graphic"
    args.source = f"derived from {args.parent}"
    args.brand = None
    args.tags = "derived"
    return cmd_import(args)


def approved_document(root, kind, identifier):
    identifier = valid_id(identifier)
    relative = f"{kind}s/{identifier}/{kind}.json"
    path = managed(root, relative)
    data = read_json(path)
    if not isinstance(data, dict) or data.get("id") != identifier or data.get("status") != "approved":
        fail(f"{relative} musi zawierać zgodne id oraz status approved po onboardingu.")
    if not data.get("name"):
        fail(f"Brak name w {relative}.")
    if kind == "brand":
        if not isinstance(data.get("colors"), list) or not data["colors"] or not all(isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in data["colors"]):
            fail("Marka musi mieć listę kolorów HEX #RRGGBB.")
        fonts = data.get("fonts", {})
        if not isinstance(fonts, dict) or not fonts.get("heading") or not fonts.get("body") or not data.get("tone"):
            fail("Uzupełnij fonts.heading, fonts.body i tone marki.")
    else:
        canvas = data.get("canvas", {})
        if not isinstance(canvas, dict) or any(type(canvas.get(k)) is not int or not 100 <= canvas[k] <= 20000 for k in ("width", "height")):
            fail("Styl musi mieć canvas.width i canvas.height od 100 do 20000.")
        margin = data.get("safe_margin")
        if type(margin) is not int or margin < 0 or margin * 2 >= min(canvas["width"], canvas["height"]):
            fail("Nieprawidłowy safe_margin stylu.")
        if not data.get("layout_rules"):
            fail("Uzupełnij layout_rules stylu.")
    return data, digest(path), relative


def write_snapshot(root, project, brand_id, style_id, overwrite=False):
    brand, brand_hash, brand_path = approved_document(root, "brand", brand_id)
    style, style_hash, style_path = approved_document(root, "style", style_id)
    base = f"projects/{project}/config"
    for name, data in (("brand.json", brand), ("style.json", style)):
        atomic_json(managed(root, f"{base}/{name}"), data, overwrite=overwrite)
    # Hash the actual copied snapshots, since JSON serialization can normalize whitespace.
    result = {"created_at": now(), "brand_id": brand_id, "style_id": style_id,
              "brand_source": brand_path, "style_source": style_path,
              "brand_source_sha256": brand_hash, "style_source_sha256": style_hash,
              "brand_snapshot_sha256": digest(managed(root, f"{base}/brand.json")),
              "style_snapshot_sha256": digest(managed(root, f"{base}/style.json"))}
    atomic_json(managed(root, f"{base}/snapshot.json"), result, overwrite=overwrite)
    return result


def cmd_new_project(args):
    root = root_path(args.root)
    project, brand_id, style_id = map(valid_id, (args.id, args.brand, args.style))
    if not 2 <= args.slides <= 30:
        fail("Liczba slajdów musi wynosić 2–30.")
    with locked(root):
        # Validate before creating a project, so onboarding errors leave no half project.
        approved_document(root, "brand", brand_id)
        approved_document(root, "style", style_id)
        base = managed(root, f"projects/{project}")
        if base.exists():
            fail("Projekt o tym ID już istnieje; wybierz nowe ID.")
        base.mkdir(parents=True)
        for directory in ("config", "working", "exports", "qa", "history"):
            managed(root, f"projects/{project}/{directory}").mkdir()
        atomic_json(base / "project.json", {"schema_version": 1, "id": project,
                    "brand_id": brand_id, "style_id": style_id, "created_at": now(), "status": "draft"}, overwrite=False)
        atomic_json(base / "brief.json", {"status": "draft", "goal": "", "audience": "", "key_message": "",
                    "cta": "", "slide_count": args.slides, "channels": [], "required_facts": []}, overwrite=False)
        slides = [{"number": number, "role": "hook" if number == 1 else "cta" if number == args.slides else "content",
                   "headline": "", "body": "", "asset_ids": [], "alt_text": ""}
                  for number in range(1, args.slides + 1)]
        atomic_json(base / "slides.json", slides, overwrite=False)
        atomic_json(base / "export-manifest.json", {"status": "draft", "design_url": None, "files": []}, overwrite=False)
        atomic_json(base / "qa" / "manual-review.json", {"visual_review": "pending", "reviewed_files": [],
                    "reviewed_sha256": {}, "reviewer": "",
                    "checks": {"readability": "pending", "safe_margins": "pending", "photo_fidelity": "pending",
                               "brand_consistency": "pending", "facts_and_spelling": "pending"},
                    "notes": "", "reviewed_at": None}, overwrite=False)
        snapshot = write_snapshot(root, project, brand_id, style_id)
        event(root, "new_project", project=project, brand_id=brand_id, style_id=style_id)
    return {"status": "ok", "project": project, "path": str(base), "snapshot": snapshot}


def cmd_snapshot(args):
    root = root_path(args.root)
    project = valid_id(args.project)
    with locked(root):
        config = read_json(managed(root, f"projects/{project}/project.json"))
        snapshot_path = managed(root, f"projects/{project}/config/snapshot.json")
        if snapshot_path.exists():
            fail("Projekt ma już przypięte migawki. Dla nowej wersji stylu utwórz nowy projekt; istniejąca migawka pozostaje bez zmian.")
        result = write_snapshot(root, project, config["brand_id"], config["style_id"])
        event(root, "snapshot", project=project)
    return {"status": "ok", "snapshot": result}


def asset_issues(root, assets):
    issues = []
    ids, hashes, paths = set(), set(), set()
    for index, asset in enumerate(assets):
        label = asset.get("id", f"record-{index}") if isinstance(asset, dict) else f"record-{index}"
        try:
            if not isinstance(asset, dict):
                fail("rekord nie jest obiektem")
            sha = asset.get("sha256", "")
            if not re.fullmatch(r"[a-f0-9]{64}", sha) or asset.get("id") != "asset-" + sha:
                fail("nieprawidłowe id / sha256")
            if asset["id"] in ids or sha in hashes or asset.get("canonical_path") in paths:
                fail("duplikat id / sumy / ścieżki w rejestrze")
            ids.add(asset["id"]); hashes.add(sha); paths.add(asset.get("canonical_path"))
            relative = asset.get("canonical_path", "")
            if not relative.startswith(("assets/originals/", "assets/derived/")):
                fail("zasób poza assets/originals lub assets/derived")
            path = managed(root, relative)
            if not path.is_file():
                fail("brak oryginału")
            if digest(path) != sha:
                fail("zmienione bajty oryginału")
            if path.stat().st_size != asset.get("size_bytes"):
                fail("inna wielkość oryginału")
        except (StudioError, OSError, TypeError) as exc:
            issues.append(f"{label}: {exc}")
    by_id = {a.get("id"): a for a in assets if isinstance(a, dict)}
    for asset in by_id.values():
        if "parent_asset_id" in asset:
            if asset["parent_asset_id"] not in by_id or asset["parent_asset_id"] == asset.get("id"):
                issues.append(f"{asset.get('id')}: brak rodzica lub odwołanie do siebie")
            if not asset.get("recipe"):
                issues.append(f"{asset.get('id')}: brak recipe derywatu")
    return issues


def cmd_verify(args):
    root = root_path(args.root)
    with locked(root):
        assets = registry(root)["assets"]
        issues = asset_issues(root, assets)
        refs = registry(root, "references")["references"]
        ids = {a.get("id") for a in assets if isinstance(a, dict)}
        for ref in refs:
            if not isinstance(ref, dict):
                issues.append("Referencja nie jest obiektem JSON.")
            elif ref.get("asset_id") is None:
                source = ref.get("source", "")
                parsed = urlsplit(source) if isinstance(source, str) else None
                if not ref.get("title") or parsed is None or parsed.scheme not in ("http", "https") or not parsed.netloc:
                    issues.append("Referencja bez pliku wymaga title i source jako URL http/https.")
            elif ref.get("asset_id") not in ids:
                issues.append("Referencja wskazuje brakujący zasób.")
        registered = {a.get("canonical_path") for a in assets if isinstance(a, dict)}
        unregistered = []
        for folder in ("assets/originals", "assets/derived"):
            for path in managed(root, folder).rglob("*"):
                reject_links(path)
                if path.is_file() and path.relative_to(root).as_posix() not in registered:
                    unregistered.append(path.relative_to(root).as_posix())
        if unregistered:
            issues.append("Niezarejestrowane pliki w originals: " + ", ".join(unregistered))
    return {"status": "fail" if issues else "ok", "asset_count": len(assets), "issues": issues,
            "scope": "SHA256 oryginałów i spójność odwołań. Brak automatycznej detekcji podobnych wizualnie zdjęć."}


def image_dimensions(path):
    with path.open("rb") as stream:
        header = stream.read(24)
        if len(header) >= 24 and header[:8] == b"\x89PNG\r\n\x1a\n" and header[12:16] == b"IHDR":
            stream.seek(8)
            width = height = None
            payloads = []
            ended = False
            chunks = 0
            while True:
                chunk_header = stream.read(8)
                if len(chunk_header) != 8:
                    fail("Ucięty PNG: brak pełnego nagłówka chunk.")
                length, kind = struct.unpack(">I4s", chunk_header)
                if length > 128 * 1024 * 1024:
                    fail("Chunk PNG przekracza limit walidacji 128 MiB.")
                data = stream.read(length)
                checksum = stream.read(4)
                if len(data) != length or len(checksum) != 4 or zlib.crc32(kind + data) & 0xFFFFFFFF != struct.unpack(">I", checksum)[0]:
                    fail("Uszkodzony PNG: rozmiar lub CRC chunk.")
                chunks += 1
                if chunks == 1 and kind != b"IHDR":
                    fail("Pierwszy chunk PNG musi być IHDR.")
                if kind == b"IHDR":
                    if width is not None or len(data) != 13:
                        fail("Nieprawidłowy IHDR PNG.")
                    width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", data)
                    allowed_depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
                    if not width or not height or depth not in allowed_depths.get(color, ()) or compression != 0 or filtering != 0:
                        fail("Nieprawidłowe parametry PNG.")
                    if interlace != 0:
                        fail("QA wymaga PNG bez przeplotu; wyeksportuj bez interlace.")
                elif kind == b"IDAT":
                    payloads.append(data)
                elif kind == b"IEND":
                    if data:
                        fail("Nieprawidłowy IEND PNG.")
                    ended = True
                    if stream.read(1):
                        fail("Dodatkowe dane po końcu PNG.")
                    break
            if not ended or not payloads or width is None:
                fail("Niekompletny PNG.")
            channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
            row_length = (width * channels * depth + 7) // 8
            expected = (row_length + 1) * height
            if expected > 256 * 1024 * 1024:
                fail("Rozpakowany PNG przekracza limit walidacji 256 MiB.")
            try:
                decompressor = zlib.decompressobj()
                decoded = decompressor.decompress(b"".join(payloads), expected + 1)
                if len(decoded) != expected or not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
                    fail("Nieprawidłowy strumień pikseli PNG.")
                if any(decoded[offset] > 4 for offset in range(0, len(decoded), row_length + 1)):
                    fail("Nieprawidłowy filtr wiersza PNG.")
            except zlib.error as exc:
                fail(f"Uszkodzona kompresja PNG: {exc}")
            return width, height
        if header[:2] == b"\xff\xd8":
            stream.seek(-2, 2)
            if stream.read(2) != b"\xff\xd9":
                fail("Ucięty JPEG: brak znacznika końcowego.")
            stream.seek(2)
            while True:
                byte = stream.read(1)
                if not byte:
                    break
                if byte != b"\xff":
                    continue
                while byte == b"\xff":
                    byte = stream.read(1)
                if not byte:
                    break
                marker = byte[0]
                if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                    continue
                length_data = stream.read(2)
                if len(length_data) != 2:
                    break
                length = struct.unpack(">H", length_data)[0]
                if length < 2:
                    break
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    data = stream.read(5)
                    if len(data) == 5:
                        height, width = struct.unpack(">HH", data[1:5])
                        return width, height
                    break
                if marker == 0xDA:
                    break
                stream.seek(length - 2, 1)
    fail("Nieobsługiwany lub uszkodzony nagłówek obrazu; QA automatyczne obsługuje PNG/JPEG.")


def cmd_qa(args):
    root = root_path(args.root)
    project = valid_id(args.project)
    base_relative = f"projects/{project}"
    base = managed(root, base_relative)
    if not base.is_dir():
        fail("Projekt nie istnieje.")
    issues, warnings = [], []

    def load(relative, default=None):
        try:
            return read_json(managed(root, f"{base_relative}/{relative}"))
        except StudioError as exc:
            issues.append(str(exc))
            return default

    with locked(root):
        project_data = load("project.json", {})
        brief = load("brief.json", {})
        slides = load("slides.json", [])
        manifest = load("export-manifest.json", {})
        manual = load("qa/manual-review.json", {})
        brand = load("config/brand.json", {})
        style = load("config/style.json", {})
        snapshot = load("config/snapshot.json", {})
        # Validate types before inspecting nested objects; malformed content produces FAIL.
        objects = {"project": project_data, "brief": brief, "manifest": manifest,
                   "manual": manual, "brand": brand, "style": style, "snapshot": snapshot}
        for name, value in list(objects.items()):
            if not isinstance(value, dict):
                issues.append(f"{name} musi być obiektem JSON.")
                objects[name] = {}
        project_data, brief, manifest, manual, brand, style, snapshot = (objects[k] for k in objects)
        if not isinstance(slides, list):
            issues.append("slides.json musi być tablicą.")
            slides = []
        if project_data.get("id") != project:
            issues.append("Niezgodne ID projektu.")
        for name, document in (("brand", brand), ("style", style)):
            if document.get("status") != "approved":
                issues.append(f"Migawka {name} nie ma statusu approved.")
            expected = snapshot.get(f"{name}_snapshot_sha256")
            path = managed(root, f"{base_relative}/config/{name}.json")
            if not expected or not path.is_file() or digest(path) != expected:
                issues.append(f"Migawka {name} zmieniona lub brak jej sumy SHA256.")
            if snapshot.get(f"{name}_id") != project_data.get(f"{name}_id") or document.get("id") != project_data.get(f"{name}_id"):
                issues.append(f"Niezgodne ID migawki {name}.")
        if brief.get("status") != "approved":
            issues.append("Brief wymaga statusu approved.")
        for field in ("goal", "audience", "key_message", "cta"):
            if not isinstance(brief.get(field), str) or not brief[field].strip():
                issues.append(f"Brak treści brief.{field}.")
        if not isinstance(brief.get("channels"), list) or not brief["channels"]:
            issues.append("Brak kanału publikacji w brief.channels.")
        count = brief.get("slide_count")
        if type(count) is not int or not 2 <= count <= 30 or len(slides) != count:
            issues.append("Liczba slajdów nie zgadza się z briefem (2–30).")
        if not slides or not isinstance(slides[0], dict) or slides[0].get("role") != "hook":
            issues.append("Pierwszy slajd musi mieć role hook.")
        if not slides or not isinstance(slides[-1], dict) or slides[-1].get("role") != "cta":
            issues.append("Ostatni slajd musi mieć role cta.")
        used_assets = set()
        logo_ids = brand.get("logo_asset_ids", [])
        if isinstance(logo_ids, list) and all(isinstance(i, str) for i in logo_ids):
            used_assets.update(logo_ids)
        else:
            issues.append("brand.logo_asset_ids musi być tablicą ID.")
        fonts = brand.get("fonts", {})
        font_ids = fonts.get("asset_ids", []) if isinstance(fonts, dict) else []
        if isinstance(font_ids, list) and all(isinstance(i, str) for i in font_ids):
            used_assets.update(font_ids)
        else:
            issues.append("brand.fonts.asset_ids musi być tablicą ID.")
        for number, slide in enumerate(slides, 1):
            if not isinstance(slide, dict):
                issues.append(f"Slajd {number} nie jest obiektem.")
                continue
            if type(slide.get("number")) is not int or slide["number"] != number:
                issues.append(f"Nieprawidłowy numer slajdu {number}.")
            for field in ("headline", "alt_text"):
                if not isinstance(slide.get(field), str) or not slide[field].strip():
                    issues.append(f"Brak {field} slajdu {number}.")
            if not isinstance(slide.get("body", ""), str):
                issues.append(f"body slajdu {number} musi być tekstem.")
            asset_ids = slide.get("asset_ids", [])
            if not isinstance(asset_ids, list) or not all(isinstance(i, str) for i in asset_ids):
                issues.append(f"asset_ids slajdu {number} musi być tablicą ID.")
            else:
                used_assets.update(asset_ids)
        try:
            assets = registry(root)["assets"]
            issues.extend(asset_issues(root, assets))
            by_id = {a["id"]: a for a in assets if isinstance(a, dict) and "id" in a}
            # A derivative cannot hide an unknown upstream licence.
            queue = list(used_assets)
            while queue:
                candidate = by_id.get(queue.pop())
                if candidate is not None and candidate.get("parent_asset_id"):
                    parent_id = candidate["parent_asset_id"]
                    if parent_id not in used_assets:
                        used_assets.add(parent_id)
                        queue.append(parent_id)
            for asset_id in sorted(used_assets):
                asset = by_id.get(asset_id)
                if asset is None:
                    issues.append(f"Brak zasobu {asset_id}.")
                elif str(asset.get("rights", "")).strip().lower() in UNKNOWN_RIGHTS:
                    issues.append(f"Nieustalone prawa do zasobu {asset_id}.")
        except StudioError as exc:
            issues.append(str(exc))
        if manifest.get("status") != "ready":
            issues.append("export-manifest.json wymaga statusu ready.")
        files = manifest.get("files", [])
        if not isinstance(files, list):
            issues.append("manifest.files musi być tablicą.")
            files = []
        export_paths, covered = set(), set()
        canvas = style.get("canvas", {})
        if not isinstance(canvas, dict):
            canvas = {}
        for exported in files:
            try:
                if not isinstance(exported, dict):
                    fail("Rekord eksportu musi być obiektem.")
                relative = exported.get("path", "")
                if not isinstance(relative, str) or not relative.startswith("exports/"):
                    fail("Eksport musi znajdować się w projekcie w exports/.")
                if relative in export_paths:
                    fail("Duplikat ścieżki eksportu.")
                export_paths.add(relative)
                path = managed(root, f"{base_relative}/{relative}")
                if not path.is_file() or path.stat().st_size == 0:
                    fail("Brak lub pusty eksport.")
                number = exported.get("slide")
                if type(number) is not int or not 1 <= number <= len(slides):
                    fail("Nieprawidłowy numer slajdu eksportu.")
                covered.add(number)
                if exported.get("sha256") != digest(path):
                    fail("Suma SHA256 eksportu nie zgadza się z manifestem.")
                width, height = image_dimensions(path)
                if (width, height) != (canvas.get("width"), canvas.get("height")):
                    fail("Wymiary eksportu nie zgadzają się z przypiętym stylem.")
                if (width, height) != (exported.get("width"), exported.get("height")):
                    fail("Wymiary manifestu nie zgadzają się z rzeczywistym plikiem.")
            except (StudioError, OSError, TypeError, ValueError) as exc:
                issues.append(f"Eksport {exported.get('path', '?') if isinstance(exported, dict) else '?'}: {exc}")
        if covered != set(range(1, len(slides) + 1)) or not files:
            issues.append("Nie każdy slajd ma eksport PNG/JPEG.")
        checks = manual.get("checks", {})
        required_checks = ("readability", "safe_margins", "photo_fidelity", "brand_consistency", "facts_and_spelling")
        if manual.get("visual_review") != "passed" or not isinstance(checks, dict) or any(checks.get(k) != "passed" for k in required_checks):
            issues.append("Wymagana rzeczywista ocena wizualna i redakcyjna: wszystkie pola checks oraz visual_review muszą mieć passed.")
        reviewed = manual.get("reviewed_files", [])
        if not isinstance(reviewed, list) or not all(isinstance(item, str) for item in reviewed) or not export_paths.issubset(set(reviewed)):
            issues.append("Lista reviewed_files nie obejmuje wszystkich eksportów.")
        if not manual.get("reviewed_at"):
            issues.append("Brak daty rzeczywistej oceny reviewed_at.")
        if not isinstance(manual.get("reviewer"), str) or not manual["reviewer"].strip():
            issues.append("Brak reviewer rzeczywistej oceny wizualnej.")
        reviewed_hashes = manual.get("reviewed_sha256", {})
        if not isinstance(reviewed_hashes, dict):
            reviewed_hashes = {}
        for relative in export_paths:
            try:
                path = managed(root, f"{base_relative}/{relative}")
                if not path.is_file() or reviewed_hashes.get(relative) != digest(path):
                    issues.append(f"Nieaktualna lub brakująca ocena wizualna SHA256: {relative}.")
            except (StudioError, OSError) as exc:
                issues.append(str(exc))
        warnings.append("QA automatyczne nie ogląda kompozycji ani nie potwierdza prawdziwości deklaracji praw. Ocena manual-review musi opierać się na otwartych eksportach i źródłach.")
        report = {"schema_version": 1, "project": project, "checked_at": now(),
                  "result": "FAIL" if issues else "PASS", "issues": issues, "warnings": warnings,
                  "export_count": len(files), "asset_ids": sorted(used_assets),
                  "checks": {"automatic": "failed" if issues else "passed", "visual_review": manual.get("visual_review", "pending")}}
        atomic_json(managed(root, f"{base_relative}/qa/report.json"), report)
        event(root, "qa", project=project, result=report["result"], issues=len(issues))
    return {"status": "fail" if issues else "ok", "report_path": str(base / "qa" / "report.json"), **report}


def parser():
    cli = argparse.ArgumentParser(description="Carousel Studio — lokalne narzędzia, bez usług sieciowych.")
    cli.add_argument("--version", action="version", version=VERSION)
    commands = cli.add_subparsers(dest="command", required=True)
    for name, function, help_text in (
        ("init", cmd_init, "Utwórz strukturę bez nadpisywania istniejących plików."),
        ("doctor", cmd_doctor, "Sprawdź katalogi, rejestry i odczyt/zapis."),
        ("import-asset", cmd_import, "Importuj oryginał; deduplikacja SHA256."),
        ("register-derived", cmd_derived, "Zarejestruj nowy plik z rodzicem i opisem przekształcenia."),
        ("new-project", cmd_new_project, "Utwórz projekt z przypiętą marką i stylem."),
        ("snapshot-style", cmd_snapshot, "Przypnij konfigurację w starszym projekcie bez migawki."),
        ("verify", cmd_verify, "Sprawdź integralność biblioteki oryginałów."),
        ("qa", cmd_qa, "Zapisz raport QA projektu; FAIL zwraca kod 2."),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--root", required=True, help="Ścieżka do lokalnego katalogu danych studia")
        sub.set_defaults(function=function)
        if name == "import-asset":
            sub.add_argument("--file", required=True)
            sub.add_argument("--kind", choices=KINDS, required=True)
            sub.add_argument("--source", default="unknown")
            sub.add_argument("--rights", default="unknown")
            sub.add_argument("--brand")
            sub.add_argument("--tags", default="")
        elif name == "register-derived":
            sub.add_argument("--file", required=True)
            sub.add_argument("--parent", required=True, help="ID zasobu źródłowego asset-<sha256>")
            sub.add_argument("--recipe", required=True, help="Operacje, parametry, narzędzie i wersja")
            sub.add_argument("--rights", default="inherited")
        elif name == "new-project":
            sub.add_argument("--id", required=True)
            sub.add_argument("--brand", required=True)
            sub.add_argument("--style", required=True)
            sub.add_argument("--slides", type=int, default=6)
        elif name in ("snapshot-style", "qa"):
            sub.add_argument("--project", required=True)
    return cli


def main():
    args = parser().parse_args()
    try:
        result = args.function(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get("status") == "fail" else 0
    except (StudioError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
