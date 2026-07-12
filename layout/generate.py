#!/usr/bin/env python3
"""Generate a macOS XML keyboard layout from pinned public sources only."""
from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCK = ROOT / "source-lock.json"
OUTPUTS = {
    "layout": ROOT / "us-altgr-intl.keylayout",
    "spec": ROOT / "layout-spec.json",
    "derivation": ROOT / "derivation.json",
}
NAME = "us-altgr-intl"
ID_SEED = b"us-altgr-intl\0xkeyboard-config-2.48\0clean-room-v1"
KEYBOARD_ID = -(int.from_bytes(hashlib.sha256(ID_SEED).digest()[:4], "big") & 0x7FFFFFFF or 1)

# Decimal virtual keycodes transcribed by physical position from Apple,
# Inside Macintosh: Macintosh Toolbox Essentials, Figure 2-10. XKB names
# follow the public xkeyboard-config symbols convention.
APPLE_KEYCODES = {
    "TLDE": 50,
    "AE01": 18, "AE02": 19, "AE03": 20, "AE04": 21, "AE05": 23,
    "AE06": 22, "AE07": 26, "AE08": 28, "AE09": 25, "AE10": 29,
    "AE11": 27, "AE12": 24,
    "AD01": 12, "AD02": 13, "AD03": 14, "AD04": 15, "AD05": 17,
    "AD06": 16, "AD07": 32, "AD08": 34, "AD09": 31, "AD10": 35,
    "AD11": 33, "AD12": 30,
    "AC01": 0, "AC02": 1, "AC03": 2, "AC04": 3, "AC05": 5,
    "AC06": 4, "AC07": 38, "AC08": 40, "AC09": 37, "AC10": 41,
    "AC11": 39, "BKSL": 42,
    "AB01": 6, "AB02": 7, "AB03": 8, "AB04": 9, "AB05": 11,
    "AB06": 45, "AB07": 46, "AB08": 43, "AB09": 47, "AB10": 44,
    "LSGT": 10,
}

# Essential non-symbol keys. Keycodes use the same Apple Figure 2-10.
# Control outputs are ASCII control-code facts; keypad labels/outputs follow
# the figure's keypad positions. They are not imported from another layout.
SPECIAL_KEYS = {
    "RTRN": (36, "Return", "\r"), "TAB": (48, "Tab", "\t"),
    "SPCE": (49, "space", " "), "BKSP": (51, "Delete", "\b"),
    "ESC": (53, "Escape", "\x1b"),
    "LEFT": (123, "Left Arrow", "\x1c"), "RGHT": (124, "Right Arrow", "\x1d"),
    "DOWN": (125, "Down Arrow", "\x1f"), "UP": (126, "Up Arrow", "\x1e"),
    "KPDL": (65, "Keypad Decimal", "."), "KPMU": (67, "Keypad Multiply", "*"),
    "KPAD": (69, "Keypad Plus", "+"),
    "KPDV": (75, "Keypad Divide", "/"), "KPEN": (76, "Keypad Enter", "\r"),
    "KPSU": (78, "Keypad Minus", "-"), "KPEQ": (81, "Keypad Equals", "="),
    "KP0": (82, "Keypad 0", "0"), "KP1": (83, "Keypad 1", "1"),
    "KP2": (84, "Keypad 2", "2"), "KP3": (85, "Keypad 3", "3"),
    "KP4": (86, "Keypad 4", "4"), "KP5": (87, "Keypad 5", "5"),
    "KP6": (88, "Keypad 6", "6"), "KP7": (89, "Keypad 7", "7"),
    "KP8": (91, "Keypad 8", "8"), "KP9": (92, "Keypad 9", "9"),
}
APPLE_ANCHOR = {
    "source": "apple-virtual-keycodes",
    "location": "Event Manager chapter, Figure 2-10 (virtual key codes)",
}
CHARACTER_ANCHOR = {
    "source": "unicode-data",
    "location": "Unicode 17.0.0 scalar/control assignments; TN2056 defines output as UTF-16",
}


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_and_verify_sources() -> tuple[dict, dict[str, bytes]]:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    data = {}
    for source in lock["sources"]:
        if source.get("reference_only"):
            if source.get("redistribute") is not False:
                raise SystemExit(f"reference-only source must set redistribute=false: {source['id']}")
            continue
        path = ROOT / source["path"]
        blob = path.read_bytes()
        actual = sha256(blob)
        if actual != source["sha256"]:
            raise SystemExit(f"source hash mismatch: {source['id']}: {actual}")
        data[source["id"]] = blob
    return lock, data


