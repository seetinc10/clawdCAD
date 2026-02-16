"""FreeCAD tool functions for post-frame building generation.

All public functions accept dimensions in FEET (and inches where noted).
Internally everything is converted to mm for FreeCAD.

Post-frame construction basics:
- Laminated wood posts (typically 3-ply 2x6 or 2x8) set in ground or on brackets
- Posts spaced 8' on center (common) along the perimeter
- Horizontal girts connect posts for wall sheathing attachment
- Trusses span the full width, bearing on the posts
- No continuous foundation - just post embedments or piers
"""

import math
import logging
import os
import sys

log = logging.getLogger(__name__)

# Auto-detect FreeCAD installation and add to path
_FREECAD_PATHS = [
    r"C:\Program Files\FreeCAD 1.0\bin",
    r"C:\Program Files\FreeCAD 1.0\lib",
    r"C:\Program Files\FreeCAD\bin",
    r"C:\Program Files\FreeCAD\lib",
]
for _p in _FREECAD_PATHS:
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

# We attempt to import FreeCAD. If unavailable (e.g. during testing),
# we run in "dry-run" mode and return descriptions instead of real objects.
try:
    import FreeCAD
    import Part

    FREECAD_AVAILABLE = True
    # Arch and Draft may not be available in headless mode
    try:
        import Draft
    except ImportError:
        Draft = None
except ImportError:
    FREECAD_AVAILABLE = False
    log.warning("FreeCAD not available - running in dry-run mode")

from tools.units import ft_in_to_mm, feet_to_mm, format_ft_in, mm_to_ft_in


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_doc = None
_objects = {}  # name -> FreeCAD object or description dict


def _get_doc():
    global _doc
    if FREECAD_AVAILABLE:
        if _doc is None:
            _doc = FreeCAD.newDocument("PostFrameBuilding")
        return _doc
    return None


def _record(name, obj):
    _objects[name] = obj
    return name


def get_object(name):
    return _objects.get(name)


def list_objects():
    return list(_objects.keys())


# ---------------------------------------------------------------------------
# Post-frame specific tools
# ---------------------------------------------------------------------------


def create_post(
    name: str,
    x_ft: float,
    y_ft: float,
    height_ft: float = 10,
    size_inches: float = 6,
    embed_ft: float = 4,
) -> str:
    """Create a single post at (x, y) in feet.

    Args:
        name: Unique name for this post.
        x_ft: X position in feet from origin.
        y_ft: Y position in feet from origin.
        height_ft: Above-grade height in feet (default 10').
        size_inches: Post cross-section size in inches (default 6" = 6x6 post).
        embed_ft: Below-grade embedment in feet (default 4').

    Returns:
        Name of the created post object.
    """
    x_mm = feet_to_mm(x_ft)
    y_mm = feet_to_mm(y_ft)
    h_mm = feet_to_mm(height_ft)
    embed_mm = feet_to_mm(embed_ft)
    size_mm = size_inches * 25.4

    total_h = h_mm + embed_mm

    if FREECAD_AVAILABLE:
        doc = _get_doc()
        post = doc.addObject("Part::Box", name)
        post.Length = size_mm
        post.Width = size_mm
        post.Height = total_h
        post.Placement.Base = FreeCAD.Vector(
            x_mm - size_mm / 2, y_mm - size_mm / 2, -embed_mm
        )
        doc.recompute()
        return _record(name, post)

    desc = {
        "type": "post",
        "name": name,
        "x_ft": x_ft,
        "y_ft": y_ft,
        "height_ft": height_ft,
        "embed_ft": embed_ft,
        "size_inches": size_inches,
    }
    return _record(name, desc)


