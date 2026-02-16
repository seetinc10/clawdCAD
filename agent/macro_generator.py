"""Generate FreeCAD GUI macros from agent tool calls.

Instead of calling FreeCAD headless (which loses ViewObject data),
we generate a .py macro that FreeCAD's GUI executes directly.
This gives us colors, transparency, and proper visibility.
"""

import os
import math

MACRO_HEADER = '''\
"""Auto-generated FreeCAD macro by OpenClaw agent."""

import math
import FreeCAD
import FreeCADGui
import Part
import Draft

MM_PER_FOOT = 304.8

def ft(feet):
    return feet * MM_PER_FOOT

def inches(i):
    return i * 25.4

def set_color(obj, r, g, b, transparency=0):
    if hasattr(obj, 'ViewObject') and obj.ViewObject:
        obj.ViewObject.ShapeColor = (r/255.0, g/255.0, b/255.0)
        if transparency > 0:
            obj.ViewObject.Transparency = transparency

doc = FreeCAD.newDocument("PostFrameBuilding")

'''

MACRO_FOOTER = '''\

# Finalize
doc.recompute()

import os as _os
_screenshot_dir = _os.path.join(_os.path.dirname(SAVE_PATH), "screenshots")
_os.makedirs(_screenshot_dir, exist_ok=True)

_view = FreeCADGui.ActiveDocument.ActiveView

# Screenshot 1: Isometric view
_view.viewIsometric()
_view.fitAll()
FreeCADGui.updateGui()
_view.saveImage(_os.path.join(_screenshot_dir, "view_isometric.png"), 1920, 1080, "Current")
print("Captured isometric view")

# Screenshot 2: Top-down (plan view)
_view.viewTop()
_view.fitAll()
FreeCADGui.updateGui()
_view.saveImage(_os.path.join(_screenshot_dir, "view_top.png"), 1920, 1080, "Current")
print("Captured top view")

# Screenshot 3: Front elevation
_view.viewFront()
_view.fitAll()
FreeCADGui.updateGui()
_view.saveImage(_os.path.join(_screenshot_dir, "view_front.png"), 1920, 1080, "Current")
print("Captured front view")

# Return to isometric for user
_view.viewIsometric()
_view.fitAll()

doc.saveAs(SAVE_PATH)
print(f"Done! {len(doc.Objects)} objects saved to {SAVE_PATH}")

# Write signal file so agent knows screenshots are ready
with open(_os.path.join(_screenshot_dir, "done.signal"), "w") as _sf:
    _sf.write(f"{len(doc.Objects)} objects\\n")
    _sf.write(f"Saved to {SAVE_PATH}\\n")
print("Signal file written - agent can review screenshots now")
'''


