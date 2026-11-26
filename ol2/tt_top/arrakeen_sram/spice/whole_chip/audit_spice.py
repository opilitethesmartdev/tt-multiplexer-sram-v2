#!/usr/bin/env python3
"""Fail-closed hierarchy audit for the actual extracted top-level SPICE.

This is a preflight, not a simulator or an LVS/PEX checker. It deliberately
does not modify extracted connectivity, reorder pins, or supply missing cells.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import gzip
import hashlib
from pathlib import Path
import re
import sys


@dataclass
class Subcircuit:
    name: str
    ports: list[str]
    body: list[str]
    source: str

    @property
    def elements(self):
        return [line for line in self.body
                if line and not line.startswith(("*", "."))]

    @property
    def empty(self):
        return not self.elements

    def instances(self):
        for line in self.elements:
            tokens = line.split()
            if not tokens or not tokens[0].lower().startswith("x"):
                continue
            # Instance parameters follow the subcircuit name.
            tail = next((i for i, token in enumerate(tokens)
                         if "=" in token or token.lower() in ("params:", "param:")),
                        len(tokens))
            if tail < 2:
                raise ValueError(f"invalid instance in {self.name}: {line}")
            yield tokens[0], tokens[1:tail - 1], tokens[tail - 1]


def read_source(path):
    data = path.read_bytes()
    content = gzip.decompress(data) if path.suffix.lower() == ".gz" else data
    return content.decode("utf-8", errors="strict"), hashlib.sha256(content).hexdigest()


def parse_subcircuits(text, source):
    # Join SPICE continuation lines before parsing; keep original node order.
    statements = []
    for number, original in enumerate(text.splitlines(), 1):
        line = original.strip()
        if not line or line.startswith("*"):
            continue
        if line.startswith("+"):
            if not statements:
                raise ValueError(f"{source}:{number}: dangling continuation")
            statements[-1] += " " + line[1:].strip()
        else:
            statements.append(line)

    subcircuits = []
    current = None
    for line in statements:
        tokens = line.split()
        directive = tokens[0].lower()
        if directive == ".subckt":
            if current is not None or len(tokens) < 2:
                raise ValueError(f"{source}: nested or malformed .subckt")
            param = next((i for i, token in enumerate(tokens[2:], 2)
                          if "=" in token or token.lower() in ("params:", "param:")),
                         len(tokens))
            current = Subcircuit(tokens[1], tokens[2:param], [], str(source))
        elif directive == ".ends":
            if current is None:
                raise ValueError(f"{source}: .ends without .subckt")
            subcircuits.append(current)
            current = None
        elif current is not None:
            current.body.append(line)
    if current is not None:
        raise ValueError(f"{source}: missing .ends for {current.name}")
    return subcircuits


def audit(paths, top):
    definitions = defaultdict(list)
    source_hashes = {}
    for path in paths:
        text, digest = read_source(path)
        source_hashes[str(path)] = digest
        for sub in parse_subcircuits(text, path):
            definitions[sub.name.lower()].append(sub)

    top_key = top.lower()
    if top_key not in definitions:
        raise ValueError(f"top subcircuit {top!r} not found")
    candidates = definitions[top_key]
    if len(candidates) != 1 or candidates[0].empty:
        raise ValueError(f"top {top!r} must have exactly one nonempty definition")

    mismatches = []
    duplicates = []
    selected = {}
    for key, options in definitions.items():
        bodies = [sub for sub in options if not sub.empty]
        if len(bodies) > 1:
            duplicates.append(key)
        if bodies:
            selected[key] = bodies[0]
            for abstract in (sub for sub in options if sub.empty):
                left = [p.lower() for p in abstract.ports]
                right = [p.lower() for p in bodies[0].ports]
                if left != right:
                    mismatches.append((key, len(left), len(right),
                                       set(left) == set(right)))
        else:
            selected[key] = options[0]

    reachable = set()
    missing = Counter()
    empty = Counter()
    bad_arity = []
    frontier = [top_key]
    while frontier:
        parent = frontier.pop()
        if parent in reachable:
            continue
        reachable.add(parent)
        sub = selected.get(parent)
        if sub is None:
            continue
        for name, nodes, master in sub.instances():
            child = master.lower()
            target = selected.get(child)
            if target is None:
                missing[child] += 1
            else:
                if len(nodes) != len(target.ports):
                    bad_arity.append((parent, name, child, len(nodes), len(target.ports)))
                if target.empty:
                    empty[child] += 1
                else:
                    frontier.append(child)

    # Inspect the actual top-level SRAM pin associations. This is a
    # net-name check only; it cannot decide whether extraction is correct.
    signals_on_supply = []
    top_sub = selected[top_key]
    # Detect a completely disconnected group of explicit top-level supply
    # ports. A single disconnected alias can be legitimate, but if *none*
    # of the digital supply ports appears in the circuit body, an external
    # source connected to those ports cannot power the simulated design.
    disconnected_supply_groups = []
    body_tokens = {token.lower() for line in top_sub.elements for token in line.split()}
    groups = {
        "digital power": {"vccd", "vccd1", "vccd2", "vdpwr", "vpwr", "vdd"},
        "ground": {"vssd", "vssd1", "vssd2", "vssa", "vssa1", "vssa2",
                   "vgnd", "vss"},
    }
    top_ports = {p.lower() for p in top_sub.ports}
    for label, names in groups.items():
        ports = top_ports & names
        if ports and not (ports & body_tokens):
            disconnected_supply_groups.append((label, sorted(ports)))

    for instance, nodes, master in top_sub.instances():
        if master.lower() != "sp6tsram256x32":
            continue
        # Use the top file's own abstract header, not the compiler schematic.
        top_headers = [s for s in definitions[master.lower()]
                       if s.source == top_sub.source]
        if len(top_headers) != 1:
            raise ValueError("cannot uniquely identify SRAM header in top extraction")
        ports = top_headers[0].ports
        if len(nodes) != len(ports):
            bad_arity.append((top_key, instance, master, len(nodes), len(ports)))
            continue
        connections = {p.lower(): n for p, n in zip(ports, nodes)}
        supply = {connections.get("vss", "").lower(), connections.get("vdd", "").lower()}
        for port, node in connections.items():
            if re.fullmatch(r"q\[\d+\]", port) and node.lower() in supply:
                signals_on_supply.append((instance, port, node))

    return {
        "source_hashes": source_hashes,
        "top": top_sub,
        "definition_count": len(definitions),
        "reachable": sorted(reachable),
        "empty": empty,
        "missing": missing,
        "port_order_mismatches": sorted(mismatches),
        "duplicate_implementations": sorted(duplicates),
        "bad_arity": bad_arity,
        "signals_on_supply": signals_on_supply,
        "disconnected_supply_groups": disconnected_supply_groups,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("top_spice", type=Path, help="raw extracted top, optionally .gz")
    parser.add_argument("--library", type=Path, action="append", default=[],
                        help="additional extracted/model subcircuits; repeat as needed")
    parser.add_argument("--top", default="tt_gf_wrapper")
    args = parser.parse_args()
    try:
        result = audit([args.top_spice, *args.library], args.top)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for source, digest in result["source_hashes"].items():
        print(f"SHA256 {digest}  {source}")
    top = result["top"]
    print(f"Top {top.name}: {len(top.ports)} ports, {len(top.elements)} elements")
    for label, key in (("EMPTY referenced subcircuits", "empty"),
                       ("MISSING referenced subcircuits", "missing")):
        print(f"{label}: {len(result[key])} distinct")
        for name, count in sorted(result[key].items()):
            print(f"  {name}: {count} references in distinct parsed definitions")
    for name, left, right, same in result["port_order_mismatches"]:
        print(f"PORT MISMATCH {name}: abstract={left}, implementation={right}, "
              f"same_pin_names={same}")
    for name in result["duplicate_implementations"]:
        print(f"DUPLICATE IMPLEMENTATION {name}")
    for parent, inst, master, got, expected in result["bad_arity"]:
        print(f"PIN COUNT {parent}/{inst} {master}: {got}, expected {expected}")
    for inst, port, net in result["signals_on_supply"]:
        print(f"SRAM OUTPUT ON SUPPLY {inst} {port} -> {net}")
    for group, ports in result["disconnected_supply_groups"]:
        print(f"DISCONNECTED SUPPLY GROUP {group}: no listed port appears "
              f"in top circuit elements: {', '.join(ports)}")
    failed = any(result[k] for k in ("empty", "missing", "port_order_mismatches",
                                      "duplicate_implementations", "bad_arity",
                                      "signals_on_supply", "disconnected_supply_groups"))
    if failed:
        print("FAIL: whole-chip transistor simulation is not ready; no connectivity repaired.")
        return 1
    print("Hierarchy preflight passed; independent LVS, device models, PEX and "
          "actual simulation are still required.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