def section(text: str, name: str) -> tuple[str, int]:
    match = re.search(r'(?m)^xkb_symbols\s+"' + re.escape(name) + r'"\s*\{', text)
    if not match:
        raise ValueError(f"missing XKB section {name}")
    start = match.end()
    depth = 1
    end = start
    while end < len(text) and depth:
        if text[end] == "{":
            depth += 1
        elif text[end] == "}":
            depth -= 1
        end += 1
    if depth:
        raise ValueError(f"unterminated XKB section {name}")
    return text[start:end - 1], text.count("\n", 0, match.start()) + 1


def parse_xkb(text: str) -> tuple[dict[str, list[str]], dict[str, object]]:
    intl, intl_line = section(text, "intl")
    altgr, altgr_line = section(text, "altgr-intl")
    if not re.search(r'include\s+"us\(intl\)"', altgr):
        raise ValueError("altgr-intl no longer includes us(intl)")
    pattern = re.compile(r'(?m)^\s*key\s+<([A-Z0-9]+)>\s*\{\s*\[([^]]+)\]\s*\}\s*;')

    def keys(body: str, base_line: int) -> tuple[dict[str, list[str]], dict[str, int]]:
        result, lines = {}, {}
        for match in pattern.finditer(body):
            name = match.group(1)
            levels = [item.strip() for item in match.group(2).split(",")]
            if len(levels) != 4:
                raise ValueError(f"{name} has {len(levels)} levels, expected 4")
            result[name] = levels
            lines[name] = base_line + body.count("\n", 0, match.start())
        return result, lines

    result, inherited_lines = keys(intl, intl_line)
    overrides, override_lines = keys(altgr, altgr_line)
    if set(overrides) != {"TLDE", "AC11", "AE01", "AD04", "AC04", "AB02", "AB04", "AB05", "AE06", "AE07", "AE08"}:
        raise ValueError(f"unexpected altgr-intl override set: {sorted(overrides)}")
    result.update(overrides)
    missing = set(result) - set(APPLE_KEYCODES)
    if missing:
        raise ValueError(f"no publicly anchored Apple keycode for {sorted(missing)}")
    traces = {}
    for key in sorted(result):
        line = override_lines.get(key, inherited_lines[key])
        traces[key] = {
            "source": "xkeyboard-config-symbols-us",
            "section": "altgr-intl override" if key in overrides else "intl inherited",
            "line": line,
            "levels": result[key],
        }
    return result, {
        "include": {"from": "altgr-intl", "target": "us(intl)", "line": altgr_line + 2},
        "keys": traces,
    }


def parse_keysyms(text: str) -> dict[str, dict[str, object]]:
    records = {}
    rx = re.compile(r'(?m)^#define\s+XK_([A-Za-z0-9_]+)\s+(0x[0-9a-fA-F]+)(?:\s+/\*\s*U\+([0-9A-Fa-f]+)\s+([^*]+?)\s*\*/)?')
    for match in rx.finditer(text):
        name, raw, unicode_hex, unicode_name = match.groups()
        value = int(raw, 16)
        cp = int(unicode_hex, 16) if unicode_hex else None
        if cp is None and value <= 0xFF:
            cp = value
        elif cp is None and 0x01000100 <= value <= 0x0110FFFF:
            cp = value - 0x01000000
        records[name] = {
            "value": value,
            "codepoint": cp,
            "unicode_name": unicode_name.strip() if unicode_name else None,
            "line": text.count("\n", 0, match.start()) + 1,
        }
    return records


def symbol_char(name: str, keysyms: dict[str, dict[str, object]]) -> str:
    record = keysyms.get(name)
    if not record or record["codepoint"] is None:
        raise ValueError(f"literal keysym cannot be resolved publicly: {name}")
    cp = int(record["codepoint"])
    if not 0 <= cp <= 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
        raise ValueError(f"invalid Unicode scalar for keysym {name}: U+{cp:04X}")
    return chr(cp)


