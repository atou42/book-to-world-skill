import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_world.py"
SPEC = importlib.util.spec_from_file_location("validate_world", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_world():
    return {
        "worldConfig": {
            "name": "The Harbour", "overview": "A harbour town guards a sealed gate.",
            "language": "en", "creationMode": "book-import",
            "sections": [{"key": "characters", "label": "Characters"}],
        },
        "atoms": [{
            "type": "character", "name": "Mira", "description": "The keeper of the gate.",
            "content": [{"key": "Role", "value": "She watches the gate at night."}],
            "tags": ["Gatekeeper"],
        }],
    }


class ValidationTests(unittest.TestCase):
    def assert_error(self, value, code, path=None):
        result = MODULE.validate_world(value)
        self.assertFalse(result["ok"], result)
        matches = [error for error in result["errors"] if error["code"] == code]
        self.assertTrue(matches, result)
        if path is not None:
            self.assertIn(path, [error["path"] for error in matches], result)

    def test_valid_world_counts_and_unchanged_input(self):
        world = valid_world()
        before = copy.deepcopy(world)
        self.assertEqual(MODULE.validate_world(world), {
            "ok": True, "errors": [],
            "counts": {"sections": 1, "atoms": 1, "byType": {"character": 1}},
        })
        self.assertEqual(world, before)

    def test_builtin_mappings(self):
        for key, atom_type in MODULE.SECTION_TO_TYPE.items():
            with self.subTest(key=key):
                world = valid_world()
                world["worldConfig"]["sections"][0]["key"] = key
                world["atoms"][0]["type"] = atom_type
                self.assertTrue(MODULE.validate_world(world)["ok"])

    def test_custom_type_exact_match_no_plural_guessing(self):
        world = valid_world()
        world["worldConfig"]["sections"] = [{"key": "organization", "label": "Organizations"}]
        world["atoms"][0]["type"] = "organization"
        self.assertTrue(MODULE.validate_world(world)["ok"])
        world["worldConfig"]["sections"][0]["key"] = "organizations"
        self.assert_error(world, "undeclared_atom_type", "$.atoms[0].type")

    def test_machine_identifiers_reject_padding_without_normalizing(self):
        for section_key, atom_type, expected_path in [
            (" characters ", "character", "$.worldConfig.sections[0].key"),
            ("characters", " character ", "$.atoms[0].type"),
            (" organization ", " organization ", "$.worldConfig.sections[0].key"),
        ]:
            with self.subTest(section_key=section_key, atom_type=atom_type):
                world = valid_world()
                world["worldConfig"]["sections"][0]["key"] = section_key
                world["atoms"][0]["type"] = atom_type
                before = copy.deepcopy(world)
                self.assert_error(world, "padded_identifier", expected_path)
                self.assertEqual(world, before)
        world = valid_world()
        world["atoms"][0]["name"] = " Mira "
        world["atoms"][0]["description"] = " The keeper of the gate. "
        self.assertTrue(MODULE.validate_world(world)["ok"])

    def test_padded_section_body_key_does_not_match(self):
        world = valid_world()
        world["worldConfig"]["sectionBodies"] = {" characters ": "The people of the harbour"}
        self.assert_error(world, "undeclared_section_key", '$.worldConfig.sectionBodies[" characters "]')

    def test_duplicate_and_ambiguous_sections(self):
        world = valid_world()
        world["worldConfig"]["sections"].append({"key": "characters", "label": "Others"})
        self.assert_error(world, "duplicate_section", "$.worldConfig.sections[1].key")
        world["worldConfig"]["sections"][1]["key"] = "character"
        self.assert_error(world, "ambiguous_section_type", "$.worldConfig.sections[1].key")

    def test_empty_section(self):
        world = valid_world()
        world["worldConfig"]["sections"].append({"key": "locations", "label": "Places"})
        self.assert_error(world, "empty_section", "$.worldConfig.sections[1]")

    def test_section_text_keys_reference_declared_sections(self):
        for field in ("sectionBodies", "sectionTitles"):
            with self.subTest(field=field):
                world = valid_world()
                world["worldConfig"][field] = {"characters": "The people of the harbour"}
                self.assertTrue(MODULE.validate_world(world)["ok"])
                world["worldConfig"][field]["locations"] = "Places around the harbour"
                self.assert_error(world, "undeclared_section_key", f"$.worldConfig.{field}.locations")

    def test_duplicate_entity_unicode_case_and_space(self):
        world = valid_world()
        other = copy.deepcopy(world["atoms"][0])
        other["name"] = "  ＭＩＲＡ  "
        world["atoms"].append(other)
        self.assert_error(world, "duplicate_atom", "$.atoms[1].name")
        world["worldConfig"]["sections"].append({"key": "location", "label": "Locations"})
        other["type"] = "location"
        self.assertTrue(MODULE.validate_world(world)["ok"])

    def test_duplicate_content_key(self):
        world = valid_world()
        world["atoms"][0]["content"].append({"key": " ｒｏｌｅ ", "value": "Guard."})
        self.assert_error(world, "duplicate_content_key", "$.atoms[0].content[1].key")

    def test_duplicate_tags(self):
        world = valid_world()
        world["atoms"][0]["tags"] = ["Guard", " ＧＵＡＲＤ "]
        self.assert_error(world, "duplicate_tags", "$.atoms[0].tags")
        world["atoms"][0]["tags"] = ["Guard", "Guard"]
        self.assert_error(world, "schema_uniqueItems", "$.atoms[0].tags")

    def test_empty_tags_allowed(self):
        world = valid_world()
        world["atoms"][0]["tags"] = []
        self.assertTrue(MODULE.validate_world(world)["ok"])

    def test_blank_and_placeholder(self):
        for value, code in [(" \t\n", "blank_string"), (" TODO ", "placeholder"), ("未知", "placeholder")]:
            with self.subTest(value=value):
                world = valid_world()
                world["atoms"][0]["content"][0]["value"] = value
                self.assert_error(world, code, "$.atoms[0].content[0].value")
        world = valid_world()
        world["worldConfig"]["rules"] = ["TBD"]
        self.assert_error(world, "placeholder", "$.worldConfig.rules[0]")

    def test_internal_markers_and_source_phrases(self):
        world = valid_world()
        world["atoms"][0]["description"] = "Extracted from /workspace/chapter_0001."
        self.assert_error(world, "internal_leak", "$.atoms[0].description")
        world["atoms"][0]["description"] = "A model citizen watches an unknown ship."
        self.assertTrue(MODULE.validate_world(world)["ok"])

    def test_no_language_ratio_guess(self):
        world = valid_world()
        world["worldConfig"]["language"] = "zh"
        world["atoms"][0]["description"] = "Sherlock Holmes / John Watson / Moriarty " * 10
        self.assertTrue(MODULE.validate_world(world)["ok"])
        world["worldConfig"]["language"] = "en"
        world["atoms"][0]["description"] = "東京の街に住んでいた人間が語る物語。" * 10
        self.assertTrue(MODULE.validate_world(world)["ok"])

    def test_world_cover_uri(self):
        for uri in ["https://example.org/cover.png", "urn:isbn:12345"]:
            world = valid_world()
            world["worldConfig"]["worldCover"] = uri
            self.assertTrue(MODULE.validate_world(world)["ok"])
        for uri in ["cover.png", "https://exa mple.org/cover.png", ":invalid"]:
            world = valid_world()
            world["worldConfig"]["worldCover"] = uri
            self.assert_error(world, "schema_format", "$.worldConfig.worldCover")

    def test_maximum_lengths_count_original_string(self):
        cases = [
            (("worldConfig", "name"), 200),
            (("worldConfig", "backgroundPresetId"), 64),
            (("worldConfig", "sections", 0, "key"), 50),
            (("worldConfig", "sections", 0, "label"), 80),
            (("atoms", 0, "type"), 50),
            (("atoms", 0, "name"), 100),
            (("atoms", 0, "description"), 500),
        ]
        for keys, limit in cases:
            with self.subTest(keys=keys):
                world = valid_world()
                target = world
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = " " + "x" * limit
                self.assert_error(world, "schema_maxLength")
        world = valid_world()
        world["worldConfig"]["sectionTitles"] = {"characters": " " + "x" * 80}
        self.assert_error(world, "schema_maxLength", "$.worldConfig.sectionTitles.characters")
        world = valid_world()
        world["atoms"][0]["name"] = "界" * 100
        world["atoms"][0]["description"] = "界" * 500
        self.assertTrue(MODULE.validate_world(world)["ok"])

    def test_missing_extra_wrong_enum_and_empty_arrays(self):
        world = valid_world()
        del world["atoms"][0]["tags"]
        self.assert_error(world, "schema_required", "$.atoms[0]")
        world = valid_world()
        world["atoms"][0]["sourceId"] = "secret"
        self.assert_error(world, "schema_additionalProperties", "$.atoms[0]")
        world = valid_world()
        world["worldConfig"]["creationMode"] = "manual"
        self.assert_error(world, "schema_const", "$.worldConfig.creationMode")
        world["worldConfig"]["language"] = "ja"
        self.assert_error(world, "schema_enum", "$.worldConfig.language")
        for keys in [("atoms",), ("worldConfig", "sections"), ("atoms", 0, "content")]:
            world = valid_world()
            target = world
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = []
            self.assert_error(world, "schema_minItems")
        world = valid_world()
        world["worldConfig"]["sections"] *= 51
        self.assert_error(world, "schema_maxItems", "$.worldConfig.sections")

    def test_bad_types_return_errors_without_exceptions(self):
        paths = [(), ("worldConfig",), ("atoms",), ("atoms", 0),
                 ("worldConfig", "sections"), ("worldConfig", "sections", 0),
                 ("worldConfig", "name"), ("atoms", 0, "name"),
                 ("atoms", 0, "content"), ("atoms", 0, "content", 0),
                 ("atoms", 0, "content", 0, "key"), ("atoms", 0, "tags"),
                 ("atoms", 0, "tags", 0)]
        for keys in paths:
            for value in [None, True, 3, 2.5, {}, []]:
                with self.subTest(keys=keys, value=value):
                    world = valid_world()
                    if keys == ("atoms", 0, "tags") and value == []:
                        continue  # An empty tag list is valid under the contract.
                    if not keys:
                        world = value
                    else:
                        target = world
                        for key in keys[:-1]:
                            target = target[key]
                        target[keys[-1]] = value
                    self.assertFalse(MODULE.validate_world(world)["ok"])


class CliTests(unittest.TestCase):
    def invoke(self, raw, expected_code):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "world.json"
            file.write_bytes(raw)
            result = subprocess.run([sys.executable, str(SCRIPT), str(file)], capture_output=True, text=True)
            self.assertEqual(result.returncode, expected_code, result.stderr)
            self.assertEqual(file.read_bytes(), raw)
            self.assertEqual(result.stderr, "")
            return json.loads(result.stdout)

    def test_valid_cli(self):
        result = self.invoke(json.dumps(valid_world()).encode(), 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["counts"]["atoms"], 1)

    def test_cli_bad_inputs_are_read_only_and_fail(self):
        for raw, code in [
            (b'{"outer":{"key":1,"key":2}}', "duplicate_json_key"),
            (b'{"outer":[NaN]}', "nonfinite_number"),
            (b'{"outer":Infinity}', "nonfinite_number"),
            (b'{"outer":-Infinity}', "nonfinite_number"),
            (b'{"outer":1e999}', "nonfinite_number"),
            (b'{', "input_error"), (b'\xff', "input_error"),
            (b'{"hello":"world"}', "schema_required"),
        ]:
            with self.subTest(raw=raw):
                result = self.invoke(raw, 1)
                self.assertFalse(result["ok"])
                self.assertIn(code, [error["code"] for error in result["errors"]])
        result = self.invoke(b'{"outer":{"key":1,"key":2}}', 1)
        self.assertEqual(result["errors"][0]["path"], "$.outer.key")
        result = self.invoke(b'{"outer":[NaN]}', 1)
        self.assertEqual(result["errors"][0]["path"], "$.outer[0]")

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(SCRIPT), str(Path(directory) / "absent.json")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["errors"][0]["code"], "input_error")

    def test_help(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("never modified", result.stdout)

    def test_missing_dependency_is_clear_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "world.json"
            file.write_text(json.dumps(valid_world()), encoding="utf-8")
            result = subprocess.run([sys.executable, "-S", str(SCRIPT), str(file)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["errors"][0]["code"], "missing_dependency")


if __name__ == "__main__":
    unittest.main()
