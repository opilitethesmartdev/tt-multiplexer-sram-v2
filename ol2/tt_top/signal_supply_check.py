"""Detect extracted signal-to-supply mismatches without rewriting SPICE."""
import re


def def_pin_nets(text):
    """Read complete multi-line NETS connection lists; exclude SPECIALNETS."""
    inside = False
    records = []
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^NETS\s+\d+\s*;", stripped, re.I):
            inside = True
            continue
        if re.match(r"^END\s+NETS\b", stripped, re.I):
            break
        if not inside:
            continue
        if stripped.startswith("- "):
            if current is not None:
                raise ValueError("unfinished DEF net record")
            current = stripped
        elif current is not None:
            current += " " + stripped
        if current is not None and ";" in stripped:
            records.append(current)
            current = None
    if not inside or current is not None:
        raise ValueError("missing or truncated DEF NETS section")
    result = {}
    for record in records:
        match = re.match(r"-\s+(\S+)\s+(.*)", record)
        if not match:
            raise ValueError("malformed DEF net")
        name = match.group(1)
        connections = match.group(2).split("+", 1)[0]
        for inst, pin in re.findall(r"\(\s*(\S+)\s+(\S+)\s*\)", connections):
            key = (inst, pin)
            if key in result and result[key] != name:
                raise ValueError(f"DEF assigns {inst}/{pin} to multiple nets")
            result[key] = name
    return result


def signal_supply_conflicts(text, design, pin_lists, connectivity, supply):
    """List (instance,pin,extracted,golden) mismatches, retaining raw text."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines)
                  if re.match(r"^\.subckt\s+" + re.escape(design) + r"(?:\s|$)",
                              line.strip(), re.I)), None)
    if start is None:
        raise ValueError(f"missing extracted top subcircuit {design}")
    i = start + 1
    while i < len(lines) and lines[i].lstrip().startswith("+"):
        i += 1
    found = []
    supplies = {node.lower() for node in supply}
    while i < len(lines):
        line = lines[i].strip()
        if re.match(r"^\.ends(?:\s|$)", line, re.I):
            return found
        i += 1
        if not line or not line.lower().startswith("x"):
            continue
        tokens = line.split()
        while i < len(lines) and lines[i].lstrip().startswith("+"):
            tokens.extend(lines[i].lstrip()[1:].split())
            i += 1
        if len(tokens) < 2:
            raise ValueError("malformed extracted instance")
        ports = pin_lists.get(tokens[-1])
        if ports is None:
            continue
        if len(tokens) - 2 != len(ports):
            raise ValueError(f"pin arity mismatch for {tokens[0]}")
        instance = tokens[0][1:]
        for pin, node in zip(ports, tokens[1:-1]):
            golden = connectivity.get((instance, pin))
            if golden is not None and node.lower() in supplies and golden.lower() not in supplies:
                found.append((instance, pin, node, golden))
    raise ValueError(f"unterminated extracted top subcircuit {design}")