def parse_ucd(text: str) -> tuple[dict[int, dict[str, object]], dict[tuple[int, int], int]]:
    records, pairs = {}, {}
    for line_no, line in enumerate(text.splitlines(), 1):
        fields = line.split(";")
        if len(fields) < 6:
            continue
        cp = int(fields[0], 16)
        decomp = fields[5]
        seq = [] if not decomp or decomp.startswith("<") else [int(x, 16) for x in decomp.split()]
        records[cp] = {
            "name": fields[1],
            "ccc": int(fields[3]),
            "decomposition": seq,
            "uppercase": int(fields[12], 16) if len(fields) > 12 and fields[12] else None,
            "lowercase": int(fields[13], 16) if len(fields) > 13 and fields[13] else None,
            "line": line_no,
        }
        if len(seq) == 2:
            pairs[(seq[0], seq[1])] = cp
    return records, pairs


def parse_exclusions(text: str) -> set[int]:
    result = set()
    for line in text.splitlines():
        token = line.split("#", 1)[0].strip()
        if token:
            result.add(int(token, 16))
    return result


def decode_compose_string(raw: str) -> str:
    # Compose.pre quoted strings use C-style byte escapes; direct UTF-8 is retained.
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith("\\x"):
            return chr(int(token[2:], 16))
        if len(token) > 1 and token[1:].isdigit():
            return chr(int(token[1:], 8))
        return {r'\\"': '"', r'\\\\': '\\', r'\\n': '\n', r'\\t': '\t'}.get(token, token[1:])
    return re.sub(r'\\x[0-9A-Fa-f]{2}|\\[0-7]{1,3}|\\["\\nt]', replace, raw)


def parse_compose(text: str) -> list[dict[str, object]]:
    rx = re.compile(r'^\s*((?:<[A-Za-z0-9_]+>\s*)+)\s*:\s*"((?:[^"\\]|\\.)*)"', re.M)
    entries = []
    for match in rx.finditer(text):
        sequence = re.findall(r'<([A-Za-z0-9_]+)>', match.group(1))
        entries.append({
            "sequence": sequence,
            "output": decode_compose_string(match.group(2)),
            "line": text.count("\n", 0, match.start()) + 1,
        })
    if not entries:
        raise ValueError("no Compose entries parsed")
    return entries


