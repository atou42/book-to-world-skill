#!/usr/bin/env python3
"""Read-only validation of a Neta Studio World Import V1 JSON file.

Checks structure and mechanical consistency, not source coverage or truth.
"""

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "references" / "studio-world-import-v1.schema.json"
SECTION_TO_TYPE = {
    "characters": "character", "character": "character",
    "locations": "location", "location": "location",
    "events": "event", "event": "event",
    "secrets": "secret", "secret": "secret",
    "perspectives": "perspective", "perspective": "perspective",
    "lore": "lore",
}
PLACEHOLDER = re.compile(r"(?:starter|unknown|todo|tbd|n/a|none|null|未定|未知|待补|暂无)", re.I)
INTERNAL_LEAK = re.compile(
    r"/workspace\b|\buploads/|\bchapter_\d{4}\b|\bconfidence\s*[:：]|"
    r"\bmodel\s*[:：]|\bsystem prompt\b|处理日志|置信度|评测字段", re.I
)


def child_path(path, key):
    if isinstance(key, int):
        return f"{path}[{key}]"
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return f"{path}.{key}"
    return f"{path}[{json.dumps(key, ensure_ascii=False)}]"


class InputError(ValueError):
    def __init__(self, code, path, message):
        super().__init__(message)
        self.error = {"code": code, "path": path, "message": message}


class ObjectPairs(list):
    """Keep JSON object pairs until duplicate keys have been checked."""


def read_json(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=ObjectPairs)

    def materialize(item, location):
        if isinstance(item, ObjectPairs):
            result = {}
            for key, entry in item:
                entry_path = child_path(location, key)
                if key in result:
                    raise InputError("duplicate_json_key", entry_path, f"Duplicate JSON key: {key!r}.")
                result[key] = materialize(entry, entry_path)
            return result
        if isinstance(item, list):
            return [materialize(entry, child_path(location, i)) for i, entry in enumerate(item)]
        if isinstance(item, float) and not math.isfinite(item):
            raise InputError("nonfinite_number", location, "NaN, infinity and numeric overflow are not allowed.")
        return item

    return materialize(value, "$")


def normalized(value):
    return unicodedata.normalize("NFKC", value).strip().casefold()


def counts_for(payload):
    config = payload.get("worldConfig") if isinstance(payload, dict) else None
    sections = config.get("sections") if isinstance(config, dict) else None
    atoms = payload.get("atoms") if isinstance(payload, dict) else None
    by_type = Counter(
        atom["type"] for atom in (atoms if isinstance(atoms, list) else [])
        if isinstance(atom, dict) and isinstance(atom.get("type"), str)
    )
    return {"sections": len(sections) if isinstance(sections, list) else 0,
            "atoms": len(atoms) if isinstance(atoms, list) else 0,
            "byType": dict(sorted(by_type.items()))}