def create_post_layout(
    building_length_ft: float,
    building_width_ft: float,
    post_spacing_ft: float = 8,
    height_ft: float = 10,
    size_inches: float = 6,
    embed_ft: float = 4,
) -> list[str]:
    """Generate the full post layout for a rectangular post-frame building.

    Posts are placed at each corner and evenly spaced along each wall.

    Args:
        building_length_ft: Total building length in feet (along X axis).
        building_width_ft: Total building width in feet (along Y axis).
        post_spacing_ft: On-center spacing between posts (default 8').
        height_ft: Above-grade post height in feet.
        size_inches: Post cross-section in inches.
        embed_ft: Below-grade embedment in feet.

    Returns:
        List of created post names.
    """
    posts = []

    def _posts_along(start_ft, end_ft, spacing_ft):
        count = max(2, math.ceil((end_ft - start_ft) / spacing_ft) + 1)
        actual_spacing = (end_ft - start_ft) / (count - 1)
        return [start_ft + i * actual_spacing for i in range(count)]

    x_positions = _posts_along(0, building_length_ft, post_spacing_ft)
    y_positions = _posts_along(0, building_width_ft, post_spacing_ft)

    idx = 0
    # Front wall (y=0)
    for x in x_positions:
        name = f"Post_front_{idx}"
        create_post(name, x, 0, height_ft, size_inches, embed_ft)
        posts.append(name)
        idx += 1

    # Back wall (y=width)
    for x in x_positions:
        name = f"Post_back_{idx}"
        create_post(name, x, building_width_ft, height_ft, size_inches, embed_ft)
        posts.append(name)
        idx += 1

    # Left wall (x=0), skip corners already placed
    for y in y_positions[1:-1]:
        name = f"Post_left_{idx}"
        create_post(name, 0, y, height_ft, size_inches, embed_ft)
        posts.append(name)
        idx += 1

    # Right wall (x=length), skip corners
    for y in y_positions[1:-1]:
        name = f"Post_right_{idx}"
        create_post(name, building_length_ft, y, height_ft, size_inches, embed_ft)
        posts.append(name)
        idx += 1

    return posts


def create_girt(
    name: str,
    start_x_ft: float,
    start_y_ft: float,
    end_x_ft: float,
    end_y_ft: float,
    height_ft: float = 4,
    width_inches: float = 1.5,
    depth_inches: float = 5.5,
) -> str:
    """Create a horizontal girt (wall framing member) between two points.

    Args:
        name: Unique name.
        start_x_ft, start_y_ft: Start point in feet.
        end_x_ft, end_y_ft: End point in feet.
        height_ft: Height above grade where girt is placed.
        width_inches: Girt thickness (default 1.5" = 2x nominal).
        depth_inches: Girt depth (default 5.5" = 2x6 actual).

    Returns:
        Name of created girt.
    """
    sx = feet_to_mm(start_x_ft)
    sy = feet_to_mm(start_y_ft)
    ex = feet_to_mm(end_x_ft)
    ey = feet_to_mm(end_y_ft)
    z = feet_to_mm(height_ft)
    w = width_inches * 25.4
    d = depth_inches * 25.4

    length = math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2)
    angle = math.degrees(math.atan2(ey - sy, ex - sx))

    if FREECAD_AVAILABLE:
        doc = _get_doc()
        girt = doc.addObject("Part::Box", name)
        girt.Length = length
        girt.Width = w
        girt.Height = d
        girt.Placement.Base = FreeCAD.Vector(sx, sy, z)
        girt.Placement.Rotation = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), angle)
        doc.recompute()
        return _record(name, girt)

    desc = {
        "type": "girt",
        "name": name,
        "start": (start_x_ft, start_y_ft),
        "end": (end_x_ft, end_y_ft),
        "height_ft": height_ft,
        "size": f"{width_inches}x{depth_inches}",
    }
    return _record(name, desc)


def create_wall_girts(
    building_length_ft: float,
    building_width_ft: float,
    wall_height_ft: float = 10,
    girt_spacing_ft: float = 2,
) -> list[str]:
    """Create horizontal girts on all four walls.

    Girts run between posts at regular vertical intervals.

    Args:
        building_length_ft: Building length in feet.
        building_width_ft: Building width in feet.
        wall_height_ft: Total wall height in feet.
        girt_spacing_ft: Vertical spacing between girts.

    Returns:
        List of created girt names.
    """
    girts = []
    num_rows = int(wall_height_ft / girt_spacing_ft)
    idx = 0

    for row in range(1, num_rows + 1):
        h = row * girt_spacing_ft

        # Front wall
        n = f"Girt_front_{idx}"
        create_girt(n, 0, 0, building_length_ft, 0, h)
        girts.append(n)
        idx += 1

        # Back wall
        n = f"Girt_back_{idx}"
        create_girt(n, 0, building_width_ft, building_length_ft, building_width_ft, h)
        girts.append(n)
        idx += 1

        # Left wall
        n = f"Girt_left_{idx}"
        create_girt(n, 0, 0, 0, building_width_ft, h)
        girts.append(n)
        idx += 1

        # Right wall
        n = f"Girt_right_{idx}"
        create_girt(n, building_length_ft, 0, building_length_ft, building_width_ft, h)
        girts.append(n)
        idx += 1

    return girts