def dead_machine(layout: dict[str, list[str]], keysyms: dict[str, dict[str, object]], compose: list[dict[str, object]], ucd: dict[int, dict[str, object]], exclusions: set[int]) -> tuple[dict, dict]:
    symbols = {symbol for levels in layout.values() for symbol in levels}
    dead = sorted(symbol for symbol in symbols if symbol.startswith("dead_"))
    literal_symbols = sorted(symbols - set(dead))
    token_chars = {symbol: symbol_char(symbol, keysyms) for symbol in literal_symbols}
    token_chars["space"] = " "
    available = set(token_chars) | set(dead)

    chosen: dict[tuple[str, ...], dict[str, object]] = {}
    forced_prefix_support: dict[tuple[str, ...], list[dict[str, object]]] = {}
    for entry in compose:
        seq = tuple(entry["sequence"])
        if seq and seq[0] in dead and set(seq).issubset(available):
            previous = chosen.get(seq)
            if previous and previous["output"] != entry["output"]:
                raise ValueError(f"conflicting Compose sequence {seq}")
            unicode_lines = []
            for char in entry["output"]:
                if ord(char) not in ucd:
                    raise ValueError(f"Compose output missing from pinned UnicodeData: U+{ord(char):04X}")
                unicode_lines.append(ucd[ord(char)]["line"])
            chosen[seq] = {
                "output": entry["output"],
                "source": "libX11_Compose",
                "line": entry["line"],
                "unicode_data_lines": unicode_lines,
            }
        if seq and seq[0] in dead:
            prefix = []
            for token in seq:
                if token not in dead:
                    break
                prefix.append(token)
                if len(prefix) > 1 and len(prefix) < len(seq):
                    forced_prefix_support.setdefault(tuple(prefix), []).append({
                        "sequence": list(seq),
                        "source": "libX11_Compose",
                        "line": entry["line"],
                    })

    # Infer each dead key's combining mark from Compose results plus UCD canonical
    # decompositions, rather than embedding a private dead-key table.
    inferred_marks = {}
    for dead_name in dead:
        votes = Counter()
        evidence = []
        for seq, record in chosen.items():
            if len(seq) != 2 or seq[0] != dead_name or seq[1] not in token_chars or len(record["output"]) != 1:
                continue
            out_cp = ord(record["output"])
            decomposition = ucd.get(out_cp, {}).get("decomposition", [])
            base = token_chars[seq[1]]
            if len(base) == 1 and len(decomposition) == 2 and decomposition[0] == ord(base):
                votes[decomposition[1]] += 1
                evidence.append({"compose_line": record["line"], "unicode_data_line": ucd[out_cp]["line"]})
        if not votes:
            raise ValueError(f"cannot infer combining mark for {dead_name} from Compose + UCD")
        best, count = votes.most_common(1)[0]
        if len(votes) > 1 and votes.most_common(2)[1][1] == count:
            raise ValueError(f"ambiguous combining mark for {dead_name}: {votes}")
        inferred_marks[dead_name] = {"codepoint": best, "votes": count, "evidence": evidence[:8]}


    # Retain reachable prefixes plus every all-dead prefix supported by Compose,
    # even when its eventual terminal keysym is unavailable on this layout.
    prefixes = {seq[:length] for seq in chosen for length in range(1, len(seq))}
    prefixes.update(forced_prefix_support)
    ambiguous = sorted(prefix for prefix in prefixes if prefix in chosen)
    if ambiguous:
        raise ValueError(f"available Compose sequence is both complete and a prefix: {ambiguous}")
    state_id = lambda seq: "s_" + "__".join(seq)
    transitions: dict[str, dict[str, dict[str, str]]] = {token: {} for token in available}
    for dead_name in dead:
        transitions[dead_name]["none"] = {"next": state_id((dead_name,))}
    trace_transitions = []
    for seq, record in sorted(chosen.items()):
        prior, token = seq[:-1], seq[-1]
        if not prior:
            continue
        value = {"output": record["output"]}
        transitions[token][state_id(prior)] = value
        trace_transitions.append({"sequence": list(seq), **record, "state": state_id(prior), "action_token": token})
    for prefix in sorted(prefixes):
        if len(prefix) > 1:
            prior, token = prefix[:-1], prefix[-1]
            transitions[token][state_id(prior)] = {"next": state_id(prefix)}
            support = [
                {"sequence": list(seq), "source": record["source"], "line": record["line"]}
                for seq, record in sorted(chosen.items())
                if seq[:len(prefix)] == prefix
            ] + forced_prefix_support.get(prefix, [])
            trace_transitions.append({
                "sequence": list(prefix),
                "state": state_id(prior),
                "action_token": token,
                "next": state_id(prefix),
                "source": "prefix mechanically derived from selected public sequences",
                "support": support,
            })

    # Drop literal actions that have no state-specific branch. Dead actions remain.
    actions = {}
    for token, whens in sorted(transitions.items()):
        if token in token_chars and len(whens) == 0:
            continue
        ordered = {}
        if token in token_chars:
            ordered["none"] = {"output": token_chars[token]}
        ordered.update(dict(sorted(whens.items())))
        actions[token] = ordered

    # A single state's terminator is its explicit Compose spacing form.
    # A combined all-dead state concatenates every component spacing form;
    # explicit full-sequence results remain normal action branches, not fallbacks.
    terminators = {}
    terminator_trace = {}
    single_terminators = {}
    single_trace = {}
    for dead_name in dead:
        preferred = chosen.get((dead_name, "space"))
        sequence = (dead_name, "space")
        if preferred is None:
            preferred = chosen.get((dead_name, dead_name))
            sequence = (dead_name, dead_name)
        if preferred is None:
            raise ValueError(f"no explicit Compose spacing form for {dead_name}")
        single_terminators[dead_name] = preferred["output"]
        single_trace[dead_name] = {
            "output": preferred["output"],
            "sequence": list(sequence),
            "source": preferred["source"],
            "line": preferred["line"],
        }
    for prefix in sorted(prefixes):
        state = state_id(prefix)
        if len(prefix) == 1:
            terminators[state] = single_terminators[prefix[0]]
            terminator_trace[state] = single_trace[prefix[0]]
            continue
        if not all(token in dead for token in prefix):
            raise ValueError(f"non-dead combined prefix has no deterministic terminator: {prefix}")
        output = "".join(single_terminators[token] for token in prefix)
        terminators[state] = output
        terminator_trace[state] = {
            "output": output,
            "source": "ordered concatenation of explicit Compose spacing forms",
            "prefix": list(prefix),
            "components": [single_trace[token] for token in prefix],
        }

    return {
        "dead_symbols": dead,
        "token_chars": token_chars,
        "actions": actions,
        "terminators": terminators,
    }, {
        "combining_mark_inference": inferred_marks,
        "transitions": trace_transitions,
        "compose_entries_considered": len(compose),
        "terminator_trace": terminator_trace,
        "compose_entries_selected": len(chosen),
        "all_dead_prefixes_retained": len(forced_prefix_support),
        "composition_exclusions_pinned": len(exclusions),
    }




