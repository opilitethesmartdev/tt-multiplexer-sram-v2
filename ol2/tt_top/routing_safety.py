"""Conservative rectangle checks for custom power geometry.

These checks do not replace foundry DRC, routed-net checks, or GDS LVS.
Coordinates and margins are in the caller's database units.
"""


def intersects(a, b, margin=0):
    """Treat contact and less-than-margin separation as unsafe."""
    if margin:
        return (a[0] < b[2] + margin and a[2] > b[0] - margin and
                a[1] < b[3] + margin and a[3] > b[1] - margin)
    return (a[0] <= b[2] and a[2] >= b[0] and
            a[1] <= b[3] and a[3] >= b[1])


def blocked_by_macro(rect, macros, margin):
    return any(intersects(rect, macro, margin) for macro in macros)


def placement_halo_strips(bbox, halo):
    if halo <= 0:
        raise ValueError("placement halo must be positive")
    x0, y0, x1, y1 = bbox
    return [(x0 - halo, y0 - halo, x1 + halo, y0),
            (x0 - halo, y1, x1 + halo, y1 + halo),
            (x0 - halo, y0, x0, y1),
            (x1, y0, x1 + halo, y1)]


def blocked_by_other_pin(rects, net, pins, margin):
    return any(owner != net and intersects(rect, pin, margin)
               for rect in rects for owner, pin in pins)


def restricted_macro_crossing(rects, macros, allowed):
    """Inside any macro bbox, permit geometry only inside its allowed pin."""
    for macro in macros:
        pins = allowed.get(macro, ())
        for rect in rects:
            overlap = (max(rect[0], macro[0]), max(rect[1], macro[1]),
                       min(rect[2], macro[2]), min(rect[3], macro[3]))
            if overlap[0] >= overlap[2] or overlap[1] >= overlap[3]:
                continue
            if not any(pin[0] <= overlap[0] and pin[1] <= overlap[1] and
                       pin[2] >= overlap[2] and pin[3] >= overlap[3]
                       for pin in pins):
                return True
    return False


def segment_rect(x0, y0, x1, y1, width):
    """Manhattan rectangle including square end caps."""
    if x0 != x1 and y0 != y1:
        raise ValueError("power strap must be Manhattan")
    half = width // 2
    return (min(x0, x1) - half, min(y0, y1) - half,
            max(x0, x1) + half, max(y0, y1) + half)


def gate_escape_rects(pin, bbox, target_x, join_y, width, clearance, grid):
    """Try exits around either vertical side of an endpoint macro.

    The starting pin must reach that side of the macro. The candidate leaves
    below/above the signal pin, goes around the macro, then to the target.
    The caller must additionally check ALL other-net pins, macros and wiring.
    """
    x0, y0, x1, y1 = pin
    bx0, by0, bx1, by1 = bbox
    half = width // 2
    pad = clearance + half + grid
    if join_y > y1:
        start_y = y1 - pad
    elif join_y < y0:
        start_y = y0 + pad
    else:
        return []
    if not y0 + half <= start_y <= y1 - half:
        return []
    start_x = (x0 + x1) // 2
    result = []
    if x1 >= bx1:
        result.append([
            segment_rect(start_x, start_y, bx1 + pad, start_y, width),
            segment_rect(bx1 + pad, start_y, bx1 + pad, join_y, width),
            segment_rect(bx1 + pad, join_y, target_x, join_y, width),
        ])
    if x0 <= bx0:
        result.append([
            segment_rect(start_x, start_y, bx0 - pad, start_y, width),
            segment_rect(bx0 - pad, start_y, bx0 - pad, join_y, width),
            segment_rect(bx0 - pad, join_y, target_x, join_y, width),
        ])
    return result
