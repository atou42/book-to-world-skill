import codecs
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile


SPEC = importlib.util.spec_from_file_location("prepare_source", Path(__file__).parents[1] / "scripts" / "prepare_source.py")
prep = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prep)


def archive_bytes(files, compression=zipfile.ZIP_STORED):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def epub_files():
    return {
        "META-INF/container.xml": '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        "OPS/package.opf": '<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="second" href="text/a.xhtml" media-type="application/xhtml+xml"/><item id="first" href="text/z.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="first"/><itemref idref="second"/></spine></package>',
        "OPS/text/a.xhtml": '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Hidden title</title></head><body><p>第二章</p></body></html>',
        "OPS/text/z.xhtml": '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>第一章</p></body></html>',
    }


class PrepareSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output = self.root / "prepared"

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, name, data):
        path = self.root / name
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        return path

    def assert_failed(self, path, match):
        original = path.read_bytes() if path.is_file() else None
        with self.assertRaisesRegex(prep.SourceError, match):
            prep.prepare_source([path], self.output)
        self.assertFalse(self.output.exists(), "Failed parsing must not create output")
        if original is not None:
            self.assertEqual(path.read_bytes(), original)

    def test_input_argument_order_exact_hashes_and_line_ranges(self):
        second = self.write("a.md", "  后篇\n\n尾声\n")
        first = self.write("z.txt", codecs.BOM_UTF8 + "首章\r\n下一行\r\n".encode())
        result = prep.prepare_source([first, second], self.output)
        expected = "首章\n下一行\n后篇\n\n尾声\n".encode()
        self.assertEqual((self.output / "source.txt").read_bytes(), expected)
        self.assertEqual(result["total_lines"], 5)
        self.assertEqual(result["source_sha256"], hashlib.sha256(expected).hexdigest())
        self.assertEqual([(row["start_line"], row["end_line"]) for row in result["sources"]], [(1, 2), (3, 5)])
        lines = expected.decode().splitlines(keepends=True)
        for row, path in zip(result["sources"], [first, second]):
            self.assertEqual(row["source_path"], str(path.resolve()))
            self.assertEqual(row["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            portion = "".join(lines[row["start_line"] - 1:row["end_line"]]).encode()
            self.assertEqual(row["extracted_sha256"], hashlib.sha256(portion).hexdigest())
        self.assertEqual(json.loads((self.output / "source-manifest.json").read_text()), result)

    def test_utf16_bom_and_explicit_legacy_encoding(self):
        source = self.write("utf16.txt", "中文文本".encode("utf-16"))
        prep.prepare_source([source], self.output)
        self.assertEqual((self.output / "source.txt").read_text(), "中文文本\n")
        legacy = self.write("legacy.txt", "繁體中文".encode("big5"))
        result = self.root / "legacy-output"
        prep.prepare_source([legacy], result, encoding="big5")
        self.assertEqual((result / "source.txt").read_text(), "繁體中文\n")

    def test_invalid_encoding_fails_without_replacement(self):
        self.assert_failed(self.write("broken.txt", b"hello\xffworld"), "Cannot decode")

    def test_binary_disguised_as_text_fails(self):
        self.assert_failed(self.write("binary.txt", b"hello\x00world"), "control characters")

    def test_existing_directory_and_symlink_never_overwritten(self):
        source = self.write("source.txt", "new text")
        self.output.mkdir()
        sentinel = self.output / "source.txt"
        sentinel.write_text("existing work")
        with self.assertRaisesRegex(prep.SourceError, "already exists"):
            prep.prepare_source([source], self.output)
        self.assertEqual(sentinel.read_text(), "existing work")
        link = self.root / "link"
        link.symlink_to(self.root / "missing")
        with self.assertRaisesRegex(prep.SourceError, "already exists"):
            prep.prepare_source([source], link)
        self.assertTrue(link.is_symlink())

    def test_later_input_failure_creates_no_partial_output(self):
        first = self.write("first.txt", "valid")
        second = self.write("bad.txt", b"\xff")
        with self.assertRaises(prep.SourceError):
            prep.prepare_source([first, second], self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(first.read_text(), "valid")

    def test_output_write_failure_removes_success_files(self):
        source = self.write("first.txt", "valid")
        original_open = Path.open

        def failing_open(path, *args, **kwargs):
            if path.name == ".source-manifest.json.tmp":
                raise OSError("simulated disk full")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", failing_open):
            with self.assertRaisesRegex(OSError, "disk full"):
                prep.prepare_source([source], self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(source.read_text(), "valid")

    def test_directories_and_empty_text_are_rejected(self):
        self.assert_failed(self.root, "explicit regular file")
        self.assert_failed(self.write("blank.txt", " \n\t"), "No readable text")

    def test_html_visible_text_order_and_media_disclosure(self):
        source = self.write("page.html", '<html><head><title>Do not read</title></head><body><p>A <b>bold</b> &amp; B.</p><script>secret()</script><p>Second<br>Third</p><img src="image.png" alt="Not actual image text"></body></html>')
        manifest = prep.prepare_source([source], self.output)
        self.assertEqual((self.output / "source.txt").read_text(), "A bold & B.\nSecond\nThird\n")
        self.assertIn("1 non-text media", manifest["sources"][0]["limitations"][0])

    def test_docx_table_and_paragraph_order(self):
        xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Before</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell 1</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Cell 2</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:r><w:t>After</w:t><w:tab/><w:t>tab</w:t><w:br/><w:t>new line</w:t></w:r></w:p></w:body></w:document>'
        source = self.write("book.docx", archive_bytes({"word/document.xml": xml}))
        prep.prepare_source([source], self.output)
        self.assertEqual((self.output / "source.txt").read_text(), "Before\nCell 1\nCell 2\nAfter\ttab\nnew line\n")

    def test_docx_nested_text_box_is_read_once_in_place(self):
        xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Before</w:t></w:r><w:r><w:pict><w:txbxContent><w:p><w:r><w:t>Box text</w:t></w:r></w:p></w:txbxContent></w:pict></w:r><w:r><w:t>After</w:t></w:r></w:p></w:body></w:document>'
        source = self.write("textbox.docx", archive_bytes({"word/document.xml": xml}))
        prep.prepare_source([source], self.output)
        self.assertEqual((self.output / "source.txt").read_text(), "Before\nBox text\nAfter\n")

    def test_epub_spine_order_overrides_manifest_and_archive_order(self):
        source = self.write("book.epub", archive_bytes(epub_files()))
        prep.prepare_source([source], self.output)
        self.assertEqual((self.output / "source.txt").read_text(), "第一章\n第二章\n")

    def test_epub_relative_parent_paths_inside_archive_are_valid(self):
        files = epub_files()
        files["OPS/package.opf"] = files["OPS/package.opf"].replace("text/z.xhtml", "../text/z.xhtml")
        files["text/z.xhtml"] = files.pop("OPS/text/z.xhtml")
        source = self.write("book.epub", archive_bytes(files))
        prep.prepare_source([source], self.output)
        self.assertEqual((self.output / "source.txt").read_text(), "第一章\n第二章\n")

    def test_epub_missing_chapter_and_missing_spine_id(self):
        files = epub_files()
        del files["OPS/text/z.xhtml"]
        self.assert_failed(self.write("missing.epub", archive_bytes(files)), "Missing EPUB manifest resource")
        files = epub_files()
        files["OPS/package.opf"] = files["OPS/package.opf"].replace('idref="first"', 'idref="unknown"')
        self.assert_failed(self.write("bad-id.epub", archive_bytes(files)), "missing manifest id")

    def test_epub_empty_or_image_only_chapter_is_not_silently_skipped(self):
        files = epub_files()
        files["OPS/text/z.xhtml"] = '<html xmlns="http://www.w3.org/1999/xhtml"><body><img src="page.png"/></body></html>'
        self.assert_failed(self.write("images.epub", archive_bytes(files)), "No readable text")

    def test_epub_drm_and_malformed_xml_fail(self):
        files = epub_files()
        files["META-INF/encryption.xml"] = "<encryption/>"
        self.assert_failed(self.write("drm.epub", archive_bytes(files)), "encryption/DRM")
        files = epub_files()
        files["OPS/text/z.xhtml"] = "<broken>"
        self.assert_failed(self.write("malformed.epub", archive_bytes(files)), "malformed XML")

    def test_epub_dtd_and_unsafe_path_fail(self):
        files = epub_files()
        files["OPS/text/z.xhtml"] = '<!DOCTYPE html [<!ENTITY x "abc">]><html><body>&x;</body></html>'
        self.assert_failed(self.write("entity.epub", archive_bytes(files)), "DTD/entity")
        files = epub_files()
        files["OPS/package.opf"] = files["OPS/package.opf"].replace("text/z.xhtml", "../../escape.xhtml")
        self.assert_failed(self.write("escape.epub", archive_bytes(files)), "escapes archive")
        files = epub_files()
        files["../unused.txt"] = "even unused unsafe entries fail"
        self.assert_failed(self.write("unsafe.epub", archive_bytes(files)), "Unsafe archive")

    def test_zip_expansion_limit_fails_before_reading_content(self):
        source = self.write("large.epub", archive_bytes(epub_files()))
        with patch.object(prep, "MAX_ZIP_BYTES", 20):
            self.assert_failed(source, "expanded size")

    def test_combined_text_limit_does_not_truncate(self):
        first = self.write("first.txt", "abc")
        second = self.write("second.txt", "def")
        with patch.object(prep, "MAX_TEXT_BYTES", 7):
            with self.assertRaisesRegex(prep.SourceError, "Combined text"):
                prep.prepare_source([first, second], self.output)
        self.assertFalse(self.output.exists())

    def test_pdf_dependency_absent_is_explicit(self):
        source = self.write("book.pdf", b"%PDF-placeholder")
        with patch.object(prep.shutil, "which", return_value=None):
            self.assert_failed(source, "requires pdftotext")

    def test_pdf_blank_page_and_diagnostics_fail(self):
        source = self.write("book.pdf", b"%PDF-placeholder")

        def convert(arguments, **kwargs):
            Path(arguments[-1]).write_text("Page one\f\fPage three\f")
            return subprocess.CompletedProcess(arguments, 0)

        with patch.object(prep.shutil, "which", return_value="/fake/pdftotext"), patch.object(prep.subprocess, "run", side_effect=convert):
            self.assert_failed(source, r"page\(s\) without extractable")

        def warn(arguments, **kwargs):
            Path(arguments[-1]).write_text("Some text\f")
            kwargs["stderr"].write(b"Syntax Warning: broken page")
            return subprocess.CompletedProcess(arguments, 0)

        with patch.object(prep.shutil, "which", return_value="/fake/pdftotext"), patch.object(prep.subprocess, "run", side_effect=warn):
            self.assert_failed(source, "reported diagnostics")

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext is an optional local dependency")
    def test_real_pdf_text_extraction(self):
        # A complete one-page PDF with a real text layer; no fixture dependency.
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
        stream = b"BT /F1 12 Tf 20 250 Td (Hello PDF) Tj ET\n"
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream")
        pdf = b"%PDF-1.4\n"
        offsets = []
        for number, obj in enumerate(objects, 1):
            offsets.append(len(pdf))
            pdf += str(number).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
        xref = len(pdf)
        pdf += b"xref\n0 6\n0000000000 65535 f \n"
        for offset in offsets:
            pdf += ("%010d 00000 n \n" % offset).encode()
        pdf += b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(xref).encode() + b"\n%%EOF\n"
        source = self.write("real.pdf", pdf)
        manifest = prep.prepare_source([source], self.output)
        self.assertEqual((self.output / "source.txt").read_text(), "Hello PDF\n")
        self.assertIn("text layer", manifest["sources"][0]["limitations"][0])

    def test_cli_failure_exit_and_no_false_success(self):
        source = self.write("bad.txt", b"\xff")
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            result = prep.main([str(source), "--output-dir", str(self.output)])
        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Cannot decode", stderr.getvalue())
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