def attr_escape(value: object) -> str:
    text = str(value)
    result = []
    for char in text:
        cp = ord(char)
        if char == "&": result.append("&amp;")
        elif char == '"': result.append("&quot;")
        elif char == "<": result.append("&lt;")
        elif char == ">": result.append("&gt;")
        elif cp < 0x20 or cp == 0x7F: result.append(f"&#x{cp:04X};")
        else: result.append(char)
    return "".join(result)


def render_xml(layout: dict[str, list[str]], machine: dict[str, object], keysyms: dict[str, dict[str, object]], ucd: dict[int, dict[str, object]]) -> tuple[bytes, list[dict[str, object]]]:
    # Maps 0-7 are text entry, including Caps+AltGr pair-aware maps.
    # Maps 8-9 emit direct Control base/Shift; 10-11 emit direct Command identity.
    modifier_rows = [
        (0, ""), (1, "anyShift"), (4, "caps"), (5, "caps anyShift"),
        (2, "anyOption"), (3, "anyOption anyShift"),
        (6, "anyOption caps"), (7, "anyOption anyShift caps"),
        (8, "anyControl anyOption? caps?"),
        (9, "anyControl anyShift anyOption? caps?"),
        (10, "command anyOption? anyControl? caps?"),
        (11, "command anyShift anyOption? anyControl? caps?"),
    ]
    direct_outputs = [
        value["output"]
        for whens in machine["actions"].values()
        for value in whens.values()
        if "output" in value
    ] + [row[2] for row in SPECIAL_KEYS.values()]
    utf16_units = lambda text: len(text.encode("utf-16-be")) // 2
    max_direct = max(map(utf16_units, direct_outputs))
    max_terminator = max(map(utf16_units, machine["terminators"].values()))
    # An unmatched state emits its terminator and then the current key result.
    maxout = max_direct + max_terminator
    lines = [
        '<?xml version="1.1" encoding="UTF-8"?>',
        '<!-- Canonical behavior: xkeyboard-config 2.48 us(altgr-intl), independently generated.',
        '     X.Org, Unicode, and Apple are source references only; no endorsement is claimed. -->',
        f'<keyboard group="126" id="{KEYBOARD_ID}" name="{NAME}" maxout="{maxout}">',
        '  <layouts>',
        '    <!-- TN2056 ANSI range 0-17; ISO shares the ANSI map. JIS ranges intentionally absent. -->',
        '    <layout first="0" last="17" modifiers="modifiers" mapSet="ANSI"/>',
        '  </layouts>',
        '  <modifierMap id="modifiers" defaultIndex="0">',
    ]
    for index, keys in modifier_rows:
        lines.append(f'    <keyMapSelect mapIndex="{index}">')
        if keys:
            lines.append(f'      <modifier keys="{keys}"/>')
        else:
            lines.append('      <modifier keys=""/>')
        lines.append('    </keyMapSelect>')
    lines += ['  </modifierMap>', '  <keyMapSet id="ANSI">']

    output_trace = []
    action_tokens = set(machine["actions"])
    for map_index in range(12):
        lines.append(f'    <keyMap index="{map_index}">')
        for key_name, code in sorted(APPLE_KEYCODES.items(), key=lambda item: item[1]):
            levels = layout[key_name]
            chars = [symbol_char(symbol, keysyms) if not symbol.startswith("dead_") else None for symbol in levels]
            base_char, shift_char, altgr_char, shift_altgr_char = chars
            ascii_case_pair = (
                base_char is not None and shift_char is not None
                and len(base_char) == 1 and "a" <= base_char <= "z"
                and shift_char == chr(ord(base_char) - 32)
            )
            altgr_case_pair = (
                altgr_char is not None and shift_altgr_char is not None
                and len(altgr_char) == len(shift_altgr_char) == 1
                and ucd.get(ord(altgr_char), {}).get("uppercase") == ord(shift_altgr_char)
                and ucd.get(ord(shift_altgr_char), {}).get("lowercase") == ord(altgr_char)
            )
            direct_shortcut = map_index >= 8
            if map_index < 4:
                level_index = map_index
            elif map_index == 4:
                level_index = 1 if ascii_case_pair else 0
            elif map_index == 5:
                level_index = 0 if ascii_case_pair else 1
            elif map_index == 6:
                level_index = 3 if altgr_case_pair else 2
            elif map_index == 7:
                level_index = 2 if altgr_case_pair else 3
            elif map_index in (8, 10):
                level_index = 0
            else:
                level_index = 1
            symbol = levels[level_index]
            if not direct_shortcut and (symbol.startswith("dead_") or symbol in action_tokens):
                action = "a_" + symbol
                lines.append(f'      <key code="{code}" action="{action}"/>')
                rendered = {"action": action}
            else:
                output = symbol_char(symbol, keysyms)
                rendered = {"output": output}
                if map_index in (8, 9) and ascii_case_pair:
                    output = chr(ord(base_char) - ord("a") + 1)
                    rendered = {
                        "output": output,
                        "control_derivation": {
                            "input": base_char,
                            "formula": "ASCII lowercase ordinal - 0x60",
                            "unicode": f"U+{ord(output):04X}",
                            "sources": ["apple-virtual-keycodes", "unicode-data"],
                        },
                    }
                lines.append(f'      <key code="{code}" output="{attr_escape(output)}"/>')
            routing_kind = "control-direct" if map_index in (8, 9) else ("command-direct" if map_index in (10, 11) else "text")
            output_trace.append({
                "map_index": map_index,
                "routing_kind": routing_kind,
                "key": key_name,
                "keycode": code,
                "xkb_level": level_index + 1,
                "keysym": symbol,
                "altgr_case_pair": altgr_case_pair if map_index in (6, 7) else None,
                **rendered,
            })
        for special, (code, label, output) in sorted(SPECIAL_KEYS.items(), key=lambda item: item[1][0]):
            if map_index < 8 and special == "SPCE" and "space" in action_tokens:
                lines.append(f'      <key code="{code}" action="a_space"/>')
                rendered = {"action": "a_space"}
            else:
                lines.append(f'      <key code="{code}" output="{attr_escape(output)}"/>')
                rendered = {"output": output}
            routing_kind = "control-direct" if map_index in (8, 9) else ("command-direct" if map_index in (10, 11) else "text")
            output_trace.append({
                "map_index": map_index,
                "routing_kind": routing_kind,
                "key": special,
                "keycode": code,
                "label": label,
                **rendered,
            })
        lines.append('    </keyMap>')
    lines += ['  </keyMapSet>', '  <actions>']
    for token, whens in sorted(machine["actions"].items()):
        lines.append(f'    <action id="a_{token}">')
        for state, value in whens.items():
            attrs = [f'state="{attr_escape(state)}"']
            if "next" in value: attrs.append(f'next="{attr_escape(value["next"])}"')
            if "output" in value: attrs.append(f'output="{attr_escape(value["output"])}"')
            lines.append('      <when ' + ' '.join(attrs) + '/>')
        lines.append('    </action>')
    lines += ['  </actions>', '  <terminators>']
    for state, output in sorted(machine["terminators"].items()):
        lines.append(f'    <when state="{attr_escape(state)}" output="{attr_escape(output)}"/>')
    lines += ['  </terminators>', '</keyboard>', '']
    return "\n".join(lines).encode("utf-8"), output_trace