class MacroBuilder:
    """Accumulates tool calls and produces a complete FreeCAD macro."""

    def __init__(self, save_path: str = r"C:\clawdbotCAD\output\building.FCStd"):
        self.lines: list[str] = []
        self.save_path = save_path
        self.obj_count = 0

    def _add(self, code: str):
        self.lines.append(code)

    def create_concrete_slab(self, name: str, length_ft: float, width_ft: float,
                             thickness_inches: float = 4) -> str:
        self._add(f"""
# Concrete Slab
slab = doc.addObject("Part::Box", "{name}")
slab.Length = ft({length_ft})
slab.Width = ft({width_ft})
slab.Height = inches({thickness_inches})
slab.Placement.Base = FreeCAD.Vector(0, 0, -inches({thickness_inches}))
set_color(slab, 180, 180, 180)
""")
        self.obj_count += 1
        return name

    def create_post_layout(self, building_length_ft: float, building_width_ft: float,
                           post_spacing_ft: float = 8, height_ft: float = 10,
                           size_inches: float = 6, embed_ft: float = 4) -> list[str]:
        self._add(f"""
# Posts - {size_inches}"x{size_inches}", {post_spacing_ft}' OC, {height_ft}' tall, {embed_ft}' embed
POST_SIZE = inches({size_inches})
POST_HEIGHT = ft({height_ft})
POST_EMBED = ft({embed_ft})

def post_positions(total, spacing):
    count = max(2, math.ceil(total / spacing) + 1)
    actual = total / (count - 1)
    return [i * actual for i in range(count)]

x_posts = post_positions(ft({building_length_ft}), ft({post_spacing_ft}))
y_posts = post_positions(ft({building_width_ft}), ft({post_spacing_ft}))

_pidx = 0
def _make_post(prefix, x, y):
    global _pidx
    name = f"Post_{{prefix}}{{_pidx}}"
    p = doc.addObject("Part::Box", name)
    p.Length = POST_SIZE
    p.Width = POST_SIZE
    p.Height = POST_HEIGHT + POST_EMBED
    p.Placement.Base = FreeCAD.Vector(x - POST_SIZE/2, y - POST_SIZE/2, -POST_EMBED)
    set_color(p, 139, 90, 43)
    _pidx += 1
    return name

for x in x_posts:
    _make_post("F", x, 0)
for x in x_posts:
    _make_post("B", x, ft({building_width_ft}))
for y in y_posts[1:-1]:
    _make_post("L", 0, y)
for y in y_posts[1:-1]:
    _make_post("R", ft({building_length_ft}), y)

print(f"Posts: {{_pidx}}")
""")
        return ["posts"]

    def create_wall_girts(self, building_length_ft: float, building_width_ft: float,
                          wall_height_ft: float = 10, girt_spacing_ft: float = 2) -> list[str]:
        self._add(f"""
# Wall Girts - 2x6, {girt_spacing_ft}' vertical spacing
GIRT_W = inches(1.5)
GIRT_D = inches(5.5)
_gidx = 0

def _make_girt(sx, sy, ex, ey, z):
    global _gidx
    name = f"Girt_{{_gidx}}"
    length = math.sqrt((ex-sx)**2 + (ey-sy)**2)
    angle = math.degrees(math.atan2(ey-sy, ex-sx))
    g = doc.addObject("Part::Box", name)
    g.Length = length
    g.Width = GIRT_W
    g.Height = GIRT_D
    g.Placement.Base = FreeCAD.Vector(sx, sy, z)
    g.Placement.Rotation = FreeCAD.Rotation(FreeCAD.Vector(0,0,1), angle)
    set_color(g, 210, 180, 140)
    _gidx += 1

_num_rows = int(ft({wall_height_ft}) / ft({girt_spacing_ft}))
for _row in range(1, _num_rows + 1):
    _z = _row * ft({girt_spacing_ft})
    _make_girt(0, 0, ft({building_length_ft}), 0, _z)
    _make_girt(0, ft({building_width_ft}), ft({building_length_ft}), ft({building_width_ft}), _z)
    _make_girt(0, 0, 0, ft({building_width_ft}), _z)
    _make_girt(ft({building_length_ft}), 0, ft({building_length_ft}), ft({building_width_ft}), _z)

print(f"Girts: {{_gidx}}")
""")
        return ["girts"]

    def create_wainscot(self, building_length_ft: float, building_width_ft: float,
                        wainscot_height_ft: float = 4, thickness_inches: float = 0.5) -> list[str]:
        self._add(f"""
# Wainscot - {wainscot_height_ft}' tall panels
_WAIN_H = ft({wainscot_height_ft})
_WAIN_T = inches({thickness_inches})
_L = ft({building_length_ft})
_W = ft({building_width_ft})

for _wname, _wbase, _wl, _ww, _wh in [
    ("Wainscot_F", FreeCAD.Vector(0, -_WAIN_T, 0), _L, _WAIN_T, _WAIN_H),
    ("Wainscot_B", FreeCAD.Vector(0, _W, 0), _L, _WAIN_T, _WAIN_H),
    ("Wainscot_L", FreeCAD.Vector(-_WAIN_T, 0, 0), _WAIN_T, _W, _WAIN_H),
    ("Wainscot_R", FreeCAD.Vector(_L, 0, 0), _WAIN_T, _W, _WAIN_H),
]:
    _wp = doc.addObject("Part::Box", _wname)
    _wp.Length = _wl
    _wp.Width = _ww
    _wp.Height = _wh
    _wp.Placement.Base = _wbase
    set_color(_wp, 100, 100, 110, transparency=30)
""")
        return ["wainscot"]

    def create_roof_trusses(self, building_length_ft: float, building_width_ft: float,
                            truss_spacing_ft: float = 2, eave_height_ft: float = 10,
                            pitch: float = 4, overhang_ft: float = 1) -> list[str]:
        self._add(f"""
# Roof Trusses - {truss_spacing_ft}' OC, {pitch}:12 pitch, {overhang_ft}' overhang
_PITCH = {pitch}
_EAVE = ft({eave_height_ft})
_SPAN = ft({building_width_ft})
_TLEN = ft({building_length_ft})
_OH = ft({overhang_ft})
_ridge_rise = (_SPAN / 2) * (_PITCH / 12.0)
_ridge_z = _EAVE + _ridge_rise

_tcount = int(_TLEN / ft({truss_spacing_ft})) + 1
_tspacing = _TLEN / (_tcount - 1) if _tcount > 1 else 0

for _ti in range(_tcount):
    _tx = _ti * _tspacing
    _pts = [
        FreeCAD.Vector(_tx, -_OH, _EAVE),
        FreeCAD.Vector(_tx, _SPAN/2, _ridge_z),
        FreeCAD.Vector(_tx, _SPAN + _OH, _EAVE),
    ]
    _tw = Draft.makeWire(_pts, closed=False)
    _tw.Label = f"Truss_{{_ti}}"
    if hasattr(_tw, 'ViewObject') and _tw.ViewObject:
        _tw.ViewObject.LineColor = (0.8, 0.2, 0.2)
        _tw.ViewObject.LineWidth = 2.0

print(f"Trusses: {{_tcount}}")
""")
        return ["trusses"]

    def create_purlins(self, building_length_ft: float, building_width_ft: float,
                       eave_height_ft: float = 10, pitch: float = 4,
                       purlin_spacing_ft: float = 2, overhang_ft: float = 1) -> list[str]:
        self._add(f"""
# Purlins - 2x4, {purlin_spacing_ft}' OC along slope
_P_W = inches(1.5)
_P_D = inches(3.5)
_slope_angle = math.atan({pitch} / 12.0)
_half_span = ft({building_width_ft}) / 2
_p_eave = ft({eave_height_ft})
_p_oh = ft({overhang_ft})
_p_len = ft({building_length_ft})
_slope_len = _half_span / math.cos(_slope_angle)
_total_slope = _slope_len + _p_oh / math.cos(_slope_angle)
_num_purlins = int(_total_slope / ft({purlin_spacing_ft})) + 1
_pcnt = 0

for _pside in ["L", "R"]:
    for _pi in range(_num_purlins):
        _pdist = _pi * ft({purlin_spacing_ft})
        _phoriz = _pdist * math.cos(_slope_angle)
        _pvert = _pdist * math.sin(_slope_angle)
        if _pside == "L":
            _py = -_p_oh + _phoriz
        else:
            _py = ft({building_width_ft}) + _p_oh - _phoriz
        _pz = _p_eave + _pvert
        _pp = doc.addObject("Part::Box", f"Purlin_{{_pside}}{{_pcnt}}")
        _pp.Length = _p_len
        _pp.Width = _P_W
        _pp.Height = _P_D
        _pp.Placement.Base = FreeCAD.Vector(0, _py - _P_W/2, _pz)
        set_color(_pp, 180, 150, 100, transparency=60)
        _pcnt += 1

print(f"Purlins: {{_pcnt}}")
""")
        return ["purlins"]

    def create_ridge_cap(self, building_length_ft: float, building_width_ft: float,
                         eave_height_ft: float = 10, pitch: float = 4,
                         cap_width_inches: float = 12, cap_height_inches: float = 2) -> str:
        self._add(f"""
# Ridge Cap
_rc_span = ft({building_width_ft})
_rc_eave = ft({eave_height_ft})
_rc_ridge_z = _rc_eave + (_rc_span / 2) * ({pitch} / 12.0)
_rc = doc.addObject("Part::Box", "Ridge_Cap")
_rc.Length = ft({building_length_ft})
_rc.Width = inches({cap_width_inches})
_rc.Height = inches({cap_height_inches})
_rc.Placement.Base = FreeCAD.Vector(0, _rc_span/2 - inches({cap_width_inches/2}), _rc_ridge_z)
set_color(_rc, 60, 60, 70, transparency=60)
""")
        return "Ridge_Cap"

    def create_overhead_door(self, name: str, wall: str, position_ft: float,
                             width_ft: float = 10, height_ft: float = 10,
                             building_length_ft: float = 0, building_width_ft: float = 0) -> str:
        # Calculate placement based on wall
        if wall == "front":
            base = f"FreeCAD.Vector(ft({position_ft}), -inches(4), 0)"
            dims = f"ft({width_ft}), inches(4), ft({height_ft})"
        elif wall == "back":
            base = f"FreeCAD.Vector(ft({position_ft}), ft({building_width_ft}), 0)"
            dims = f"ft({width_ft}), inches(4), ft({height_ft})"
        elif wall == "left":
            base = f"FreeCAD.Vector(-inches(4), ft({position_ft}), 0)"
            dims = f"inches(4), ft({width_ft}), ft({height_ft})"
        else:  # right
            base = f"FreeCAD.Vector(ft({building_length_ft}), ft({position_ft}), 0)"
            dims = f"inches(4), ft({width_ft}), ft({height_ft})"

        self._add(f"""
# Overhead Door: {name} ({width_ft}'x{height_ft}' on {wall} wall)
_ohd = doc.addObject("Part::Box", "{name}")
_ohd.Length, _ohd.Width, _ohd.Height = {dims}
_ohd.Placement.Base = {base}
set_color(_ohd, 200, 200, 220, transparency=50)
""")
        return name

    def create_walk_door(self, name: str, wall: str, position_ft: float,
                         width_ft: float = 3, height_ft: float = 6.67,
                         building_length_ft: float = 0, building_width_ft: float = 0) -> str:
        if wall == "front":
            base = f"FreeCAD.Vector(ft({position_ft}), -inches(4), 0)"
            dims = f"ft({width_ft}), inches(4), ft({height_ft})"
        elif wall == "back":
            base = f"FreeCAD.Vector(ft({position_ft}), ft({building_width_ft}), 0)"
            dims = f"ft({width_ft}), inches(4), ft({height_ft})"
        elif wall == "left":
            base = f"FreeCAD.Vector(-inches(4), ft({position_ft}), 0)"
            dims = f"inches(4), ft({width_ft}), ft({height_ft})"
        else:  # right
            base = f"FreeCAD.Vector(ft({building_length_ft}), ft({position_ft}), 0)"
            dims = f"inches(4), ft({width_ft}), ft({height_ft})"

        self._add(f"""
# Walk Door: {name} ({width_ft}'x{height_ft}' on {wall} wall)
_wd = doc.addObject("Part::Box", "{name}")
_wd.Length, _wd.Width, _wd.Height = {dims}
_wd.Placement.Base = {base}
set_color(_wd, 160, 82, 45, transparency=50)
""")
        return name

    def create_window(self, name: str, wall: str, position_ft: float,
                      sill_height_ft: float = 3, width_ft: float = 3, height_ft: float = 4,
                      building_length_ft: float = 0, building_width_ft: float = 0) -> str:
        if wall == "front":
            base = f"FreeCAD.Vector(ft({position_ft}), -inches(2), ft({sill_height_ft}))"
            dims = f"ft({width_ft}), inches(2), ft({height_ft})"
        elif wall == "back":
            base = f"FreeCAD.Vector(ft({position_ft}), ft({building_width_ft}), ft({sill_height_ft}))"
            dims = f"ft({width_ft}), inches(2), ft({height_ft})"
        elif wall == "left":
            base = f"FreeCAD.Vector(-inches(2), ft({position_ft}), ft({sill_height_ft}))"
            dims = f"inches(2), ft({width_ft}), ft({height_ft})"
        else:
            base = f"FreeCAD.Vector(ft({building_length_ft}), ft({position_ft}), ft({sill_height_ft}))"
            dims = f"inches(2), ft({width_ft}), ft({height_ft})"

        self._add(f"""
# Window: {name} ({width_ft}'x{height_ft}' on {wall} wall, sill at {sill_height_ft}')
_win = doc.addObject("Part::Box", "{name}")
_win.Length, _win.Width, _win.Height = {dims}
_win.Placement.Base = {base}
set_color(_win, 173, 216, 230, transparency=60)
""")
        return name

    def create_interior_wall(self, name: str, start_x_ft: float, start_y_ft: float,
                             end_x_ft: float, end_y_ft: float,
                             height_ft: float = 10, thickness_inches: float = 5.5) -> str:
        self._add(f"""
# Interior Wall: {name}
_iw_sx, _iw_sy = ft({start_x_ft}), ft({start_y_ft})
_iw_ex, _iw_ey = ft({end_x_ft}), ft({end_y_ft})
_iw_len = math.sqrt((_iw_ex-_iw_sx)**2 + (_iw_ey-_iw_sy)**2)
_iw_angle = math.degrees(math.atan2(_iw_ey-_iw_sy, _iw_ex-_iw_sx))
_iw_t = inches({thickness_inches})
_iw = doc.addObject("Part::Box", "{name}")
_iw.Length = _iw_len
_iw.Width = _iw_t
_iw.Height = ft({height_ft})
_iw.Placement.Base = FreeCAD.Vector(_iw_sx, _iw_sy - _iw_t/2, 0)
_iw.Placement.Rotation = FreeCAD.Rotation(FreeCAD.Vector(0,0,1), _iw_angle)
set_color(_iw, 220, 220, 200)
""")
        return name

    def create_roof_panels(self, building_length_ft: float, building_width_ft: float,
                           eave_height_ft: float = 10, pitch: float = 4,
                           overhang_ft: float = 1, panel_thickness_inches: float = 0.5,
                           color: str = "charcoal") -> list[str]:
        color_rgb = {
            "charcoal": "50, 50, 55",
            "red": "140, 30, 30",
            "green": "40, 80, 50",
            "tan": "180, 160, 130",
            "white": "240, 240, 240",
            "blue": "40, 60, 100",
            "brown": "100, 70, 40",
            "galvalume": "170, 175, 170",
        }.get(color.lower(), "50, 50, 55")

        self._add(f"""
# Roof Rib Panels - {color}
_rp_pitch = {pitch}
_rp_eave = ft({eave_height_ft})
_rp_span = ft({building_width_ft})
_rp_len = ft({building_length_ft})
_rp_oh = ft({overhang_ft})
_rp_t = inches({panel_thickness_inches})
_rp_slope_angle = math.atan(_rp_pitch / 12.0)
_rp_half = _rp_span / 2
_rp_slope_len = (_rp_half + _rp_oh) / math.cos(_rp_slope_angle)
_rp_ridge_z = _rp_eave + _rp_half * (_rp_pitch / 12.0)

# Build roof as two triangulated panels using Draft wires + Part Face/Extrude
# This avoids rotation pivot issues with Part::Box

# Left slope: 4 corners (eave-left-overhang to ridge)
_rp_ll = FreeCAD.Vector(0, -_rp_oh, _rp_eave)               # front-left eave
_rp_lr = FreeCAD.Vector(_rp_len, -_rp_oh, _rp_eave)          # back-left eave
_rp_rr = FreeCAD.Vector(_rp_len, _rp_half, _rp_ridge_z)      # back ridge
_rp_rl = FreeCAD.Vector(0, _rp_half, _rp_ridge_z)            # front ridge

_rpL_wire = Draft.makeWire([_rp_ll, _rp_lr, _rp_rr, _rp_rl], closed=True)
_rpL_wire.Label = "Roof_Panel_L_Wire"
_rpL_wire.MakeFace = True
doc.recompute()
_rpL = doc.addObject("Part::Extrusion", "Roof_Panel_L")
_rpL.Base = _rpL_wire
_rpL.Dir = FreeCAD.Vector(0, 0, _rp_t)
_rpL.Solid = True
doc.recompute()
set_color(_rpL, {color_rgb}, transparency=70)
if hasattr(_rpL_wire, 'ViewObject') and _rpL_wire.ViewObject:
    _rpL_wire.ViewObject.Visibility = False

# Right slope: 4 corners (ridge to eave-right-overhang)
_rp2_ll = FreeCAD.Vector(0, _rp_half, _rp_ridge_z)           # front ridge
_rp2_lr = FreeCAD.Vector(_rp_len, _rp_half, _rp_ridge_z)     # back ridge
_rp2_rr = FreeCAD.Vector(_rp_len, _rp_span + _rp_oh, _rp_eave) # back-right eave
_rp2_rl = FreeCAD.Vector(0, _rp_span + _rp_oh, _rp_eave)     # front-right eave

_rpR_wire = Draft.makeWire([_rp2_ll, _rp2_lr, _rp2_rr, _rp2_rl], closed=True)
_rpR_wire.Label = "Roof_Panel_R_Wire"
_rpR_wire.MakeFace = True
doc.recompute()
_rpR = doc.addObject("Part::Extrusion", "Roof_Panel_R")
_rpR.Base = _rpR_wire
_rpR.Dir = FreeCAD.Vector(0, 0, _rp_t)
_rpR.Solid = True
doc.recompute()
set_color(_rpR, {color_rgb}, transparency=70)
if hasattr(_rpR_wire, 'ViewObject') and _rpR_wire.ViewObject:
    _rpR_wire.ViewObject.Visibility = False
""")
        return ["Roof_Panel_L", "Roof_Panel_R"]

    def create_wall_panels(self, building_length_ft: float, building_width_ft: float,
                           wall_height_ft: float = 10, panel_thickness_inches: float = 0.5,
                           color: str = "charcoal") -> list[str]:
        color_rgb = {
            "charcoal": "60, 60, 65",
            "red": "150, 35, 35",
            "green": "45, 90, 55",
            "tan": "190, 170, 140",
            "white": "245, 245, 245",
            "blue": "45, 65, 110",
            "brown": "110, 75, 45",
            "galvalume": "175, 180, 175",
        }.get(color.lower(), "60, 60, 65")

        self._add(f"""
# Wall Panels (steel rib) - {color}
_wp_L = ft({building_length_ft})
_wp_W = ft({building_width_ft})
_wp_H = ft({wall_height_ft})
_wp_T = inches({panel_thickness_inches})

for _wpn, _wpb, _wpl, _wpw, _wph in [
    ("Wall_Panel_F", FreeCAD.Vector(0, -_wp_T, 0), _wp_L, _wp_T, _wp_H),
    ("Wall_Panel_B", FreeCAD.Vector(0, _wp_W, 0), _wp_L, _wp_T, _wp_H),
    ("Wall_Panel_L", FreeCAD.Vector(-_wp_T, 0, 0), _wp_T, _wp_W, _wp_H),
    ("Wall_Panel_R", FreeCAD.Vector(_wp_L, 0, 0), _wp_T, _wp_W, _wp_H),
]:
    _wpp = doc.addObject("Part::Box", _wpn)
    _wpp.Length = _wpl
    _wpp.Width = _wpw
    _wpp.Height = _wph
    _wpp.Placement.Base = _wpb
    set_color(_wpp, {color_rgb}, transparency=25)
""")
        return ["Wall_Panel_F", "Wall_Panel_B", "Wall_Panel_L", "Wall_Panel_R"]

    def create_room(self, name: str, x_ft: float, y_ft: float,
                    width_ft: float, depth_ft: float, height_ft: float = 9,
                    wall_thickness_inches: float = 3.5,
                    room_type: str = "room") -> str:
        color_map = {
            "bedroom": "200, 210, 230",
            "bathroom": "180, 220, 220",
            "kitchen": "240, 230, 200",
            "living": "230, 225, 215",
            "great_room": "235, 230, 220",
            "laundry": "210, 210, 220",
            "closet": "220, 215, 210",
            "utility": "200, 200, 200",
            "office": "210, 220, 210",
            "pantry": "225, 215, 200",
            "mudroom": "200, 195, 185",
            "room": "220, 220, 215",
        }
        rgb = color_map.get(room_type.lower(), "220, 220, 215")

        self._add(f"""
# Room: {name} ({room_type}) - {width_ft}'x{depth_ft}' at ({x_ft}', {y_ft}')
_rm_x = ft({x_ft})
_rm_y = ft({y_ft})
_rm_w = ft({width_ft})
_rm_d = ft({depth_ft})
_rm_h = ft({height_ft})
_rm_t = inches({wall_thickness_inches})

# Floor
_rmf = doc.addObject("Part::Box", "{name}_Floor")
_rmf.Length = _rm_w
_rmf.Width = _rm_d
_rmf.Height = inches(0.75)
_rmf.Placement.Base = FreeCAD.Vector(_rm_x, _rm_y, 0)
set_color(_rmf, {rgb})

# Walls (4 sides)
for _rmwn, _rmwb, _rmwl, _rmww, _rmwh in [
    ("{name}_Wall_S", FreeCAD.Vector(_rm_x, _rm_y, 0), _rm_w, _rm_t, _rm_h),
    ("{name}_Wall_N", FreeCAD.Vector(_rm_x, _rm_y + _rm_d - _rm_t, 0), _rm_w, _rm_t, _rm_h),
    ("{name}_Wall_W", FreeCAD.Vector(_rm_x, _rm_y, 0), _rm_t, _rm_d, _rm_h),
    ("{name}_Wall_E", FreeCAD.Vector(_rm_x + _rm_w - _rm_t, _rm_y, 0), _rm_t, _rm_d, _rm_h),
]:
    _rmw = doc.addObject("Part::Box", _rmwn)
    _rmw.Length = _rmwl
    _rmw.Width = _rmww
    _rmw.Height = _rmwh
    _rmw.Placement.Base = _rmwb
    set_color(_rmw, 250, 248, 240, transparency=40)
""")
        return name

    def create_kitchen_fixtures(self, name: str, x_ft: float, y_ft: float,
                                width_ft: float, depth_ft: float,
                                layout: str = "L") -> str:
        self._add(f"""
# Kitchen Fixtures: {name} ({layout}-shape)
_kx = ft({x_ft})
_ky = ft({y_ft})
_kw = ft({width_ft})
_kd = ft({depth_ft})

# Base cabinets (24" deep x 34.5" tall)
_cab_d = inches(24)
_cab_h = inches(34.5)

# South wall cabinets
_kc1 = doc.addObject("Part::Box", "{name}_Cab_S")
_kc1.Length = _kw
_kc1.Width = _cab_d
_kc1.Height = _cab_h
_kc1.Placement.Base = FreeCAD.Vector(_kx, _ky, 0)
set_color(_kc1, 160, 130, 90)

# Countertop (25.5" deep x 1.5" thick)
_kct = doc.addObject("Part::Box", "{name}_Counter_S")
_kct.Length = _kw
_kct.Width = inches(25.5)
_kct.Height = inches(1.5)
_kct.Placement.Base = FreeCAD.Vector(_kx, _ky, _cab_h)
set_color(_kct, 120, 120, 125)
""")
        if layout.upper() in ("L", "U"):
            self._add(f"""
# West wall cabinets (L or U shape)
_kc2 = doc.addObject("Part::Box", "{name}_Cab_W")
_kc2.Length = _cab_d
_kc2.Width = _kd - _cab_d
_kc2.Height = _cab_h
_kc2.Placement.Base = FreeCAD.Vector(_kx, _ky + _cab_d, 0)
set_color(_kc2, 160, 130, 90)

_kct2 = doc.addObject("Part::Box", "{name}_Counter_W")
_kct2.Length = inches(25.5)
_kct2.Width = _kd - _cab_d
_kct2.Height = inches(1.5)
_kct2.Placement.Base = FreeCAD.Vector(_kx, _ky + _cab_d, _cab_h)
set_color(_kct2, 120, 120, 125)
""")
        if layout.upper() == "U":
            self._add(f"""
# North wall cabinets (U shape)
_kc3 = doc.addObject("Part::Box", "{name}_Cab_N")
_kc3.Length = _kw
_kc3.Width = _cab_d
_kc3.Height = _cab_h
_kc3.Placement.Base = FreeCAD.Vector(_kx, _ky + _kd - _cab_d, 0)
set_color(_kc3, 160, 130, 90)

_kct3 = doc.addObject("Part::Box", "{name}_Counter_N")
_kct3.Length = _kw
_kct3.Width = inches(25.5)
_kct3.Height = inches(1.5)
_kct3.Placement.Base = FreeCAD.Vector(_kx, _ky + _kd - _cab_d, _cab_h)
set_color(_kct3, 120, 120, 125)
""")
        # Island
        self._add(f"""
# Kitchen Island (4'x3')
_ki = doc.addObject("Part::Box", "{name}_Island")
_ki.Length = ft(4)
_ki.Width = ft(3)
_ki.Height = inches(36)
_ki.Placement.Base = FreeCAD.Vector(_kx + _kw/2 - ft(2), _ky + _kd/2 - ft(1), 0)
set_color(_ki, 140, 115, 80)

_kit = doc.addObject("Part::Box", "{name}_Island_Top")
_kit.Length = ft(4.5)
_kit.Width = ft(3.5)
_kit.Height = inches(1.5)
_kit.Placement.Base = FreeCAD.Vector(_kx + _kw/2 - ft(2.25), _ky + _kd/2 - ft(1.25), inches(36))
set_color(_kit, 120, 120, 125)
""")
        return name

    def create_bathroom_fixtures(self, name: str, x_ft: float, y_ft: float,
                                 width_ft: float, depth_ft: float,
                                 has_tub: bool = True) -> str:
        self._add(f"""
# Bathroom Fixtures: {name}
_bx = ft({x_ft})
_by = ft({y_ft})

# Toilet (18"x28")
_bt = doc.addObject("Part::Box", "{name}_Toilet")
_bt.Length = inches(18)
_bt.Width = inches(28)
_bt.Height = inches(16)
_bt.Placement.Base = FreeCAD.Vector(_bx + ft({width_ft}) - inches(24), _by + inches(6), 0)
set_color(_bt, 240, 240, 245)

# Vanity (24"x21"x34")
_bv = doc.addObject("Part::Box", "{name}_Vanity")
_bv.Length = inches(36)
_bv.Width = inches(21)
_bv.Height = inches(34)
_bv.Placement.Base = FreeCAD.Vector(_bx + inches(6), _by + inches(3), 0)
set_color(_bv, 150, 125, 90)

# Vanity top
_bvt = doc.addObject("Part::Box", "{name}_VanityTop")
_bvt.Length = inches(37)
_bvt.Width = inches(22)
_bvt.Height = inches(1)
_bvt.Placement.Base = FreeCAD.Vector(_bx + inches(5.5), _by + inches(2.5), inches(34))
set_color(_bvt, 200, 200, 205)
""")
        if has_tub:
            self._add(f"""
# Bathtub (60"x30"x16")
_btub = doc.addObject("Part::Box", "{name}_Tub")
_btub.Length = inches(60)
_btub.Width = inches(30)
_btub.Height = inches(16)
_btub.Placement.Base = FreeCAD.Vector(_bx + inches(3), _by + ft({depth_ft}) - inches(33), 0)
set_color(_btub, 235, 235, 240)
""")
        else:
            self._add(f"""
# Shower (36"x36"x80")
_bsh = doc.addObject("Part::Box", "{name}_Shower")
_bsh.Length = inches(36)
_bsh.Width = inches(36)
_bsh.Height = inches(80)
_bsh.Placement.Base = FreeCAD.Vector(_bx + inches(3), _by + ft({depth_ft}) - inches(39), 0)
set_color(_bsh, 210, 230, 235, transparency=30)
""")
        return name

    def build_macro(self) -> str:
        """Return the complete macro source code."""
        save_line = f'SAVE_PATH = r"{self.save_path}"'
        return MACRO_HEADER + save_line + "\n" + "\n".join(self.lines) + MACRO_FOOTER

    def write_macro(self, path: str) -> str:
        """Write the macro to a file and return the path."""
        code = self.build_macro()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(code)
        return path
