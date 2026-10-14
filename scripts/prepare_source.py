#!/usr/bin/env python3
"""Prepare explicit local sources, in argument order, without changing originals.

Python 3 standard library. PDF additionally requires pdftotext and POSIX resource
limits. Output line ranges refer to source.txt, are one-based and inclusive.
"""

import argparse
import codecs
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile


MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_TEXT_BYTES = 32 * 1024 * 1024
MAX_ZIP_BYTES = 128 * 1024 * 1024
MAX_ZIP_ENTRIES = 10000
MAX_ZIP_RATIO = 1000
PDF_TIMEOUT = 60
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
OPF = "{http://www.idpf.org/2007/opf}"
CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"


class SourceError(ValueError):
    """An input cannot be faithfully prepared with the supported readers."""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def decode_text(data, encoding=None):
    # A caller-supplied encoding is explicit; the default never guesses legacy
    # encodings or replaces invalid bytes.
    if encoding:
        try:
            codecs.lookup(encoding)
        except LookupError as exc:
            raise SourceError("Unknown --encoding: " + encoding) from exc
        chosen = encoding
    elif data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        raise SourceError("UTF-32 requires explicit --encoding utf-32")
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        chosen = "utf-16"
    else:
        chosen = "utf-8-sig"
    try:
        return data.decode(chosen, errors="strict")
    except UnicodeError as exc:
        raise SourceError("Cannot decode text as %s; specify its real --encoding" % chosen) from exc