def create_truss(
    name: str,
    x_ft: float,
    building_width_ft: float,
    eave_height_ft: float = 10,
    pitch: float = 4,
    overhang_ft: float = 1,
) -> str:
    """Create a simple gable truss profile at position x.

    Args:
        name: Unique name.
        x_ft: X position along building length.
        building_width_ft: Building width in feet (truss span).
        eave_height_ft: Eave height in feet.
        pitch: Roof pitch as rise per 12" run (e.g., 4 = 4:12).
        overhang_ft: Eave overhang in feet.

    Returns:
        Name of created truss.
    """
    span_mm = feet_to_mm(building_width_ft)
    x_mm = feet_to_mm(x_ft)
    eave_mm = feet_to_mm(eave_height_ft)
    overhang_mm = feet_to_mm(overhang_ft)

    rise_per_run = pitch / 12.0
    ridge_rise_mm = (span_mm / 2) * rise_per_run
    ridge_z = eave_mm + ridge_rise_mm

    if FREECAD_AVAILABLE:
        doc = _get_doc()
        points = [
            FreeCAD.Vector(x_mm, -overhang_mm, eave_mm),
            FreeCAD.Vector(x_mm, span_mm / 2, ridge_z),
            FreeCAD.Vector(x_mm, span_mm + overhang_mm, eave_mm),
        ]
        wire = Draft.makeWire(points, closed=False)
        wire.Label = name
        doc.recompute()
        return _record(name, wire)

    ridge_ft_in = mm_to_ft_in(ridge_rise_mm)
    desc = {
        "type": "truss",
        "name": name,
        "x_ft": x_ft,
        "span_ft": building_width_ft,
        "eave_height_ft": eave_height_ft,
        "pitch": f"{pitch}:12",
        "ridge_height": format_ft_in(*mm_to_ft_in(ridge_z)),
        "overhang_ft": overhang_ft,
    }
    return _record(name, desc)


def create_roof_trusses(
    building_length_ft: float,
    building_width_ft: float,
    truss_spacing_ft: float = 2,
    eave_height_ft: float = 10,
    pitch: float = 4,
    overhang_ft: float = 1,
) -> list[str]:
    """Create evenly spaced trusses along the building length.

    Args:
        building_length_ft: Building length in feet.
        building_width_ft: Building width in feet.
        truss_spacing_ft: On-center truss spacing (default 2').
        eave_height_ft: Eave height.
        pitch: Roof pitch (rise per 12" run).
        overhang_ft: Eave overhang.

    Returns:
        List of truss names.
    """
    trusses = []
    count = int(building_length_ft / truss_spacing_ft) + 1
    actual_spacing = building_length_ft / (count - 1) if count > 1 else 0

    for i in range(count):
        x = i * actual_spacing
        name = f"Truss_{i}"
        create_truss(name, x, building_width_ft, eave_height_ft, pitch, overhang_ft)
        trusses.append(name)

    return trusses


def create_overhead_door(
    name: str,
    wall: str,
    position_ft: float,
    width_ft: float = 10,
    height_ft: float = 10,
) -> str:
    """Create an overhead/garage door opening in a wall.

    Args:
        name: Unique name.
        wall: Which wall - "front", "back", "left", "right".
        position_ft: Position along the wall in feet (from left corner).
        width_ft: Door width in feet.
        height_ft: Door height in feet.

    Returns:
        Name of created door.
    """
    desc = {
        "type": "overhead_door",
        "name": name,
        "wall": wall,
        "position_ft": position_ft,
        "width_ft": width_ft,
        "height_ft": height_ft,
    }
    return _record(name, desc)


