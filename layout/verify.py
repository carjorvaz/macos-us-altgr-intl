#!/usr/bin/env python3
"""Focused offline verification for the sealed clean-room keyboard artifacts."""
from __future__ import annotations

import itertools
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def fail(message: str) -> None:
    raise AssertionError(message)


def xml_tree() -> ET.Element:
    raw = (ROOT / "us-altgr-intl.keylayout").read_text(encoding="utf-8")
    if not raw.startswith('<?xml version="1.1" encoding="UTF-8"?>'):
        fail("layout is not declared as UTF-8 XML 1.1")
    if "\x00" in raw:
        fail("literal NUL in XML")
    # The platform libxml2/Expat builds available here reject XML 1.1 control
    # references. Replace only those references with legal private-use scalars
    # for structural parsing; the original spelling is checked independently.
    def safe_control(match: re.Match[str]) -> str:
        cp = int(match.group(1), 16)
        return chr(0xE000 + cp) if cp < 0x20 or cp == 0x7F else match.group(0)
    structural = re.sub(r"&#x([0-9A-Fa-f]+);", safe_control, raw)
    structural = structural.replace('<?xml version="1.1"', '<?xml version="1.0"', 1)
    return ET.fromstring(structural)


def modifier_matches(spec: str, state: dict[str, bool]) -> bool:
    tokens = spec.split()
    required = {token[:-1] if token.endswith("?") else token for token in tokens if not token.endswith("?")}
    optional = {token[:-1] for token in tokens if token.endswith("?")}
    names = {"anyShift", "anyOption", "anyControl", "command", "caps"}
    if (required | optional) - names:
        fail(f"unknown modifier token in {spec!r}")
    return all(state[name] if name in required else (True if name in optional else not state[name]) for name in names)