def build() -> dict[str, bytes]:
    lock, sources = load_and_verify_sources()
    xkb_text = sources["xkeyboard-config-symbols-us"].decode("utf-8")
    layout, xkb_trace = parse_xkb(xkb_text)
    keysyms = parse_keysyms(sources["xorgproto-keysymdef"].decode("utf-8"))
    for symbol in {s for levels in layout.values() for s in levels if not s.startswith("dead_")}:
        symbol_char(symbol, keysyms)
    ucd, _composition_pairs = parse_ucd(sources["unicode-data"].decode("utf-8"))
    exclusions = parse_exclusions(sources["unicode-composition-exclusions"].decode("utf-8"))
    normalization_props = sources["unicode-derived-normalization-properties"].decode("utf-8")
    if "DerivedNormalizationProps-17.0.0.txt" not in normalization_props or "; NFC_QC;" not in normalization_props:
        raise ValueError("pinned Unicode 17 normalization properties failed identity checks")
    compose = parse_compose(sources["libx11-compose"].decode("utf-8"))
    machine, dead_trace = dead_machine(layout, keysyms, compose, ucd, exclusions)
    xml, output_trace = render_xml(layout, machine, keysyms, ucd)

    resolved_keys = {}
    selected_literals = {s for levels in layout.values() for s in levels if not s.startswith("dead_")} | {"space"}
    keysym_resolution = {
        symbol: {
            "source": "xorgproto-keysymdef",
            "line": keysyms[symbol]["line"],
            "keysym_value": f"0x{int(keysyms[symbol]['value']):X}",
            "unicode": f"U+{ord(symbol_char(symbol, keysyms)):04X}",
        }
        for symbol in sorted(selected_literals)
    }
    for key, levels in sorted(layout.items()):
        level_records = []
        for index, symbol in enumerate(levels, 1):
            record = {"keysym": symbol, "xkb_source": xkb_trace["keys"][key], "level": index}
            if symbol.startswith("dead_"):
                record["dead"] = True
            else:
                record.update({
                    "unicode": f"U+{ord(symbol_char(symbol, keysyms)):04X}",
                    "character": symbol_char(symbol, keysyms),
                    "keysym_source": keysym_resolution[symbol],
                })
            level_records.append(record)
        resolved_keys[key] = {
            "apple_keycode": APPLE_KEYCODES[key],
            "apple_keycode_source": APPLE_ANCHOR,
            "levels": level_records,
        }
    spec = {
        "schema": 1,
        "name": NAME,
        "keyboard_id": KEYBOARD_ID,
        "keyboard_id_derivation": {"algorithm": "negative low-31-bit big-endian SHA-256 prefix; zero becomes -1", "seed_utf8_hex": ID_SEED.hex(), "sha256": sha256(ID_SEED)},
        "group": 126,
        "group_derivation": {"source": "apple-tn2056", "location": "XML File Structure: negative-id Unicode keyboards are assigned group 126"},
        "canonical_behavior": "xkeyboard-config 2.48 us(altgr-intl) mechanically expanded as us(intl) plus overrides",
        "hardware": {"supported": ["ANSI", "ISO"], "apple_type_range": [0, 17], "unsupported": ["JIS"]},
        "maxout": int(re.search(rb'maxout="(\d+)"', xml).group(1)),
        "maxout_derivation": {"source": "apple-tn2056", "location": "keyboard maxout is maximum UTF-16 values from one keypress", "method": "maximum generated direct output plus maximum state-termination fallback, measured in UTF-16 code units"},
        "routing": {
            "base": 0, "shift": 1, "option_or_altgr": 2, "shift_option_or_altgr": 3, "caps": 4, "shift_caps": 5,
            "caps_altgr": 6, "caps_shift_altgr": 7,
            "control_base_direct": 8, "control_shift_direct": 9, "command_base_direct": 10, "command_shift_direct": 11,
            "policy": "Either Option acts as AltGr when Command and Control are absent. Caps+AltGr swaps only Unicode 17 lower/upper level3/4 pairs; Caps+Shift+AltGr inverts those pairs while nonletters retain physical AltGr levels. Control emits direct ASCII C0 for US letters and direct base/physical-Shift US identity for nonletters, ignoring Caps/Option. Command has precedence, ignores Caps/Option/Control, and emits direct XKB base or physical-Shift identity. Shortcut maps contain no actions.",
        },
        "keys": resolved_keys,
        "special_keys": {name: {"apple_keycode": row[0], "label": row[1], "unicode": [f"U+{ord(ch):04X}" for ch in row[2]], "anchors": [APPLE_ANCHOR, CHARACTER_ANCHOR]} for name, row in sorted(SPECIAL_KEYS.items())},
        "dead_symbols": machine["dead_symbols"],
        "source_lock_sha256": sha256(LOCK.read_bytes()),
    }
    for record in output_trace:
        key = record["key"]
        if key in xkb_trace["keys"]:
            anchors = [APPLE_ANCHOR, {
                "source": "xkeyboard-config-symbols-us",
                "line": xkb_trace["keys"][key]["line"],
                "section": xkb_trace["keys"][key]["section"],
            }]
            if not record["keysym"].startswith("dead_"):
                anchors.append(keysym_resolution[record["keysym"]])
            record["anchors"] = anchors
        else:
            record["anchors"] = [APPLE_ANCHOR, CHARACTER_ANCHOR]
    transition_index = {
        (entry["action_token"], entry["state"]): entry
        for entry in dead_trace["transitions"]
    }
    action_branch_trace = {}
    for token, whens in machine["actions"].items():
        branches = {}
        for state, value in whens.items():
            if state != "none":
                branches[state] = transition_index[(token, state)]
            elif token.startswith("dead_"):
                placements = [
                    {"key": key, "line": info["line"], "section": info["section"], "levels": info["levels"]}
                    for key, info in xkb_trace["keys"].items()
                    if token in info["levels"]
                ]
                branches[state] = {"source": "xkeyboard-config-symbols-us", "placements": placements, "derivation": "dead keys enter their named prefix state"}
            else:
                branches[state] = keysym_resolution[token]
        action_branch_trace[token] = branches
    derivation = {
        "schema": 1,
        "generator": "generate.py",
        "generator_sha256": sha256((ROOT / "generate.py").read_bytes()),
        "source_lock": "source-lock.json",
        "source_lock_sha256": sha256(LOCK.read_bytes()),
        "xkb_expansion": xkb_trace,
        "apple_keycode_mapping": {key: {"decimal": value, **APPLE_ANCHOR} for key, value in sorted(APPLE_KEYCODES.items())},
        "keysym_resolution": keysym_resolution,
        "format_and_identity": {
            "source": "apple-tn2056",
            "locations": ["XML DTD", "XML File Structure", "<layouts> Element"],
            "facts": {"xml_version": "1.1", "group": 126, "negative_id": KEYBOARD_ID, "ansi_iso_range": [0, 17], "jis_emitted": False, "contiguous_keymaps": [0, 11]},
        },
        "modifier_routing": {"source": "apple-tn2056", "locations": ["<modifierMap> Element", "<keyMapSelect> Element"], "contract": spec["routing"]},
        "dead_keys": dead_trace,
        "normalization": {
            "standard": "Unicode 17.0.0 / UAX #15",
            "sources": ["unicode-data", "unicode-composition-exclusions", "unicode-derived-normalization-properties"],
            "method": "Validate/trace explicit Compose output scalars and infer combining-mark metadata from canonical UCD decompositions. Never synthesize a Compose rule from NFC; CompositionExclusions and normalization properties are pinned version evidence.",
        },
        "actions": machine["actions"],
        "action_branch_trace": action_branch_trace,
        "terminators": machine["terminators"],
        "output_records": output_trace,
        "trace_policy": "Every XKB output record carries behavior, keysym and Apple keycode anchors. Control-letter outputs additionally record the ASCII C0 formula and sources. Every action branch and terminator has a public sequence/UCD/keysym anchor or an explicit derivation chain. Special values carry Apple and Unicode anchors.",
    }
    return {"layout": xml, "spec": canonical_json(spec), "derivation": canonical_json(derivation)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify sources and sealed outputs without writing")
    args = parser.parse_args()
    generated = build()
    if args.check:
        failures = []
        for name, blob in generated.items():
            path = OUTPUTS[name]
            if not path.exists() or path.read_bytes() != blob:
                failures.append(str(path))
        if failures:
            print("stale generated outputs: " + ", ".join(failures), file=sys.stderr)
            return 1
        print("verified pinned sources and 3 sealed generated outputs")
        return 0
    for name, blob in generated.items():
        OUTPUTS[name].write_bytes(blob)
        print(f"wrote {OUTPUTS[name].name} sha256={sha256(blob)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