def create_walk_door(
    name: str,
    wall: str,
    position_ft: float,
    width_ft: float = 3,
    height_ft: float = 6.67,
) -> str:
    """Create a walk-through door opening.

    Args:
        name: Unique name.
        wall: Which wall.
        position_ft: Position along wall in feet.
        width_ft: Width (default 3' = 36").
        height_ft: Height (default 6'8").

    Returns:
        Name of created door.
    """
    desc = {
        "type": "walk_door",
        "name": name,
        "wall": wall,
        "position_ft": position_ft,
        "width_ft": width_ft,
        "height_ft": height_ft,
    }
    return _record(name, desc)


def create_window(
    name: str,
    wall: str,
    position_ft: float,
    sill_height_ft: float = 3,
    width_ft: float = 3,
    height_ft: float = 4,
) -> str:
    """Create a window opening.

    Args:
        name: Unique name.
        wall: Which wall.
        position_ft: Position along wall in feet.
        sill_height_ft: Sill height above grade.
        width_ft: Window width.
        height_ft: Window height.

    Returns:
        Name of created window.
    """
    desc = {
        "type": "window",
        "name": name,
        "wall": wall,
        "position_ft": position_ft,
        "sill_height_ft": sill_height_ft,
        "width_ft": width_ft,
        "height_ft": height_ft,
    }
    return _record(name, desc)


def create_concrete_slab(
    name: str,
    length_ft: float,
    width_ft: float,
    thickness_inches: float = 4,
) -> str:
    """Create a concrete floor slab.

    Args:
        name: Unique name.
        length_ft: Slab length in feet.
        width_ft: Slab width in feet.
        thickness_inches: Thickness in inches (default 4").

    Returns:
        Name of created slab.
    """
    l_mm = feet_to_mm(length_ft)
    w_mm = feet_to_mm(width_ft)
    t_mm = thickness_inches * 25.4

    if FREECAD_AVAILABLE:
        doc = _get_doc()
        slab = doc.addObject("Part::Box", name)
        slab.Length = l_mm
        slab.Width = w_mm
        slab.Height = t_mm
        slab.Placement.Base = FreeCAD.Vector(0, 0, -t_mm)
        doc.recompute()
        return _record(name, slab)

    desc = {
        "type": "slab",
        "name": name,
        "length_ft": length_ft,
        "width_ft": width_ft,
        "thickness_inches": thickness_inches,
    }
    return _record(name, desc)


def create_purlins(
    building_length_ft: float,
    building_width_ft: float,
    eave_height_ft: float = 10,
    pitch: float = 4,
    purlin_spacing_ft: float = 2,
    purlin_width_inches: float = 1.5,
    purlin_depth_inches: float = 3.5,
    overhang_ft: float = 1,
) -> list[str]:
    """Create roof purlins running along the building length on both roof slopes.

    Purlins are horizontal members perpendicular to the trusses that support
    the roof sheathing. They run the full building length.

    Args:
        building_length_ft: Building length in feet.
        building_width_ft: Building width in feet.
        eave_height_ft: Eave height in feet.
        pitch: Roof pitch (rise per 12" run).
        purlin_spacing_ft: Spacing between purlins measured along the slope.
        purlin_width_inches: Purlin thickness (default 1.5" = 2x nominal).
        purlin_depth_inches: Purlin depth (default 3.5" = 2x4 actual).
        overhang_ft: Eave overhang in feet.

    Returns:
        List of purlin names.
    """
    purlins = []
    rise_per_run = pitch / 12.0
    slope_angle = math.atan(rise_per_run)

    half_span_mm = feet_to_mm(building_width_ft) / 2
    length_mm = feet_to_mm(building_length_ft)
    eave_mm = feet_to_mm(eave_height_ft)
    overhang_mm = feet_to_mm(overhang_ft)
    spacing_mm = feet_to_mm(purlin_spacing_ft)
    w_mm = purlin_width_inches * 25.4
    d_mm = purlin_depth_inches * 25.4

    # Distance along slope from eave to ridge
    slope_length = half_span_mm / math.cos(slope_angle)
    # Add overhang
    total_slope = slope_length + overhang_mm / math.cos(slope_angle)

    num_purlins = int(total_slope / spacing_mm) + 1
    idx = 0

    for side in ["left", "right"]:
        for i in range(num_purlins):
            dist_along_slope = i * spacing_mm
            horizontal_dist = dist_along_slope * math.cos(slope_angle)
            vertical_rise = dist_along_slope * math.sin(slope_angle)

            if side == "left":
                y_mm = -overhang_mm + horizontal_dist
            else:
                y_mm = feet_to_mm(building_width_ft) + overhang_mm - horizontal_dist

            z_mm = eave_mm + vertical_rise

            name = f"Purlin_{side}_{idx}"

            if FREECAD_AVAILABLE:
                doc = _get_doc()
                purlin = doc.addObject("Part::Box", name)
                purlin.Length = length_mm
                purlin.Width = w_mm
                purlin.Height = d_mm
                purlin.Placement.Base = FreeCAD.Vector(0, y_mm - w_mm / 2, z_mm)
                doc.recompute()
                _record(name, purlin)
            else:
                _record(name, {
                    "type": "purlin",
                    "name": name,
                    "side": side,
                    "slope_distance_ft": round(dist_along_slope / 304.8, 2),
                })

            purlins.append(name)
            idx += 1

    return purlins