def normalize_text(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    for char in text:
        if unicodedata.category(char) == "Cc" and char not in "\n\t":
            raise SourceError("Text contains unsupported control characters (possibly binary or wrong encoding)")
    text = "\n".join(line.rstrip() for line in text.split("\n")).strip()
    if not text:
        raise SourceError("No readable text; image-only sources require OCR before import")
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise SourceError("Extracted text exceeds the size limit; split the source explicitly")
    return text + "\n"


def read_xml(data, label):
    # Reject declarations before parsing, including UTF-16/32 representations.
    probe = data.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in probe or b"<!ENTITY" in probe:
        raise SourceError(label + ": DTD/entity declarations are unsupported")
    try:
        return ET.fromstring(data)
    except (ET.ParseError, ValueError) as exc:
        raise SourceError(label + ": malformed XML: " + str(exc)) from exc


def safe_member_name(name):
    if not name or "\\" in name or "\x00" in name:
        raise SourceError("Unsafe archive member path: " + repr(name))
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
        raise SourceError("Unsafe archive member path: " + repr(name))
    return str(path)


class CheckedZip:
    def __init__(self, data):
        try:
            self.archive = zipfile.ZipFile(io.BytesIO(data))
        except (zipfile.BadZipFile, OSError) as exc:
            raise SourceError("Invalid ZIP document") from exc
        self.members = {}
        infos = self.archive.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise SourceError("Archive has too many entries")
        total = 0
        for entry in infos:
            name = safe_member_name(entry.filename)
            if name in self.members:
                raise SourceError("Duplicate archive member: " + name)
            self.members[name] = entry
            if entry.flag_bits & 1:
                raise SourceError("Encrypted/DRM-protected archive is unsupported")
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise SourceError("Archive symbolic links are unsupported")
            total += entry.file_size
            if total > MAX_ZIP_BYTES or entry.file_size > MAX_ZIP_BYTES:
                raise SourceError("Archive expanded size exceeds the limit")
            if entry.file_size > max(1, entry.compress_size) * MAX_ZIP_RATIO:
                raise SourceError("Archive compression ratio exceeds the limit")

    def read(self, name):
        if name not in self.members or self.members[name].is_dir():
            raise SourceError("Missing archive resource: " + name)
        try:
            with self.archive.open(self.members[name]) as stream:
                data = stream.read(MAX_ZIP_BYTES + 1)
            if len(data) > MAX_ZIP_BYTES:
                raise SourceError("Expanded archive member exceeds the limit")
            return data
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as exc:
            raise SourceError("Cannot read archive resource %s: %s" % (name, exc)) from exc


class TextHTML(HTMLParser):
    BLOCK = {"address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section", "table", "tr", "ul"}
    SKIP = {"script", "style", "head", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skipping = []
        self.images = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skipping.append(tag)
        if self.skipping:
            return
        if tag in {"img", "svg", "object", "canvas", "iframe", "audio", "video"}:
            self.images += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag in {"td", "th"}:
            self.parts.append("\t")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.skipping:
            if tag == self.skipping[-1]:
                self.skipping.pop()
            return
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(re.sub(r"\s+", " ", data))

    def text(self):
        return "\n".join(line.strip() for line in "".join(self.parts).splitlines() if line.strip())


def extract_html(text):
    parser = TextHTML()
    try:
        parser.feed(text)
        parser.close()
    except (ValueError, AssertionError) as exc:
        raise SourceError("Cannot parse HTML: " + str(exc)) from exc
    return normalize_text(parser.text()), parser.images


def image_limitations(count, kind):
    return (["%s contains %d non-text media element(s); their contents were not read. Full-source coverage cannot be claimed without reviewing/OCRing them." % (kind, count)] if count else [])


def extract_docx(data):
    archive = CheckedZip(data)
    root = read_xml(archive.read("word/document.xml"), "DOCX body")
    body = root.find(W + "body")
    if body is None:
        raise SourceError("DOCX has no document body")
    # One traversal retains table/cell and nested text-box order without reading
    # inner paragraphs once through their parent and a second time on their own.
    parts = []

    def walk(node):
        if node.tag == W + "t":
            parts.append(node.text or "")
        elif node.tag == W + "tab":
            parts.append("\t")
        elif node.tag in {W + "br", W + "cr"}:
            parts.append("\n")
        else:
            paragraph = node.tag == W + "p"
            if paragraph and parts and not parts[-1].endswith("\n"):
                parts.append("\n")
            for child in node:
                walk(child)
            if paragraph:
                parts.append("\n")

    walk(body)
    images = sum(1 for node in body.iter() if node.tag in {W + "drawing", W + "pict", W + "object"})
    limitations = image_limitations(images, "DOCX body")
    if body.find(".//" + W + "altChunk") is not None:
        raise SourceError("DOCX contains embedded altChunk text that this reader cannot extract")
    if any(name in archive.members for name in ("word/footnotes.xml", "word/endnotes.xml")):
        limitations.append("DOCX footnotes/endnotes are outside this body-only extraction; review them before claiming full-source coverage.")
    if any(re.fullmatch(r"word/(?:header|footer)\d+\.xml", name) for name in archive.members):
        limitations.append("DOCX headers/footers are outside this body-only extraction; review them before claiming full-source coverage.")
    return normalize_text("".join(parts)), limitations


def resolve_epub_path(base, href):
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc or parsed.query:
        raise SourceError("EPUB external/query resource is unsupported: " + href)
    raw = unquote(parsed.path)
    if not raw or "\\" in raw or raw.startswith("/") or "\x00" in raw:
        raise SourceError("Invalid EPUB resource path: " + href)
    parts = list(PurePosixPath(base).parent.parts)
    for part in raw.split("/"):
        if part == "..":
            if not parts:
                raise SourceError("EPUB resource escapes archive: " + href)
            parts.pop()
        elif part and part != ".":
            parts.append(part)
    return safe_member_name("/".join(parts))


def extract_epub(data):
    archive = CheckedZip(data)
    if "META-INF/encryption.xml" in archive.members:
        raise SourceError("EPUB declares encryption/DRM; decrypt or export an authorized readable copy first")
    container = read_xml(archive.read("META-INF/container.xml"), "EPUB container")
    rootfiles = container.findall(".//" + CONTAINER + "rootfile")
    candidates = [node for node in rootfiles if node.get("media-type") == "application/oebps-package+xml"]
    if len(candidates) != 1:
        raise SourceError("EPUB must identify exactly one OPF package")
    package_path = safe_member_name(candidates[0].get("full-path", ""))
    package = read_xml(archive.read(package_path), "EPUB OPF")
    manifest = package.find(OPF + "manifest")
    spine = package.find(OPF + "spine")
    if manifest is None or spine is None:
        raise SourceError("EPUB OPF is missing manifest or spine")
    items = {}
    for item in manifest.findall(OPF + "item"):
        identity = item.get("id")
        if not identity or identity in items:
            raise SourceError("EPUB manifest has missing/duplicate item id")
        path = resolve_epub_path(package_path, item.get("href", ""))
        if path not in archive.members or archive.members[path].is_dir():
            raise SourceError("Missing EPUB manifest resource: " + path)
        items[identity] = (path, item.get("media-type"))
    chapters = []
    limitations = []
    for reference in spine.findall(OPF + "itemref"):
        identity = reference.get("idref")
        if identity not in items:
            raise SourceError("EPUB spine references a missing manifest id: " + str(identity))
        path, media_type = items[identity]
        if media_type not in {"application/xhtml+xml", "text/html"}:
            raise SourceError("EPUB spine resource cannot be read completely (image or unsupported media): " + path)
        chapter = archive.read(path)
        if media_type == "application/xhtml+xml":
            root = read_xml(chapter, "EPUB chapter " + path)
            # XML's declared encoding is authoritative for XHTML. Serializing the
            # parsed tree gives HTMLParser decoded text without guessing bytes.
            for element in root.iter():
                if "}" in element.tag:
                    element.tag = element.tag.split("}", 1)[1]
            chapter_text = ET.tostring(root, encoding="unicode", method="html")
        else:
            chapter_text = decode_text(chapter)
        try:
            text, images = extract_html(chapter_text)
        except SourceError as exc:
            raise SourceError("EPUB chapter %s: %s" % (path, exc)) from exc
        chapters.append(text)
        limitations.extend(image_limitations(images, "EPUB chapter " + path))
    if not chapters:
        raise SourceError("EPUB spine is empty")
    return normalize_text("".join(chapters)), limitations


def extract_pdf(data):
    command = shutil.which("pdftotext")
    if command is None:
        raise SourceError("PDF requires pdftotext; export plain text or install it separately")
    try:
        import resource
    except ImportError as exc:
        raise SourceError("PDF extraction requires POSIX resource limits on this platform") from exc

    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_TEXT_BYTES, MAX_TEXT_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (PDF_TIMEOUT, PDF_TIMEOUT))

    with tempfile.TemporaryDirectory(prefix="book-pdf-") as directory:
        source = Path(directory) / "input.pdf"
        target = Path(directory) / "output.txt"
        error = Path(directory) / "stderr.txt"
        source.write_bytes(data)
        try:
            with error.open("wb") as stderr:
                result = subprocess.run([command, "-enc", "UTF-8", str(source), str(target)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=stderr, timeout=PDF_TIMEOUT, check=False, preexec_fn=limits)
        except subprocess.TimeoutExpired as exc:
            raise SourceError("PDF extraction exceeded its time limit") from exc
        error_text = error.read_bytes()[:4096].decode("utf-8", errors="backslashreplace").strip()
        if result.returncode != 0:
            raise SourceError("pdftotext failed (%s): %s" % (result.returncode, error_text))
        # Diagnostics may signal damaged content despite exit status zero.
        if error_text:
            raise SourceError("pdftotext reported diagnostics; inspect the PDF before importing: " + error_text)
        if not target.is_file() or target.stat().st_size > MAX_TEXT_BYTES:
            raise SourceError("PDF output is missing or exceeds the text size limit")
        text = decode_text(target.read_bytes())
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()  # pdftotext's final page separator is not another page.
    if any(not page.strip() for page in pages):
        raise SourceError("PDF has page(s) without extractable text; inspect/OCR them before importing the full source")
    return normalize_text(text), ["PDF uses the existing text layer only. Images, charts, reading order, and missing text inside partly scanned pages require review before claiming full-source coverage."]


def prepare_source(inputs, output_dir, encoding=None):
    output = Path(output_dir)
    if output.exists() or output.is_symlink():
        raise SourceError("Output directory already exists; choose a new directory: " + str(output))
    if not inputs:
        raise SourceError("Supply at least one explicit input file")
    sources, texts = [], []
    line = 1
    combined_bytes = 0
    for supplied in inputs:
        path = Path(supplied).expanduser().resolve()
        if not path.is_file():
            raise SourceError("Input must be an explicit regular file: " + str(path))
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise SourceError("Input exceeds 64 MiB; split it explicitly: " + str(path))
        with path.open("rb") as stream:
            data = stream.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            raise SourceError("Input exceeds size limit: " + str(path))
        extension = path.suffix.lower()
        limitations = []
        try:
            if extension in {".txt", ".md", ".markdown"}:
                text = normalize_text(decode_text(data, encoding))
            elif extension in {".html", ".htm"}:
                text, images = extract_html(decode_text(data, encoding))
                limitations = image_limitations(images, "HTML")
            elif extension == ".docx":
                text, limitations = extract_docx(data)
            elif extension == ".epub":
                text, limitations = extract_epub(data)
            elif extension == ".pdf":
                text, limitations = extract_pdf(data)
            else:
                raise SourceError("Unsupported extension: " + extension)
        except SourceError as exc:
            raise SourceError("%s: %s" % (path, exc)) from exc
        encoded = text.encode("utf-8")
        combined_bytes += len(encoded)
        if combined_bytes > MAX_TEXT_BYTES:
            raise SourceError("Combined text exceeds 32 MiB; split the import explicitly")
        count = text.count("\n")
        sources.append({"source_path": str(path), "format": extension[1:], "sha256": sha256(data), "extracted_sha256": sha256(encoded), "start_line": line, "end_line": line + count - 1, "limitations": limitations})
        line += count
        texts.append(text)
    combined = "".join(texts).encode("utf-8")
    manifest = {"schema_version": 1, "source_file": "source.txt", "source_sha256": sha256(combined), "total_lines": line - 1, "sources": sources}
    # mkdir claims a fresh directory atomically. A failure removes only files
    # created by this run, never an existing directory or source.
    output.mkdir(parents=False, exist_ok=False)
    created = []
    try:
        for name, payload in [("source.txt", combined), ("source-manifest.json", (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))]:
            temporary = output / ("." + name + ".tmp")
            with temporary.open("xb") as stream:
                created.append(temporary)
                stream.write(payload)
            final = output / name
            temporary.rename(final)
            created[-1] = final
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        output.rmdir()
        raise
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="Explicit local files, in reading order; directories/URLs are unsupported")
    parser.add_argument("--output-dir", required=True, help="New directory under an existing parent")
    parser.add_argument("--encoding", help="Explicit encoding for TXT/Markdown/HTML; default strict UTF-8 or BOM-marked UTF-16")
    arguments = parser.parse_args(argv)
    try:
        manifest = prepare_source(arguments.inputs, arguments.output_dir, arguments.encoding)
    except (SourceError, OSError) as exc:
        print("Source preparation failed: " + str(exc), file=sys.stderr)
        return 2
    print("Prepared %d file(s), %d lines in %s" % (len(manifest["sources"]), manifest["total_lines"], arguments.output_dir))
    for source in manifest["sources"]:
        for limitation in source["limitations"]:
            print("REVIEW REQUIRED: %s: %s" % (source["source_path"], limitation), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
