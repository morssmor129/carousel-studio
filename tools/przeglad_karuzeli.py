import argparse
import hashlib
import json
import os
import re
import zipfile
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import quote


def read_json(file):
    return json.loads(file.read_text(encoding="utf-8-sig"))


def verified_file(project, relative, checksum=None):
    file = (project / relative).resolve()
    if not file.is_relative_to(project) or not file.is_file():
        raise ValueError(f"Brak pliku w projekcie: {relative}")
    if checksum and hashlib.sha256(file.read_bytes()).hexdigest() != checksum:
        raise ValueError(f"Niezgodna suma SHA-256: {relative}")
    return file


def link_to(project, file):
    return quote(file.relative_to(project).as_posix())


def text_panel(title, content, field_id):
    return (
        f'<div class="text-panel"><div class="panel-heading"><h3>{escape(title)}</h3>'
        f'<button type="button" class="copy" data-copy="{field_id}">Kopiuj</button></div>'
        f'<pre id="{field_id}">{escape(content)}</pre></div>'
    )


def message_panels(content):
    panels = []
    for index, block in enumerate(content.strip().split("\n\n"), start=1):
        heading, separator, body = block.partition("\n")
        if not separator:
            panels.append(text_panel("Wiadomość", heading, f"chat-{index}"))
            continue
        if heading == "Trzy odpowiedzi pod postem":
            replies = re.findall(r"^\d+\.\s+(.+)$", body, flags=re.MULTILINE)
            if replies and len(replies) == len(body.splitlines()):
                for number, reply in enumerate(replies, start=1):
                    panels.append(text_panel(f"Odpowiedź pod postem {number}", reply, f"chat-{index}-{number}"))
                continue
        panels.append(text_panel(heading, body, f"chat-{index}"))
    return "\n".join(panels)


def source_text_section(project, title, file, attribute, status):
    text = file.read_text(encoding="utf-8-sig").strip()
    if attribute == "wiadomosci":
        content = message_panels(text)
    else:
        content = text_panel("Treść posta", text, "caption-text")
    return (
        f'<section id="{attribute}" class="copy-section"><div class="section-heading">'
        f'<div><h2>{escape(title)}</h2><p>{escape(status)}</p></div>'
        f'<a class="text-link" href="{link_to(project, file)}" download>Pobierz TXT</a></div>'
        f'{content}</section>'
    )


def write_archive(destination, members):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, file in members.items():
            archive.write(file, name)
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() is not None or archive.namelist() != list(members):
            raise ValueError("Nieprawidłowa zawartość paczki ZIP.")
        for name, file in members.items():
            if archive.read(name) != file.read_bytes():
                raise ValueError(f"Zawartość paczki różni się od projektu: {name}")
    os.replace(temporary, destination)


def build(project):
    project = project.resolve()
    record = read_json(project / "project.json")
    manifest_path = record.get("current_manifest") or "export-manifest.json"
    manifest = read_json(verified_file(project, manifest_path))
    exports = sorted(manifest["files"], key=lambda item: item["slide"])
    if not exports or [item["slide"] for item in exports] != list(range(1, len(exports) + 1)):
        raise ValueError("Manifest powinien zawierać po jednym eksporcie każdego slajdu.")
    slides = read_json(project / "slides.json")
    slide_info = {slide["number"]: slide for slide in slides}
    brand_path = project / "config" / "brand.json"
    brand = read_json(brand_path)["name"] if brand_path.is_file() else record["brand_id"]

    entries = {}
    thumbnails = []
    for item in exports:
        number = item["slide"]
        image_file = verified_file(project, item["path"], item.get("sha256"))
        entries[f"Kafelki/slide-{number:02d}{image_file.suffix.lower()}"] = image_file
        if item.get("source_path"):
            source = verified_file(project, item["source_path"], item.get("source_sha256"))
            entries[f"Zrodla/slide-{number:02d}{source.suffix.lower()}"] = source
        alt = item.get("alt_text") or slide_info[number]["alt_text"]
        image_link = link_to(project, image_file)
        thumbnails.append(
            f'<figure class="slide"><a class="slide-image" href="{image_link}" target="_blank" '
            f'rel="noopener" aria-label="Otwórz kafelek {number} w pełnym rozmiarze">'
            f'<img src="{image_link}" alt="{escape(alt)}" width="{int(item["width"])}" height="{int(item["height"])}"></a>'
            f'<figcaption><span>Kafelek {number}</span><a href="{image_link}" download="slide-{number:02d}{image_file.suffix.lower()}">'
            f'Pobierz {image_file.suffix[1:].upper()}</a></figcaption></figure>'
        )

    status = "Zaakceptowane do publikacji" if record.get("status") == "approved" else "Do akceptacji"
    note = f"{len(exports)} kafelków · {status}"
    nav = ['<a href="#kafelki">Kafelki</a>']
    sections = []
    caption_manifest = project / "captions" / "manifest.json"
    if caption_manifest.is_file():
        caption = read_json(caption_manifest)
        if caption.get("file"):
            caption_file = verified_file(project, "captions/" + caption["file"], caption.get("sha256"))
            entries["Teksty/Opis-Instagram.txt"] = caption_file
            caption_status = "Zaakceptowany" if caption.get("user_accepted") else "Do akceptacji"
            nav.append('<a href="#opis">Opis</a>')
            sections.append(source_text_section(project, "Opis na Instagram", caption_file, "opis", caption_status))
        if caption.get("comment_messages_file"):
            messages = verified_file(project, "captions/" + caption["comment_messages_file"], caption.get("comment_messages_sha256"))
            entries["Teksty/Wiadomosci-po-komentarzu.txt"] = messages
            messages_status = "Zaakceptowane" if caption.get("comment_messages_user_accepted") else "Do akceptacji"
            if caption.get("comment_keyword"):
                messages_status += f' · Hasło „{caption["comment_keyword"]}”'
            nav.append('<a href="#wiadomosci">Wiadomości</a>')
            sections.append(source_text_section(project, "Wiadomości po komentarzu", messages, "wiadomosci", messages_status))

    if record.get("current_copy"):
        copy = verified_file(project, record["current_copy"])
        entries["Teksty/" + copy.name] = copy
        nav.append('<a href="#teksty">Teksty slajdów</a>')
        sections.insert(0, '<section id="teksty" class="copy-section">' + text_panel(
            "Teksty slajdów i opisy alternatywne", copy.read_text(encoding="utf-8-sig").strip(), "slides-text"
        ) + '</section>')
    if manifest.get("preview"):
        preview = verified_file(project, manifest["preview"], manifest.get("preview_sha256"))
        entries["Podglad/" + preview.name] = preview

    version = manifest["version"]
    if not version.isalnum():
        raise ValueError("Nieprawidłowa wersja w manifeście.")
    archive = project / "downloads" / f"{project.name}-pakiet-{version}.zip"
    write_archive(archive, entries)

    template_path = Path(__file__).with_suffix(".html")
    template = Template(template_path.read_text(encoding="utf-8-sig"))
    html = template.substitute(
        brand=escape(brand), title=escape(record["title"]), note=escape(note),
        download=link_to(project, archive), navigation="\n".join(nav),
        slides="\n".join(thumbnails), copy="\n".join(sections),
    )
    page = project / "PRZEGLAD_KARUZEL.html"
    page.write_text(html, encoding="utf-8")

    return {"html": str(page), "zip": str(archive), "slides": len(exports), "files": len(entries)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tworzy lokalny przegląd HTML i ZIP bieżącej karuzeli.")
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.project), ensure_ascii=False))