def main() -> int:
    subprocess.run([sys.executable, str(ROOT / "generate.py"), "--check"], cwd=ROOT, check=True)
    spec = json.loads((ROOT / "layout-spec.json").read_text(encoding="utf-8"))
    derivation = json.loads((ROOT / "derivation.json").read_text(encoding="utf-8"))
    root = xml_tree()

    assert root.tag == "keyboard"
    assert root.attrib["name"] == "us-altgr-intl"
    assert int(root.attrib["id"]) == spec["keyboard_id"] < 0
    assert int(root.attrib["group"]) == spec["group"] == 126
    assert int(root.attrib["maxout"]) == spec["maxout"]
    layouts = root.findall("./layouts/layout")
    assert len(layouts) == 1 and layouts[0].attrib["first"] == "0" and layouts[0].attrib["last"] == "17"
    assert "JIS" not in (ROOT / "us-altgr-intl.keylayout").read_text(encoding="utf-8").replace("JIS ranges intentionally absent", "")

    selectors = []
    for select in root.findall("./modifierMap/keyMapSelect"):
        for modifier in select.findall("modifier"):
            selectors.append((int(select.attrib["mapIndex"]), modifier.attrib["keys"]))
    modifier_combinations = 0
    for left_shift, right_shift, left_option, right_option, left_control, right_control, command, caps in itertools.product((False, True), repeat=8):
        shift = left_shift or right_shift
        option = left_option or right_option
        control = left_control or right_control
        state = {"anyShift": shift, "anyOption": option, "anyControl": control, "command": command, "caps": caps}
        selected = int(root.find("./modifierMap").attrib["defaultIndex"])
        for index, keys in selectors:
            if modifier_matches(keys, state):
                selected = index
        expected = (11 if shift else 10) if command else ((9 if shift else 8) if control else ((7 if shift else 6) if option and caps else ((3 if shift else 2) if option else ((5 if shift else 4) if caps else (1 if shift else 0)))))
        assert selected == expected, (state, selected, expected)
        modifier_combinations += 1
    assert modifier_combinations == 256

    keymaps = root.findall("./keyMapSet/keyMap")
    assert [int(node.attrib["index"]) for node in keymaps] == list(range(12))
    code_sets = [{int(key.attrib["code"]) for key in node.findall("key")} for node in keymaps]
    assert all(codes == code_sets[0] for codes in code_sets)

    actions = {action.attrib["id"]: action for action in root.findall("./actions/action")}
    referenced_actions = {key.attrib["action"] for keymap in keymaps for key in keymap.findall("key") if "action" in key.attrib}
    assert referenced_actions <= actions.keys()
    assert all("action" not in key.attrib for keymap in keymaps[8:12] for key in keymap.findall("key"))
    for action_id, action in actions.items():
        states = [when.attrib["state"] for when in action.findall("when")]
        assert len(states) == len(set(states)) and "none" in states, action_id
    next_states = {when.attrib["next"] for action in actions.values() for when in action.findall("when") if "next" in when.attrib}
    terminator_states = {when.attrib["state"] for when in root.findall("./terminators/when")}
    assert next_states <= terminator_states

    records = derivation["output_records"]
    assert len(records) == len(keymaps) * len(code_sets[0])
    assert all(record.get("anchors") for record in records)
    for token, branches in derivation["actions"].items():
        assert set(branches) == set(derivation["action_branch_trace"][token])
    assert set(derivation["terminators"]) == set(derivation["dead_keys"]["terminator_trace"])

    unicode_cases = {}
    for line in (ROOT / "sources/unicode_UnicodeData.txt").read_text(encoding="utf-8").splitlines():
        fields = line.split(";")
        if len(fields) >= 14:
            unicode_cases[int(fields[0], 16)] = {
                "uppercase": int(fields[12], 16) if fields[12] else None,
                "lowercase": int(fields[13], 16) if fields[13] else None,
            }
    by_map_key = {(record["map_index"], record["key"]): record for record in records}
    for key, key_spec in spec["keys"].items():
        assert by_map_key[(0, key)]["keysym"] == key_spec["levels"][0]["keysym"]
        assert by_map_key[(1, key)]["keysym"] == key_spec["levels"][1]["keysym"]
        assert by_map_key[(2, key)]["keysym"] == key_spec["levels"][2]["keysym"]
        assert by_map_key[(3, key)]["keysym"] == key_spec["levels"][3]["keysym"]
        altgr = key_spec["levels"][2]["character"] if "character" in key_spec["levels"][2] else None
        shift_altgr = key_spec["levels"][3]["character"] if "character" in key_spec["levels"][3] else None
        altgr_pair = (
            altgr is not None and shift_altgr is not None
            and len(altgr) == len(shift_altgr) == 1
            and unicode_cases[ord(altgr)]["uppercase"] == ord(shift_altgr)
            and unicode_cases[ord(shift_altgr)]["lowercase"] == ord(altgr)
        )
        assert by_map_key[(6, key)]["keysym"] == key_spec["levels"][3 if altgr_pair else 2]["keysym"]
        assert by_map_key[(7, key)]["keysym"] == key_spec["levels"][2 if altgr_pair else 3]["keysym"]
        assert by_map_key[(8, key)]["keysym"] == key_spec["levels"][0]["keysym"]
        assert by_map_key[(9, key)]["keysym"] == key_spec["levels"][1]["keysym"]
        assert by_map_key[(10, key)]["keysym"] == key_spec["levels"][0]["keysym"]
        assert by_map_key[(11, key)]["keysym"] == key_spec["levels"][1]["keysym"]
        base = key_spec["levels"][0]["character"]
        shifted = key_spec["levels"][1]["character"]
        ascii_pair = len(base) == 1 and "a" <= base <= "z" and shifted == base.upper()
        assert by_map_key[(8, key)]["output"] == (chr(ord(base) - 0x60) if ascii_pair else base)
        assert by_map_key[(9, key)]["output"] == (chr(ord(base) - 0x60) if ascii_pair else shifted)

    # Observable dead-key contract: AltGr-apostrophe enters acute state and e completes é.
    acute = actions["a_dead_acute"]
    acute_start = next(when.attrib["next"] for when in acute.findall("when") if when.attrib["state"] == "none")
    e_action = actions["a_e"]
    e_result = next(when.attrib.get("output") for when in e_action.findall("when") if when.attrib["state"] == acute_start)
    assert e_result == "é"
    assert by_map_key[(2, "AC11")]["action"] == "a_dead_acute"

    # Exact pinned-Compose probes: preserve supported all-dead prefixes and
    # explicit results, concatenate full-prefix spacing terminators, and never
    # invent an NFC-only rule.
    compose_source = (ROOT / "sources/libX11_Compose.txt").read_text(encoding="utf-8")
    assert "<dead_circumflex> <dead_belowdot> <a>" in compose_source
    assert "<dead_tilde> <dead_diaeresis> <Greek_iota>" in compose_source
    assert not re.search(r"<dead_acute>\s+<Oslash>\s*:", compose_source)
    combined_belowdot = "s_dead_circumflex__dead_belowdot"
    combined_tilde_diaeresis = "s_dead_tilde__dead_diaeresis"
    belowdot_action = actions["a_dead_belowdot"]
    assert any(when.attrib == {"state": "s_dead_circumflex", "next": combined_belowdot} for when in belowdot_action.findall("when"))
    diaeresis_action = actions["a_dead_diaeresis"]
    assert any(when.attrib == {"state": "s_dead_tilde", "next": combined_tilde_diaeresis} for when in diaeresis_action.findall("when"))
    assert any(when.attrib == {"state": combined_belowdot, "output": "ậ"} for when in actions["a_a"].findall("when"))
    terminators = {when.attrib["state"]: when.attrib["output"] for when in root.findall("./terminators/when")}
    assert terminators[combined_belowdot] == "^̣"
    assert terminators[combined_tilde_diaeresis] == '~"'
    assert "a_Oslash" not in actions
    oslash = keymaps[3].find('./key[@code="37"]')
    assert oslash is not None and oslash.attrib == {"code": "37", "output": "Ø"}
    assert not any(entry.get("source") == "unicode_UnicodeData" for entry in derivation["dead_keys"]["transitions"])
    assert not any(entry.get("sequence") == ["dead_acute", "Oslash"] for entry in derivation["dead_keys"]["transitions"])

    # Caps+AltGr swaps genuine Unicode lower/upper level3/4 pairs only.
    assert by_map_key[(6, "AD01")]["keysym"] == "Adiaeresis"
    assert by_map_key[(7, "AD01")]["keysym"] == "adiaeresis"
    assert by_map_key[(6, "AE01")]["keysym"] == "onesuperior"
    assert by_map_key[(7, "AE01")]["keysym"] == "exclamdown"

    # Shortcut maps are direct, so they cannot run Compose branches.
    assert by_map_key[(8, "AC01")]["output"] == "\x01"
    assert by_map_key[(9, "AC01")]["output"] == "\x01"
    assert by_map_key[(9, "AE01")]["output"] == "!"
    assert by_map_key[(10, "AC01")]["output"] == "a"
    assert by_map_key[(11, "AC01")]["output"] == "A"
    control_a = keymaps[8].find('./key[@code="0"]')
    command_a = keymaps[10].find('./key[@code="0"]')
    command_shift_a = keymaps[11].find('./key[@code="0"]')
    assert control_a is not None and control_a.attrib.get("output") == chr(0xE001)
    assert command_a is not None and command_a.attrib == {"code": "0", "output": "a"}
    assert command_shift_a is not None and command_shift_a.attrib == {"code": "0", "output": "A"}
    def dispatch_direct(state: str, key: ET.Element) -> tuple[str, str]:
        return terminators[state] + key.attrib["output"], "none"
    assert dispatch_direct(acute_start, control_a) == ("'" + chr(0xE001), "none")
    assert dispatch_direct(acute_start, command_a) == ("'a", "none")
    assert dispatch_direct(acute_start, oslash) == ("'Ø", "none")

    print(f"verified {len(spec['keys'])} XKB keys, {len(actions)} actions, {len(terminator_states)} states, and {modifier_combinations} physical modifier combinations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