def validate_world(payload):
    from jsonschema import Draft202012Validator, FormatChecker

    schema = read_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    checker = FormatChecker()
    if "uri" not in checker.checkers:
        raise RuntimeError("URI format support is missing; install requirements.txt with its format extras.")
    validator = Draft202012Validator(schema, format_checker=checker)
    errors = []
    for error in validator.iter_errors(payload):
        location = "$"
        for component in error.absolute_path:
            location = child_path(location, component)
        errors.append({"code": f"schema_{error.validator}", "path": location, "message": error.message})
    counts = counts_for(payload)
    if errors:
        return {"ok": False, "errors": errors, "counts": counts}

    def add(code, path, message):
        errors.append({"code": code, "path": path, "message": message})

    def check_strings(value, path):
        if isinstance(value, dict):
            for key, entry in value.items():
                check_strings(entry, child_path(path, key))
        elif isinstance(value, list):
            for index, entry in enumerate(value):
                check_strings(entry, child_path(path, index))
        elif isinstance(value, str):
            if not value.strip():
                add("blank_string", path, "Whitespace-only strings are not allowed.")
            elif PLACEHOLDER.fullmatch(value.strip()):
                add("placeholder", path, "Placeholder values are not allowed.")

    check_strings(payload, "$")
    config = payload["worldConfig"]
    resolved_types = {}
    section_keys = set()
    for index, section in enumerate(config["sections"]):
        path = f"$.worldConfig.sections[{index}].key"
        key = section["key"]
        if key != key.strip():
            add("padded_identifier", path, "Section keys must not contain leading or trailing whitespace.")
        if key in section_keys:
            add("duplicate_section", path, f"Duplicate section key: {key}.")
        section_keys.add(key)
        atom_type = SECTION_TO_TYPE.get(key, key)
        if atom_type in resolved_types:
            add("ambiguous_section_type", path, f"Multiple sections resolve to Atom type {atom_type}.")
        resolved_types[atom_type] = (key, index)

    def visible(value, path):
        if INTERNAL_LEAK.search(value):
            add("internal_leak", path, "Visible text contains a known internal import marker; review it against the source.")

    for field in ("name", "genre", "tone", "era", "overview", "prologue", "coreConflict", "visualStyle"):
        if field in config:
            visible(config[field], f"$.worldConfig.{field}")
    for index, value in enumerate(config.get("rules", [])):
        visible(value, f"$.worldConfig.rules[{index}]")
    for field in ("sectionBodies", "sectionTitles"):
        for key, value in config.get(field, {}).items():
            path = child_path(f"$.worldConfig.{field}", key)
            if key not in section_keys:
                add("undeclared_section_key", path, f"No declared section has key {key}.")
            visible(value, path)
    for index, section in enumerate(config["sections"]):
        visible(section["label"], f"$.worldConfig.sections[{index}].label")

    identities = set()
    type_counts = Counter()
    for index, atom in enumerate(payload["atoms"]):
        base = f"$.atoms[{index}]"
        atom_type = atom["type"]
        if atom_type != atom_type.strip():
            add("padded_identifier", f"{base}.type", "Atom types must not contain leading or trailing whitespace.")
        if atom_type not in resolved_types:
            add("undeclared_atom_type", f"{base}.type", f"No section matches Atom type {atom_type}.")
        type_counts[atom_type] += 1
        identity = (normalized(atom["type"]), normalized(atom["name"]))
        if identity in identities:
            add("duplicate_atom", f"{base}.name", "Duplicate Atom name within one type.")
        identities.add(identity)
        keys = set()
        for content_index, field in enumerate(atom["content"]):
            path = f"{base}.content[{content_index}]"
            key = normalized(field["key"])
            if key in keys:
                add("duplicate_content_key", f"{path}.key", "Content keys must be unique within an Atom.")
            keys.add(key)
            visible(field["key"], f"{path}.key")
            visible(field["value"], f"{path}.value")
        if len({normalized(tag) for tag in atom["tags"]}) != len(atom["tags"]):
            add("duplicate_tags", f"{base}.tags", "Tags must be unique after Unicode and case normalization.")
        for field in ("name", "description"):
            visible(atom[field], f"{base}.{field}")
        for tag_index, tag in enumerate(atom["tags"]):
            visible(tag, f"{base}.tags[{tag_index}]")

    for atom_type, (key, index) in resolved_types.items():
        if not type_counts[atom_type]:
            add("empty_section", f"$.worldConfig.sections[{index}]", f"Section {key} has no matching Atoms.")
    return {"ok": not errors, "errors": errors, "counts": counts}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("world", type=Path, help="UTF-8 JSON file to validate; never modified")
    args = parser.parse_args(argv)
    try:
        payload = read_json(args.world)
        result = validate_world(payload)
    except InputError as error:
        result = {"ok": False, "errors": [error.error], "counts": counts_for(None)}
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        result = {"ok": False, "errors": [{"code": "input_error", "path": "$", "message": str(error)}], "counts": counts_for(None)}
    except ImportError as error:
        result = {"ok": False, "errors": [{"code": "missing_dependency", "path": "$", "message": f"{error}. Install this skill's requirements.txt."}], "counts": counts_for(None)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