def create_wainscot(
    building_length_ft: float,
    building_width_ft: float,
    wainscot_height_ft: float = 4,
    thickness_inches: float = 0.5,
) -> list[str]:
    """Create wainscot (lower wall sheathing panels) on all four walls.

    Wainscot is typically the lower 3'-4' of the wall, often a different
    material (steel, plywood) from the upper wall.

    Args:
        building_length_ft: Building length in feet.
        building_width_ft: Building width in feet.
        wainscot_height_ft: Wainscot height in feet (default 4').
        thickness_inches: Panel thickness in inches (default 0.5").

    Returns:
        List of wainscot panel names.
    """
    panels = []
    l_mm = feet_to_mm(building_length_ft)
    w_mm = feet_to_mm(building_width_ft)
    h_mm = feet_to_mm(wainscot_height_ft)
    t_mm = thickness_inches * 25.4

    wall_defs = [
        ("Wainscot_front", FreeCAD.Vector(0, -t_mm, 0) if FREECAD_AVAILABLE else None, l_mm, t_mm, h_mm, 0),
        ("Wainscot_back", FreeCAD.Vector(0, w_mm, 0) if FREECAD_AVAILABLE else None, l_mm, t_mm, h_mm, 0),
        ("Wainscot_left", FreeCAD.Vector(-t_mm, 0, 0) if FREECAD_AVAILABLE else None, t_mm, w_mm, h_mm, 0),
        ("Wainscot_right", FreeCAD.Vector(l_mm, 0, 0) if FREECAD_AVAILABLE else None, t_mm, w_mm, h_mm, 0),
    ]

    for name, base, lx, ly, lz, angle in wall_defs:
        if FREECAD_AVAILABLE:
            doc = _get_doc()
            panel = doc.addObject("Part::Box", name)
            panel.Length = lx
            panel.Width = ly
            panel.Height = lz
            panel.Placement.Base = base
            doc.recompute()
            _record(name, panel)
        else:
            _record(name, {"type": "wainscot", "name": name, "height_ft": wainscot_height_ft})
        panels.append(name)

    return panels


