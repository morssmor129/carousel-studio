"""Local entry point for the agent, brand setup and carousel delivery."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from types import SimpleNamespace

from PIL import Image, ImageDraw

from przeglad_karuzeli import build as build_overview
from render_carousel import FONT_DEFAULT, HEIGHTS, LAYOUTS, MARGIN, WIDTH, compose, contact_sheet, contrast, load_font

PACKAGE = Path(__file__).resolve().parents[1]
SKILL = PACKAGE / ".agents/skills/carousel-studio"
EXAMPLES = PACKAGE / "examples"
sys.path.insert(0, str(SKILL / "scripts"))
import studio


ROLES = {"hook", "content", "proof", "example", "cta"}
REVIEW_CHECKS = ("readability", "safe_margins", "photo_fidelity", "brand_consistency", "facts_and_spelling")


def object_value(value, field):
    if not isinstance(value, dict):
        raise ValueError(f"{field} musi być obiektem JSON.")
    return value


def required_text(record, key):
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Uzupełnij {key}.")
    return value.strip()


def optional_text(record, key):
    value = record.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{key} musi być tekstem.")
    return value.strip()


def profiles(spec):
    brand = dict(object_value(spec.get("brand"), "brand"))
    style = dict(object_value(spec.get("style"), "style"))
    for profile in (brand, style):
        studio.valid_id(profile.get("id"))
        required_text(profile, "name")
    for field in ("offer", "audience", "tone"):
        required_text(brand, field)
    layout = style.get("layout")
    if layout not in LAYOUTS:
        raise ValueError(f"Wybierz układ: {', '.join(LAYOUTS)}.")
    height = style.get("height", 1350)
    if type(height) is not int or height not in HEIGHTS:
        raise ValueError(f"Wybierz wysokość w pikselach: {HEIGHTS}.")
    colors = object_value(style.get("color_roles"), "style.color_roles")
    palette = {key: required_text(colors, key).upper() for key in ("background", "text", "accent")}
    if any(not re.fullmatch(r"#[0-9A-F]{6}", value) for value in palette.values()):
        raise ValueError("Podaj kolory jako #RRGGBB.")
    if contrast(palette["background"], palette["text"]) < 4.5:
        raise ValueError("Kolory tła i tekstu wymagają kontrastu co najmniej 4,5:1.")
    media = object_value(brand.get("media", {}), "brand.media")
    media = {key: required_text(media, key) for key in ("logo", "heading_font", "body_font") if key in media}
    declared_fonts = object_value(brand.get("fonts", {}), "brand.fonts")
    font_names = {
        key: required_text(declared_fonts, key) if asset_key in media else FONT_DEFAULT
        for key, asset_key in (("heading", "heading_font"), ("body", "body_font"))
    }
    brand.update(schema_version=1, status="approved", media=media, colors=list(dict.fromkeys(palette.values())),
                 logo_asset_ids=[media["logo"]] if "logo" in media else [],
                 fonts={**font_names, "asset_ids": [media[key] for key in ("heading_font", "body_font") if key in media]})
    style.pop("height", None)
    style.update(schema_version=1, status="approved", canvas={"width": WIDTH, "height": height},
                 safe_margin=MARGIN, color_roles=palette, layout_rules=[layout], brand_id=brand["id"])
    return brand, style


def asset_resolver(root, brand):
    by_id = {record["id"]: record for record in studio.registry(root)["assets"]}

    def resolve(asset_id, allowed):
        seen = set()
        current = asset_id
        original_path = None

        def allowed_use(occurrence):
            return (occurrence.get("brand") == brand and occurrence.get("kind") in allowed
                    and str(occurrence.get("rights", "")).strip().lower() not in studio.UNKNOWN_RIGHTS)

        while current:
            asset = by_id.get(current)
            if not asset or current in seen:
                raise ValueError(f"Brak zasobu lub nieprawidłowe pochodzenie: {current}.")
            seen.add(current)
            if not any(allowed_use(item) for item in asset.get("occurrences", [])):
                raise ValueError(f"Brak potwierdzenia użycia zasobu {current} przez markę {brand}.")
            path = studio.managed(root, asset["canonical_path"])
            if not path.is_file() or studio.digest(path) != asset["sha256"]:
                raise ValueError(f"Zasób {current} nie zgadza się z rejestrem.")
            if current == asset_id:
                original_path = path
            current = asset.get("parent_asset_id")
        return original_path

    return resolve


def brand_paths(brand, resolve):
    media = brand["media"]
    return {
        key: resolve(media[key], ("graphic", "icon") if key == "logo" else ("graphic",)) if key in media else None
        for key in ("logo", "heading_font", "body_font")
    }


def setup(root, spec):
    brand, style = profiles(spec)
    with studio.locked(root):
        paths = brand_paths(brand, asset_resolver(root, brand["id"]))
        load_font(paths["heading_font"], 48, True)
        load_font(paths["body_font"], 40, False)
        writes = []
        for kind, record in (("brand", brand), ("style", style)):
            path = studio.managed(root, f"{kind}s/{record['id']}/{kind}.json")
            if path.exists():
                existing = studio.read_json(path)
                if {key: value for key, value in existing.items() if key != "approved_at"} != record:
                    raise ValueError(f"Profil {record['id']} ma inną zawartość. Nadaj nową wersję ID.")
            else:
                writes.append((path, {**record, "approved_at": studio.now()}))
        for path, record in writes:
            studio.atomic_json(path, record, overwrite=False)
        settings = studio.managed(root, "studio.json")
        studio.atomic_json(settings, {**studio.read_json(settings), "default_brand_id": brand["id"],
                                     "default_style_id": style["id"]})
    return {"brand_id": brand["id"], "style_id": style["id"], "workspace": str(root)}


def validate_carousel(spec, brand, style):
    identifier = studio.valid_id(spec.get("id"))
    title = required_text(spec, "title")
    raw = spec.get("slides")
    if not isinstance(raw, list) or not 2 <= len(raw) <= 30:
        raise ValueError("Karuzela musi mieć od 2 do 30 slajdów.")
    brief = dict(object_value(spec.get("brief"), "brief"))
    brief.setdefault("audience", brand["audience"])
    for field in ("goal", "audience", "key_message", "cta"):
        required_text(brief, field)
    channels = brief.get("channels")
    if not isinstance(channels, list) or not channels or not all(isinstance(x, str) and x.strip() for x in channels):
        raise ValueError("brief.channels wymaga listy kanałów publikacji.")
    facts = brief.setdefault("required_facts", [])
    if not isinstance(facts, list):
        raise ValueError("brief.required_facts musi być listą.")
    for fact in facts:
        for field in ("claim", "source"):
            required_text(object_value(fact, "required_facts"), field)
    brief.update(status="approved", slide_count=len(raw))
    slides = []
    for number, slide in enumerate(raw, start=1):
        slide = object_value(slide, f"slajd {number}")
        role = required_text(slide, "role")
        allowed_roles = {"hook"} if number == 1 else {"cta"} if number == len(raw) else ROLES - {"hook", "cta"}
        if role not in allowed_roles:
            raise ValueError(f"Nieprawidłowa rola slajdu {number}. Oczekiwane: {', '.join(sorted(allowed_roles))}.")
        photo = slide.get("photo_asset_id")
        if photo is not None and (not isinstance(photo, str) or not photo or style["layout"] != "photo"):
            raise ValueError("Zdjęcia na slajdzie obsługuje układ photo. Podaj zarejestrowane ID zasobu.")
        crop = slide.get("crop", [0.5, 0.5])
        if not isinstance(crop, list) or len(crop) != 2 or not all(type(value) in (int, float) and 0 <= value <= 1 for value in crop):
            raise ValueError("crop wymaga dwóch wartości od 0 do 1.")
        slides.append({"number": number, "role": role, "headline": required_text(slide, "headline"),
                       "body": optional_text(slide, "body"), "alt_text": required_text(slide, "alt_text"),
                       "asset_ids": [photo] if photo else [], "crop": crop})
    return identifier, title, brief, slides


def write_content(base, title, brief, slides, spec):
    studio.atomic_json(base / "brief.json", brief)
    studio.atomic_json(base / "slides.json", slides)
    copy = [f"# {title}"]
    for slide in slides:
        copy.extend((f"## Slajd {slide['number']}", slide["headline"], slide["body"], f"Tekst alternatywny: {slide['alt_text']}"))
    (base / "copy.md").write_text("\n\n".join(part for part in copy if part) + "\n", encoding="utf-8")
    caption = optional_text(spec, "caption")
    messages = optional_text(spec, "comment_messages")
    if caption or messages:
        texts = base / "captions"
        texts.mkdir()
        caption_manifest = {}
        for key, content, filename in (("", caption, "opis.txt"), ("comment_messages_", messages, "wiadomosci.txt")):
            if content:
                path = texts / filename
                path.write_text(content + "\n", encoding="utf-8")
                caption_manifest.update({key + "file": filename, key + "sha256": studio.digest(path)})
        studio.atomic_json(texts / "manifest.json", caption_manifest)


def render_project(base, brand, style, slides, resolve):
    common = brand_paths(brand, resolve)
    files, asset_map = [], []
    version = "v001"
    export = base / "exports" / version
    sources = base / "sources" / version
    previews = base / "previews"
    for directory in (export, sources, previews):
        directory.mkdir(parents=True)
    for index, slide in enumerate(slides):
        assets = slide["asset_ids"]
        photo = resolve(assets[0], ("photo", "stock", "graphic")) if assets else None
        artwork = compose(brand, style, slide, index, len(slides), {**common, "photo": photo})
        png = export / f"slide-{index + 1:02d}.png"
        svg = sources / f"slide-{index + 1:02d}.svg"
        artwork.save(png, svg)
        files.append({"slide": index + 1, "path": png.relative_to(base).as_posix(),
                      "source_path": svg.relative_to(base).as_posix(), "source_sha256": studio.digest(svg),
                      "sha256": studio.digest(png), **style["canvas"]})
        placements = {key: brand["media"][key] for key in common if common[key]}
        if photo:
            placements["photo"] = assets[0]
        asset_map.append({"slide": index + 1, "layers": [
            {"role": key, "asset_id": value, "sha256": value.removeprefix("asset-"),
             **({"crop": slide["crop"]} if key == "photo" else {})} for key, value in placements.items()
        ]})
    preview = previews / f"{version}.png"
    contact_sheet([base / item["path"] for item in files], preview)
    studio.atomic_json(base / "config/asset-map.json", asset_map)
    studio.atomic_json(base / "export-manifest.json", {"status": "ready", "version": version,
                       "files": files, "preview": preview.relative_to(base).as_posix(), "preview_sha256": studio.digest(preview)})


def create(root, spec):
    with studio.locked(root):
        defaults = studio.read_json(studio.managed(root, "studio.json"))
        brand, _, brand_source = studio.approved_document(root, "brand", spec.get("brand_id", defaults["default_brand_id"]))
        style, _, style_source = studio.approved_document(root, "style", spec.get("style_id", defaults["default_style_id"]))
        if style["brand_id"] != brand["id"]:
            raise ValueError("Wybrany styl jest przypisany do innej marki.")
        identifier, title, brief, slides = validate_carousel(spec, brand, style)
        destination = studio.managed(root, f"projects/{identifier}")
        if destination.exists():
            raise ValueError(f"Projekt {identifier} już istnieje. Nadaj nowej wersji projektu osobne ID.")
        resolve = asset_resolver(root, brand["id"])
        with tempfile.TemporaryDirectory(prefix=".carousel-build-", dir=root) as temporary:
            stage = Path(temporary).resolve()
            for relative in (brand_source, style_source):
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / relative, target)
            record = studio.cmd_new_project(SimpleNamespace(root=str(stage), id=identifier, slides=len(slides),
                                                           brand=brand["id"], style=style["id"]))
            base = Path(record["path"])
            project = studio.read_json(base / "project.json")
            studio.atomic_json(base / "project.json", {**project, "title": title, "current_copy": "copy.md"})
            write_content(base, title, brief, slides, spec)
            render_project(base, brand, style, slides, resolve)
            result = build_overview(base)
            os.rename(base, destination)
        studio.event(root, "export", project=identifier, slides=len(slides))
    return {**result, "html": str(destination / Path(result["html"]).name),
            "zip": str(destination / "downloads" / Path(result["zip"]).name), "qa": "pending"}


def review(root, identifier, review_record):
    identifier = studio.valid_id(identifier)
    base = f"projects/{identifier}"
    reviewer = required_text(review_record, "reviewer")
    notes = required_text(review_record, "notes")
    checks = object_value(review_record.get("checks"), "checks")
    reviewed = object_value(review_record.get("reviewed_sha256"), "reviewed_sha256")
    with studio.locked(root):
        manifest = studio.read_json(studio.managed(root, f"{base}/export-manifest.json"))
        expected = {item["path"]: item["sha256"] for item in manifest["files"]}
        if set(checks) != set(REVIEW_CHECKS) or any(check != "passed" for check in checks.values()):
            raise ValueError("Do pozytywnego odbioru wymagane są wszystkie sprawdzenia wizualne.")
        if reviewed != expected or any(studio.digest(studio.managed(root, f"{base}/{path}")) != digest for path, digest in expected.items()):
            raise ValueError("Ocena musi obejmować sumy SHA-256 wszystkich faktycznie obejrzanych eksportów.")
        studio.atomic_json(studio.managed(root, f"{base}/qa/manual-review.json"), {
            "reviewer": reviewer, "notes": notes, "checks": checks, "visual_review": "passed", "reviewed_at": studio.now(),
            "reviewed_files": list(reviewed), "reviewed_sha256": reviewed})
    result = studio.cmd_qa(SimpleNamespace(root=str(root), project=identifier))
    with studio.locked(root):
        record = studio.managed(root, f"{base}/project.json")
        status = "ready_for_review" if result["result"] == "PASS" else "qa_failed"
        studio.atomic_json(record, {**studio.read_json(record), "status": status})
    return result


def demo_art(destination):
    image = Image.new("RGB", (1200, 630), "#e6ded0")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 434, 1200, 630), fill="#be9c78")
    draw.polygon([(200, 90), (920, 90), (1100, 420), (380, 420)], fill="#f2e9d8")
    draw.ellipse((767, 141, 1049, 423), fill="#bd563e")
    draw.ellipse((810, 184, 1006, 380), fill="#e6ded0")
    draw.polygon([(260, 425), (630, 123), (796, 425)], fill="#173b35")
    draw.rectangle((250, 433, 1030, 456), fill="#4a594d")
    image.save(destination)


def demo(root, layout):
    root = studio.root_path(str(root / "examples"), create=True)
    studio.cmd_init(SimpleNamespace(root=str(root)))
    profile = studio.read_json(EXAMPLES / "marka-demo.json")
    profile["style"].update(id=f"demo-{layout}", layout=layout)
    identifiers = setup(root, profile)
    spec = studio.read_json(EXAMPLES / f"{layout}.json")
    spec.update(brand_id=identifiers["brand_id"], style_id=identifiers["style_id"])
    base = studio.managed(root, f"projects/{spec['id']}")
    if base.is_dir():
        page = base / "PRZEGLAD_KARUZEL.html"
        archive = base / "downloads" / f"{spec['id']}-pakiet-v001.zip"
        if not page.is_file() or not archive.is_file():
            raise ValueError(f"Przykład ma niepełne wydanie: {base}")
        return {"html": str(page), "zip": str(archive), "existing": True}
    if layout == "photo":
        with tempfile.TemporaryDirectory(prefix=".demo-art-", dir=root) as temporary:
            image = Path(temporary) / "syntetyczna-martwa-natura.png"
            demo_art(image)
            asset = studio.cmd_import(SimpleNamespace(root=str(root), file=str(image), kind="graphic",
                                      source="Oryginalna geometria wygenerowana przez demo Carousel Studio",
                                      rights="Grafika syntetyczna utworzona na potrzeby tego przykładu",
                                      brand=spec["brand_id"], tags="demo"))
        spec["slides"][0]["photo_asset_id"] = asset["asset_id"]
    return create(root, spec)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Przygotuj lokalny katalog .studio.")
    for name in ("configure", "create"):
        command = commands.add_parser(name)
        command.add_argument("input", type=Path)
    importer = commands.add_parser("import-asset")
    importer.add_argument("file")
    importer.add_argument("--kind", required=True, choices=studio.KINDS)
    importer.add_argument("--brand", required=True)
    importer.add_argument("--source", required=True)
    importer.add_argument("--rights", default="unknown")
    importer.add_argument("--tags", default="")
    sample = commands.add_parser("demo")
    sample.add_argument("layout", choices=(*LAYOUTS, "all"))
    quality = commands.add_parser("review")
    quality.add_argument("project")
    quality.add_argument("input", type=Path)
    quality.add_argument("--demo", action="store_true")
    commands.add_parser("verify")
    args = parser.parse_args()

    try:
        root = studio.root_path(str(PACKAGE / ".studio"), create=args.command in ("init", "demo"))
        args.root = str(root)
        if args.command == "init":
            result = studio.cmd_init(args)
        elif args.command == "configure":
            result = setup(root, object_value(studio.read_json(args.input.absolute()), "konfiguracja"))
        elif args.command == "create":
            result = create(root, object_value(studio.read_json(args.input.absolute()), "karuzela"))
        elif args.command == "import-asset":
            result = studio.cmd_import(args)
        elif args.command == "demo":
            layouts = LAYOUTS if args.layout == "all" else (args.layout,)
            result = {layout: demo(root, layout) for layout in layouts}
        elif args.command == "review":
            if args.demo:
                root = studio.root_path(str(root / "examples"))
            result = review(root, args.project, object_value(studio.read_json(args.input.absolute()), "ocena"))
        else:
            result = studio.cmd_verify(args)
    except (studio.StudioError, ValueError, OSError, Image.DecompressionBombError) as exc:
        print(f"Błąd: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=sys.stdout.encoding != "utf-8", indent=2))
    return 2 if result.get("status") == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