def create_interior_wall(
    name: str,
    start_x_ft: float,
    start_y_ft: float,
    end_x_ft: float,
    end_y_ft: float,
    height_ft: float = 10,
    thickness_inches: float = 5.5,
) -> str:
    """Create an interior partition wall.

    Args:
        name: Unique name.
        start_x_ft: Start X position in feet.
        start_y_ft: Start Y position in feet.
        end_x_ft: End X position in feet.
        end_y_ft: End Y position in feet.
        height_ft: Wall height in feet.
        thickness_inches: Wall thickness in inches (default 5.5" = 2x6 framed wall).

    Returns:
        Name of created wall.
    """
    sx = feet_to_mm(start_x_ft)
    sy = feet_to_mm(start_y_ft)
    ex = feet_to_mm(end_x_ft)
    ey = feet_to_mm(end_y_ft)
    h_mm = feet_to_mm(height_ft)
    t_mm = thickness_inches * 25.4

    length = math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2)
    angle = math.degrees(math.atan2(ey - sy, ex - sx))

    if FREECAD_AVAILABLE:
        doc = _get_doc()
        wall = doc.addObject("Part::Box", name)
        wall.Length = length
        wall.Width = t_mm
        wall.Height = h_mm
        wall.Placement.Base = FreeCAD.Vector(sx, sy - t_mm / 2, 0)
        wall.Placement.Rotation = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), angle)
        doc.recompute()
        return _record(name, wall)

    desc = {
        "type": "interior_wall",
        "name": name,
        "start": (start_x_ft, start_y_ft),
        "end": (end_x_ft, end_y_ft),
        "height_ft": height_ft,
        "thickness_inches": thickness_inches,
    }
    return _record(name, desc)


def create_ridge_cap(
    building_length_ft: float,
    building_width_ft: float,
    eave_height_ft: float = 10,
    pitch: float = 4,
    cap_width_inches: float = 12,
    cap_height_inches: float = 2,
) -> str:
    """Create a ridge cap along the peak of the roof.

    Args:
        building_length_ft: Building length in feet.
        building_width_ft: Building width in feet.
        eave_height_ft: Eave height in feet.
        pitch: Roof pitch (rise per 12" run).
        cap_width_inches: Ridge cap width in inches (default 12").
        cap_height_inches: Ridge cap height in inches (default 2").

    Returns:
        Name of created ridge cap.
    """
    name = "Ridge_Cap"
    l_mm = feet_to_mm(building_length_ft)
    span_mm = feet_to_mm(building_width_ft)
    eave_mm = feet_to_mm(eave_height_ft)
    cw = cap_width_inches * 25.4
    ch = cap_height_inches * 25.4

    rise_per_run = pitch / 12.0
    ridge_z = eave_mm + (span_mm / 2) * rise_per_run

    if FREECAD_AVAILABLE:
        doc = _get_doc()
        cap = doc.addObject("Part::Box", name)
        cap.Length = l_mm
        cap.Width = cw
        cap.Height = ch
        cap.Placement.Base = FreeCAD.Vector(0, span_mm / 2 - cw / 2, ridge_z)
        doc.recompute()
        return _record(name, cap)

    desc = {
        "type": "ridge_cap",
        "name": name,
        "ridge_height": format_ft_in(*mm_to_ft_in(ridge_z)),
    }
    return _record(name, desc)


def save_document(filepath: str) -> str:
    """Save the FreeCAD document.

    Args:
        filepath: Output path (e.g., 'output/building.FCStd').

    Returns:
        Confirmation message.
    """
    if FREECAD_AVAILABLE:
        doc = _get_doc()
        doc.saveAs(filepath)
        return f"Document saved to {filepath}"
    return f"Dry-run: would save to {filepath}"


def export_step(filepath: str) -> str:
    """Export the model as a STEP file for interoperability.

    Args:
        filepath: Output path (e.g., 'output/building.step').

    Returns:
        Confirmation message.
    """
    if FREECAD_AVAILABLE:
        doc = _get_doc()
        shapes = [obj.Shape for obj in doc.Objects if hasattr(obj, "Shape")]
        if shapes:
            Part.export(shapes, filepath)
        return f"STEP exported to {filepath}"
    return f"Dry-run: would export STEP to {filepath}"


def get_building_summary() -> dict:
    """Return a summary of all objects created so far."""
    summary = {"total_objects": len(_objects), "by_type": {}}
    for name, obj in _objects.items():
        if isinstance(obj, dict):
            t = obj.get("type", "unknown")
        else:
            t = "freecad_object"
        summary["by_type"].setdefault(t, []).append(name)
    return summary


def clear_all():
    """Clear all objects and reset the document."""
    global _doc
    _objects.clear()
    if FREECAD_AVAILABLE and _doc:
        FreeCAD.closeDocument(_doc.Name)
        _doc = None
