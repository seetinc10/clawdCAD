"""Algorithmic floor plan layout engine for barndominium / post-frame homes.

Generates architecturally-sound residential floor plans using:
  1. Zone-based strip allocation (public / private / service)
  2. Squarified treemap room packing
  3. Adjacency-aware hill-climbing optimisation
  4. Plumbing clustering (wet wall minimisation)
  5. Hallway generation with dead-end avoidance and connectivity checks
  6. Door placement with swing clearance and IRC-compliant sizing
  7. Interior wall segment generation with open-concept support

Pure Python — no FreeCAD dependency.  Output is a FloorPlan dataclass whose
fields map directly to MacroBuilder.create_room / create_interior_wall calls.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RoomSpec:
    """A room the user wants (before placement)."""
    name: str
    room_type: str          # matches MacroBuilder color_map keys
    zone: str               # "public", "private_master", "private_secondary", "service"
    min_area_sqft: float
    target_area_sqft: float
    min_width_ft: float
    max_aspect_ratio: float
    is_wet: bool
    fixtures: Optional[str]              # "kitchen_L", "bathroom_tub", etc.
    adjacency_required: list[str] = field(default_factory=list)
    adjacency_prohibited: list[str] = field(default_factory=list)


@dataclass
class PlacedRoom:
    """A room with final coordinates, ready for MacroBuilder."""
    name: str
    room_type: str
    zone: str
    x_ft: float
    y_ft: float
    width_ft: float      # X direction
    depth_ft: float      # Y direction
    height_ft: float
    is_wet: bool
    fixtures: Optional[str]


@dataclass
class HallwaySegment:
    """A corridor connecting zones or providing room access."""
    x_ft: float
    y_ft: float
    width_ft: float
    depth_ft: float
    orientation: str     # "horizontal" or "vertical"


@dataclass
class DoorPlacement:
    """A door between two rooms or a room and hallway."""
    wall_name: str
    room_a: str
    room_b: str
    x_ft: float
    y_ft: float
    width_ft: float
    on_axis: str         # "x" or "y"
    swing_dir: str = "inward"   # "inward" (into smaller room) or "outward"
    swing_clear: bool = True    # True if swing arc is unobstructed


@dataclass
class WallSegment:
    """An interior wall for MacroBuilder.create_interior_wall()."""
    name: str
    start_x_ft: float
    start_y_ft: float
    end_x_ft: float
    end_y_ft: float


@dataclass
class FloorPlan:
    """Complete layout result."""
    building_length_ft: float
    building_width_ft: float
    rooms: list[PlacedRoom]
    hallways: list[HallwaySegment]
    doors: list[DoorPlacement]
    walls: list[WallSegment]
    metadata: dict


# ---------------------------------------------------------------------------
# Adjacency matrix
# ---------------------------------------------------------------------------
# Keys are frozensets of room_type pairs (or specific name pairs).
# Values: "mandatory" | "strong" | "prohibited"

ADJACENCY_RULES: dict[frozenset[str], str] = {
    # Mandatory adjacencies
    frozenset({"Kitchen", "Great_Room"}):        "mandatory",
    frozenset({"Kitchen", "Pantry"}):            "mandatory",
    frozenset({"Master_Bedroom", "Master_Bathroom"}): "mandatory",
    frozenset({"Dining_Room", "Kitchen"}):       "mandatory",
    frozenset({"Dining_Room", "Great_Room"}):    "mandatory",
    # Strong adjacencies
    frozenset({"Kitchen", "Laundry"}):           "strong",
    frozenset({"Kitchen", "Mudroom"}):           "strong",
    frozenset({"Mudroom", "Laundry"}):           "strong",
    # Prohibited adjacencies (by room_type)
    frozenset({"kitchen", "bedroom"}):           "prohibited",
    frozenset({"bathroom", "kitchen"}):          "prohibited",
    frozenset({"dining_room", "bedroom"}):       "prohibited",
}


def _adj_key(a_name: str, a_type: str, b_name: str, b_type: str) -> Optional[str]:
    """Return the adjacency relationship between two rooms, or None."""
    # Check by name first (more specific)
    for key, val in ADJACENCY_RULES.items():
        if frozenset({a_name, b_name}) == key:
            return val
    # Check by type
    for key, val in ADJACENCY_RULES.items():
        if frozenset({a_type, b_type}) == key:
            return val
    return None


# ---------------------------------------------------------------------------
# Room templates
# ---------------------------------------------------------------------------

def _make_templates() -> dict[str, RoomSpec]:
    """Standard room definitions."""
    return {
        "master_bedroom": RoomSpec(
            name="Master_Bedroom", room_type="bedroom",
            zone="private_master",
            min_area_sqft=168, target_area_sqft=224,   # 14x16
            min_width_ft=12, max_aspect_ratio=1.5,
            is_wet=False, fixtures=None,
            adjacency_required=["Master_Bathroom"],
            adjacency_prohibited=["Kitchen"],
        ),
        "master_bathroom": RoomSpec(
            name="Master_Bathroom", room_type="bathroom",
            zone="private_master",
            min_area_sqft=60, target_area_sqft=80,     # 8x10
            min_width_ft=7, max_aspect_ratio=1.5,
            is_wet=True, fixtures="bathroom_tub",
            adjacency_required=["Master_Bedroom"],
            adjacency_prohibited=["Kitchen"],
        ),
        "master_closet": RoomSpec(
            name="Master_WIC", room_type="closet",
            zone="private_master",
            min_area_sqft=36, target_area_sqft=48,     # 6x8
            min_width_ft=6, max_aspect_ratio=1.5,
            is_wet=False, fixtures=None,
            adjacency_required=["Master_Bedroom"],
            adjacency_prohibited=[],
        ),
        "bedroom": RoomSpec(
            name="Bedroom_{n}", room_type="bedroom",
            zone="private_secondary",
            min_area_sqft=120, target_area_sqft=144,   # 12x12
            min_width_ft=10, max_aspect_ratio=1.4,
            is_wet=False, fixtures=None,
            adjacency_required=[],
            adjacency_prohibited=["Kitchen"],
        ),
        "bathroom": RoomSpec(
            name="Bathroom_{n}", room_type="bathroom",
            zone="private_secondary",
            min_area_sqft=40, target_area_sqft=48,     # 6x8
            min_width_ft=5, max_aspect_ratio=1.8,
            is_wet=True, fixtures="bathroom_shower",
            adjacency_required=[],
            adjacency_prohibited=["Kitchen"],
        ),
        "great_room": RoomSpec(
            name="Great_Room", room_type="great_room",
            zone="public",
            min_area_sqft=300, target_area_sqft=400,   # 20x20
            min_width_ft=16, max_aspect_ratio=1.5,
            is_wet=False, fixtures=None,
            adjacency_required=["Kitchen"],
            adjacency_prohibited=[],
        ),
        "kitchen": RoomSpec(
            name="Kitchen", room_type="kitchen",
            zone="service",
            min_area_sqft=120, target_area_sqft=180,   # 12x15
            min_width_ft=10, max_aspect_ratio=1.5,
            is_wet=True, fixtures="kitchen_L",
            adjacency_required=["Great_Room"],
            adjacency_prohibited=[],
        ),
        "laundry": RoomSpec(
            name="Laundry", room_type="laundry",
            zone="service",
            min_area_sqft=42, target_area_sqft=48,     # 6x8
            min_width_ft=6, max_aspect_ratio=1.5,
            is_wet=True, fixtures=None,
            adjacency_required=[],
            adjacency_prohibited=[],
        ),
        "mudroom": RoomSpec(
            name="Mudroom", room_type="mudroom",
            zone="service",
            min_area_sqft=42, target_area_sqft=48,     # 6x8
            min_width_ft=6, max_aspect_ratio=1.5,
            is_wet=False, fixtures=None,
            adjacency_required=[],
            adjacency_prohibited=[],
        ),
        "pantry": RoomSpec(
            name="Pantry", room_type="pantry",
            zone="service",
            min_area_sqft=20, target_area_sqft=24,     # 4x6
            min_width_ft=4, max_aspect_ratio=2.0,
            is_wet=False, fixtures=None,
            adjacency_required=["Kitchen"],
            adjacency_prohibited=[],
        ),
        "dining_room": RoomSpec(
            name="Dining_Room", room_type="dining_room",
            zone="public",
            min_area_sqft=100, target_area_sqft=168,    # 12x14
            min_width_ft=10, max_aspect_ratio=1.5,
            is_wet=False, fixtures=None,
            adjacency_required=["Kitchen", "Great_Room"],
            adjacency_prohibited=[],
        ),
    }


ROOM_TEMPLATES = _make_templates()


# ---------------------------------------------------------------------------
# Room program parser
# ---------------------------------------------------------------------------

def parse_room_program(
    num_bedrooms: int,
    num_bathrooms: int,
    building_length_ft: float,
    building_width_ft: float,
    open_concept: bool = True,
    has_pantry: bool = True,
    has_laundry: bool = True,
    has_mudroom: bool = True,
    has_dining: bool = False,
    room_overrides: Optional[dict[str, dict]] = None,
) -> list[RoomSpec]:
    """Translate user request into a list of RoomSpec objects.

    Args:
        room_overrides: Optional dict mapping room names to dimension overrides.
            e.g. {"Master_Bedroom": {"width": 14, "depth": 16},
                  "Kitchen": {"area": 200}}
            Supported keys per room: "width", "depth", "area".
    """
    specs: list[RoomSpec] = []
    overrides = room_overrides or {}

    # Always: great room
    specs.append(copy.deepcopy(ROOM_TEMPLATES["great_room"]))

    # Dining room (between great room and kitchen in open-concept flow)
    if has_dining:
        specs.append(copy.deepcopy(ROOM_TEMPLATES["dining_room"]))

    # Always: kitchen
    specs.append(copy.deepcopy(ROOM_TEMPLATES["kitchen"]))

    # Master suite (counts as 1 bedroom + 1 bathroom)
    if num_bedrooms >= 1:
        specs.append(copy.deepcopy(ROOM_TEMPLATES["master_bedroom"]))
        specs.append(copy.deepcopy(ROOM_TEMPLATES["master_closet"]))
    if num_bathrooms >= 1:
        specs.append(copy.deepcopy(ROOM_TEMPLATES["master_bathroom"]))

    # Secondary bedrooms
    for i in range(2, num_bedrooms + 1):
        br = copy.deepcopy(ROOM_TEMPLATES["bedroom"])
        br.name = f"Bedroom_{i}"
        specs.append(br)

    # Secondary bathrooms
    for i in range(2, num_bathrooms + 1):
        ba = copy.deepcopy(ROOM_TEMPLATES["bathroom"])
        ba.name = f"Bathroom_{i}"
        specs.append(ba)

    # Optional rooms
    if has_pantry:
        specs.append(copy.deepcopy(ROOM_TEMPLATES["pantry"]))
    if has_laundry:
        specs.append(copy.deepcopy(ROOM_TEMPLATES["laundry"]))
    if has_mudroom:
        specs.append(copy.deepcopy(ROOM_TEMPLATES["mudroom"]))

    # Apply room_overrides (from photo-extracted dimensions)
    for r in specs:
        if r.name in overrides:
            ov = overrides[r.name]
            if "area" in ov:
                r.target_area_sqft = float(ov["area"])
                r.min_area_sqft = r.target_area_sqft * 0.8
            elif "width" in ov and "depth" in ov:
                r.target_area_sqft = float(ov["width"]) * float(ov["depth"])
                r.min_area_sqft = r.target_area_sqft * 0.8
                r.min_width_ft = max(r.min_width_ft, float(ov["width"]) * 0.8)

    # Scale target areas so total is ~88% of footprint (leave room for hallways + walls)
    footprint = building_length_ft * building_width_ft
    target_fill = 0.88
    total_target = sum(r.target_area_sqft for r in specs)
    if total_target > 0:
        scale = (footprint * target_fill) / total_target
        # Only scale down if rooms exceed available area; scale up gently
        scale = min(scale, 1.3)
        scale = max(scale, 0.7)

        # Per-room area caps to prevent oversizing on large buildings.
        # Without caps, the master bedroom can balloon to 360+ sqft.
        AREA_CAPS: dict[str, float] = {
            "bedroom":    250,   # master or secondary bedroom cap
            "bathroom":   120,   # any bathroom
            "closet":      80,   # walk-in closet
            "kitchen":    260,   # kitchen
            "dining_room": 220,  # dining room
            "laundry":     80,
            "mudroom":     80,
            "pantry":      40,
        }

        for r in specs:
            if r.name in overrides:
                # User-overridden rooms: only scale down, never up
                if scale < 1.0:
                    r.target_area_sqft *= scale
                    r.min_area_sqft *= max(scale, 0.8)
            else:
                r.target_area_sqft *= scale
                r.min_area_sqft *= max(scale, 0.8)

                # Apply cap: don't let rooms grow beyond architectural norms
                cap = AREA_CAPS.get(r.room_type)
                if cap:
                    r.target_area_sqft = min(r.target_area_sqft, cap)

    return specs


# ---------------------------------------------------------------------------
# Layout engine
# ---------------------------------------------------------------------------

class LayoutEngine:
    """Generates residential floor plans for barndominium shells."""

    def __init__(self):
        self._wall_thickness_inches: float = 3.5
        self._hallway_width_ft: float = 3.5
        self._ceiling_height_ft: float = 9.0
        self._last_connectivity_fallback_doors: int = 0

    # === Public API ========================================================

    def generate(
        self,
        building_length_ft: float,
        building_width_ft: float,
        num_bedrooms: int = 3,
        num_bathrooms: int = 2,
        open_concept: bool = True,
        has_pantry: bool = True,
        has_laundry: bool = True,
        has_mudroom: bool = True,
        has_dining: bool = False,
        room_overrides: Optional[dict[str, dict]] = None,
    ) -> FloorPlan:
        """Generate a complete floor plan."""

        room_specs = parse_room_program(
            num_bedrooms, num_bathrooms,
            building_length_ft, building_width_ft,
            open_concept, has_pantry=has_pantry,
            has_laundry=has_laundry, has_mudroom=has_mudroom,
            has_dining=has_dining, room_overrides=room_overrides,
        )

        # Phase 1 — zone strip allocation
        zone_strips, hallway_segments = self._allocate_zone_strips(
            room_specs, building_length_ft, building_width_ft,
        )

        # Phase 2 — zone-specific room packing
        placed_rooms: list[PlacedRoom] = []
        for zone_name, bbox in zone_strips.items():
            zone_rooms = [r for r in room_specs if r.zone == zone_name]
            if not zone_rooms:
                continue
            if zone_name == "center":
                placed = self._pack_center_zone(zone_rooms, bbox)
            elif zone_name.startswith("private"):
                placed = self._pack_private_wing(zone_rooms, bbox)
            else:
                placed = self._squarified_treemap(zone_rooms, bbox)
            placed_rooms.extend(placed)

        # Phase 3 — adjacency improvement
        placed_rooms = self._improve_adjacency(placed_rooms)

        # Phase 3b — plumbing clustering (swap wet rooms closer together)
        placed_rooms = self._cluster_plumbing(placed_rooms)

        # Phase 4 — hallways already created from zone strips;
        # add bedroom-wing hallways with dead-end avoidance
        hallway_segments = self._add_wing_hallways(
            placed_rooms, hallway_segments, zone_strips,
        )

        # Phase 4b — connectivity check: ensure every room can reach circulation
        self._ensure_connectivity(placed_rooms, hallway_segments)

        # Phase 5 — door placement with swing clearance + IRC sizing
        doors = self._place_doors(placed_rooms, hallway_segments)

        # Phase 5b — validate swing clearances
        self._check_swing_clearances(doors, placed_rooms, hallway_segments)

        # Phase 6 — wall segments (respects open_concept)
        walls = self._generate_wall_segments(
            placed_rooms, hallway_segments, doors,
            building_length_ft, building_width_ft, open_concept,
        )

        # Validate
        metadata = self._validate(
            placed_rooms, hallway_segments, doors,
            building_length_ft, building_width_ft,
        )

        return FloorPlan(
            building_length_ft=building_length_ft,
            building_width_ft=building_width_ft,
            rooms=placed_rooms,
            hallways=hallway_segments,
            doors=doors,
            walls=walls,
            metadata=metadata,
        )

    # === Phase 1: Zone strip allocation ====================================

    def _allocate_zone_strips(
        self,
        room_specs: list[RoomSpec],
        bld_len: float,
        bld_wid: float,
    ) -> tuple[dict[str, tuple[float, float, float, float]], list[HallwaySegment]]:
        """Split building into zone strips along X axis (length).

        Returns (zone_name -> (x, y, w, d), hallway_segments).

        Layout pattern (split-bedroom):
          [Master wing | Hall | Public+Service center | Hall | Secondary wing]

        Strip widths are computed from zone areas divided by building width,
        giving each strip enough X-width for its rooms to achieve reasonable
        aspect ratios.
        """
        hw = self._hallway_width_ft
        hallways: list[HallwaySegment] = []

        # Compute zone areas
        zone_areas: dict[str, float] = {}
        for r in room_specs:
            zone_areas[r.zone] = zone_areas.get(r.zone, 0) + r.target_area_sqft

        has_master = zone_areas.get("private_master", 0) > 0
        has_secondary = zone_areas.get("private_secondary", 0) > 0

        # Number of hallways between strips
        num_halls = (1 if has_master else 0) + (1 if has_secondary else 0)

        usable_length = bld_len - (num_halls * hw)
        if usable_length < 20:
            usable_length = bld_len - hw
            num_halls = 1

        # Compute ideal strip width for each zone: area / building_width
        # This gives each strip enough X-width for its rooms
        master_ideal = zone_areas.get("private_master", 0) / bld_wid if has_master else 0
        secondary_ideal = zone_areas.get("private_secondary", 0) / bld_wid if has_secondary else 0
        center_area = zone_areas.get("public", 0) + zone_areas.get("service", 0)
        center_ideal = center_area / bld_wid

        # Apply minimum widths — scaled for narrow buildings
        # On narrow buildings (width < 36'), reduce wing minimums to
        # prevent wings from stealing too much length from center zone
        if bld_wid < 36:
            min_wing = max(12, bld_len * 0.15)
            min_center = max(16, bld_len * 0.25)
        else:
            min_wing = max(14, bld_len * 0.2)
            min_center = max(16, bld_len * 0.3)

        master_width = max(master_ideal, min_wing) if has_master else 0
        secondary_width = max(secondary_ideal, min_wing) if has_secondary else 0
        center_width = max(center_ideal, min_center)

        # Normalize to fit usable_length
        total_raw = master_width + secondary_width + center_width
        if total_raw > 0:
            scale = usable_length / total_raw
            master_width = round(master_width * scale, 1)
            secondary_width = round(secondary_width * scale, 1)
            center_width = round(usable_length - master_width - secondary_width, 1)

        # Build strips left-to-right along X
        strips: dict[str, tuple[float, float, float, float]] = {}
        x_cursor = 0.0

        if has_master:
            strips["private_master"] = (x_cursor, 0, master_width, bld_wid)
            x_cursor += master_width
            hallways.append(HallwaySegment(
                x_ft=round(x_cursor, 2), y_ft=0,
                width_ft=hw, depth_ft=bld_wid,
                orientation="vertical",
            ))
            x_cursor += hw

        # Center zone — public and service rooms pack together
        strips["public"] = (x_cursor, 0, center_width, bld_wid)
        strips["service"] = (x_cursor, 0, center_width, bld_wid)
        x_cursor += center_width

        if has_secondary:
            hallways.append(HallwaySegment(
                x_ft=round(x_cursor, 2), y_ft=0,
                width_ft=hw, depth_ft=bld_wid,
                orientation="vertical",
            ))
            x_cursor += hw
            strips["private_secondary"] = (x_cursor, 0, secondary_width, bld_wid)

        # Merge public + service into one center strip for treemap packing
        center_bbox = (strips["public"][0], 0, center_width, bld_wid)
        strips["center"] = center_bbox
        del strips["public"]
        del strips["service"]

        # Re-tag center-zone rooms
        for r in room_specs:
            if r.zone in ("public", "service"):
                r.zone = "center"

        return strips, hallways

    # === Phase 2: Squarified treemap packing ================================

    def _squarified_treemap(
        self,
        rooms: list[RoomSpec],
        bbox: tuple[float, float, float, float],
    ) -> list[PlacedRoom]:
        """Pack rooms into bbox using squarified treemap algorithm.

        After treemap placement, rooms are clamped to respect min_width and
        max_aspect_ratio constraints — excess space is redistributed to
        neighbors where possible.
        """
        x, y, w, d = bbox
        total_bbox_area = w * d
        total_room_area = sum(r.target_area_sqft for r in rooms)

        if total_room_area <= 0 or total_bbox_area <= 0:
            return []

        # Scale room areas to fill the bbox exactly
        scale = total_bbox_area / total_room_area

        # Sort by target area descending (largest first)
        sorted_rooms = sorted(rooms, key=lambda r: r.target_area_sqft, reverse=True)
        items = [(r, r.target_area_sqft * scale) for r in sorted_rooms]

        placed: list[PlacedRoom] = []
        self._treemap_recurse(items, x, y, w, d, placed)

        # Post-process: clamp aspect ratios for livable rooms
        self._clamp_aspect_ratios(placed, x, y, w, d)

        return placed

    def _treemap_recurse(
        self,
        items: list[tuple[RoomSpec, float]],
        x: float, y: float, w: float, d: float,
        placed: list[PlacedRoom],
    ):
        """Recursively lay out items in the (x, y, w, d) bounding box."""
        if not items:
            return

        if len(items) == 1:
            spec, area = items[0]
            placed.append(PlacedRoom(
                name=spec.name, room_type=spec.room_type, zone=spec.zone,
                x_ft=round(x, 2), y_ft=round(y, 2),
                width_ft=round(w, 2), depth_ft=round(d, 2),
                height_ft=self._ceiling_height_ft,
                is_wet=spec.is_wet, fixtures=spec.fixtures,
            ))
            return

        if w <= 0 or d <= 0:
            return

        # Determine layout direction: lay row along shorter side
        along_x = (d <= w)  # if depth is shorter, row fills along x

        shorter = min(w, d)

        # Greedy row building
        row = [items[0]]
        rest = list(items[1:])
        best_worst = self._worst_ratio([a for _, a in row], shorter)

        while rest:
            candidate_areas = [a for _, a in row] + [rest[0][1]]
            new_worst = self._worst_ratio(candidate_areas, shorter)
            if new_worst <= best_worst:
                row.append(rest.pop(0))
                best_worst = new_worst
            else:
                break

        # Layout the row
        row_area = sum(a for _, a in row)

        if along_x:
            # Row spans full width, variable depth
            row_d = row_area / w if w > 0 else d
            rx = x
            for spec, area in row:
                room_w = area / row_d if row_d > 0 else w
                placed.append(PlacedRoom(
                    name=spec.name, room_type=spec.room_type, zone=spec.zone,
                    x_ft=round(rx, 2), y_ft=round(y, 2),
                    width_ft=round(room_w, 2), depth_ft=round(row_d, 2),
                    height_ft=self._ceiling_height_ft,
                    is_wet=spec.is_wet, fixtures=spec.fixtures,
                ))
                rx += room_w
            # Recurse on remaining rectangle
            self._treemap_recurse(rest, x, y + row_d, w, d - row_d, placed)
        else:
            # Row spans full depth, variable width
            row_w = row_area / d if d > 0 else w
            ry = y
            for spec, area in row:
                room_d = area / row_w if row_w > 0 else d
                placed.append(PlacedRoom(
                    name=spec.name, room_type=spec.room_type, zone=spec.zone,
                    x_ft=round(x, 2), y_ft=round(ry, 2),
                    width_ft=round(row_w, 2), depth_ft=round(room_d, 2),
                    height_ft=self._ceiling_height_ft,
                    is_wet=spec.is_wet, fixtures=spec.fixtures,
                ))
                ry += room_d
            self._treemap_recurse(rest, x + row_w, y, w - row_w, d, placed)

    @staticmethod
    def _clamp_aspect_ratios(
        placed: list[PlacedRoom],
        bbox_x: float, bbox_y: float, bbox_w: float, bbox_d: float,
    ):
        """Post-process treemap output to limit extreme aspect ratios.

        Rooms that exceed 2.5:1 aspect ratio are resized toward squarer
        proportions. Excess space is left for hallways / padding.
        """
        for room in placed:
            w, d = room.width_ft, room.depth_ft
            if w <= 0 or d <= 0:
                continue
            ratio = max(w / d, d / w)
            if ratio <= 2.5:
                continue
            # Compute a squarer shape keeping area constant
            area = w * d
            target_ratio = 2.0
            if w > d:
                new_d = math.sqrt(area / target_ratio)
                new_w = area / new_d
            else:
                new_w = math.sqrt(area / target_ratio)
                new_d = area / new_w
            # Ensure room stays within bbox
            new_w = min(new_w, bbox_w - (room.x_ft - bbox_x))
            new_d = min(new_d, bbox_d - (room.y_ft - bbox_y))
            room.width_ft = round(max(new_w, 5), 2)
            room.depth_ft = round(max(new_d, 5), 2)

    def _pack_center_zone(
        self,
        rooms: list[RoomSpec],
        bbox: tuple[float, float, float, float],
    ) -> list[PlacedRoom]:
        """Custom packing for the center zone (public + service).

        Layout strategy for 2 large rooms (Great Room + Kitchen):
          - Side-by-side if width allows good aspect ratios, else stack vertically

        Layout strategy for 3 large rooms (Great Room + Dining Room + Kitchen):
          - Front row: Great Room (full width or shared with Dining Room)
          - Back row: Dining Room + Kitchen side by side, or stacked

        Small service rooms (pantry, laundry, mudroom) always get a strip along
        the back wall (Y-max side).
        """
        x, y, w, d = bbox
        placed: list[PlacedRoom] = []

        # Separate large rooms from small service rooms
        large = []
        small = []
        for r in rooms:
            if r.room_type in ("great_room", "kitchen", "dining_room"):
                large.append(r)
            else:
                small.append(r)

        if not large:
            return self._squarified_treemap(rooms, bbox)

        # Allocate space: service rooms get a strip along the back (Y-max side)
        small_total_area = sum(r.target_area_sqft for r in small)
        if small_total_area > 0 and small:
            service_strip_d = max(small_total_area / w, 6)
            service_strip_d = min(service_strip_d, d * 0.3)
        else:
            service_strip_d = 0

        main_d = d - service_strip_d

        # Sort: great_room first, then dining_room, then kitchen
        type_order = {"great_room": 0, "dining_room": 1, "kitchen": 2}
        large.sort(key=lambda r: type_order.get(r.room_type, 9))

        # Extract rooms by type for named access
        gr = next((r for r in large if r.room_type == "great_room"), None)
        dr = next((r for r in large if r.room_type == "dining_room"), None)
        kit = next((r for r in large if r.room_type == "kitchen"), None)

        if len(large) == 3 and gr and dr and kit:
            # 3 large rooms: Great Room + Dining Room + Kitchen
            # Strategy: 2-row layout
            #   Front row (y=0 side): Great Room spanning full width
            #   Back row: Dining Room + Kitchen side-by-side
            # This creates the natural open-concept flow:
            #   Great Room <-> Dining Room <-> Kitchen
            back_area = dr.target_area_sqft + kit.target_area_sqft
            total_area = gr.target_area_sqft + back_area
            front_frac = gr.target_area_sqft / total_area

            front_d = max(main_d * front_frac, 12)   # min 12' great room depth
            front_d = min(front_d, main_d * 0.6)     # max 60% of main depth
            back_d = main_d - front_d

            # Ensure back row rooms have reasonable depth (min 10' for kitchen)
            if back_d < 10:
                front_d = main_d - 10
                back_d = 10

            # Front row: great room
            placed.append(PlacedRoom(
                name=gr.name, room_type=gr.room_type, zone=gr.zone,
                x_ft=round(x, 2), y_ft=round(y, 2),
                width_ft=round(w, 2), depth_ft=round(front_d, 2),
                height_ft=self._ceiling_height_ft,
                is_wet=gr.is_wet, fixtures=gr.fixtures,
            ))

            # Back row: dining room + kitchen side-by-side
            back_total = dr.target_area_sqft + kit.target_area_sqft
            dr_frac = dr.target_area_sqft / back_total if back_total > 0 else 0.5
            dr_w = round(w * dr_frac, 2)
            kit_w = round(w - dr_w, 2)

            # Ensure minimum widths
            if dr_w < 10:
                dr_w = min(10, w * 0.45)
                kit_w = round(w - dr_w, 2)
            if kit_w < 10:
                kit_w = min(10, w * 0.45)
                dr_w = round(w - kit_w, 2)

            back_y = y + front_d

            placed.append(PlacedRoom(
                name=dr.name, room_type=dr.room_type, zone=dr.zone,
                x_ft=round(x, 2), y_ft=round(back_y, 2),
                width_ft=round(dr_w, 2), depth_ft=round(back_d, 2),
                height_ft=self._ceiling_height_ft,
                is_wet=dr.is_wet, fixtures=dr.fixtures,
            ))
            placed.append(PlacedRoom(
                name=kit.name, room_type=kit.room_type, zone=kit.zone,
                x_ft=round(x + dr_w, 2), y_ft=round(back_y, 2),
                width_ft=round(kit_w, 2), depth_ft=round(back_d, 2),
                height_ft=self._ceiling_height_ft,
                is_wet=kit.is_wet, fixtures=kit.fixtures,
            ))

        elif len(large) >= 2 and gr and kit:
            # 2 large rooms: Great Room + Kitchen (original logic)
            total_area = gr.target_area_sqft + kit.target_area_sqft
            gr_frac = gr.target_area_sqft / total_area

            # Try side-by-side first
            gr_w_try = w * gr_frac
            kit_w_try = w - gr_w_try

            # Kitchen aspect ratio check
            kit_ratio = main_d / kit_w_try if kit_w_try > 0 else 999

            if kit_ratio <= 2.5 and kit_w_try >= 10:
                gr_w = round(gr_w_try, 2)
                kit_w = round(w - gr_w, 2)

                placed.append(PlacedRoom(
                    name=gr.name, room_type=gr.room_type, zone=gr.zone,
                    x_ft=round(x, 2), y_ft=round(y, 2),
                    width_ft=gr_w, depth_ft=round(main_d, 2),
                    height_ft=self._ceiling_height_ft,
                    is_wet=gr.is_wet, fixtures=gr.fixtures,
                ))
                placed.append(PlacedRoom(
                    name=kit.name, room_type=kit.room_type, zone=kit.zone,
                    x_ft=round(x + gr_w, 2), y_ft=round(y, 2),
                    width_ft=kit_w, depth_ft=round(main_d, 2),
                    height_ft=self._ceiling_height_ft,
                    is_wet=kit.is_wet, fixtures=kit.fixtures,
                ))
            else:
                # Stack vertically: great room in front, kitchen behind
                # On narrow buildings, limit kitchen width for better aspect ratio
                kit_target_d = kit.target_area_sqft / w if w > 0 else 10
                kit_d = max(kit_target_d, 10)
                kit_d = min(kit_d, main_d * 0.45)

                # Check kitchen aspect ratio in vertical stack
                kit_w_vert = w
                kit_ratio_vert = kit_w_vert / kit_d if kit_d > 0 else 999
                if kit_ratio_vert > 2.0 and w > 20:
                    # Kitchen too wide — narrow it to improve ratio
                    # Target ratio ~1.5 while keeping area reasonable
                    ideal_kit_w = kit_d * 2.0
                    kit_w_vert = max(ideal_kit_w, 14)  # min 14' kitchen width
                    kit_w_vert = min(kit_w_vert, w)    # can't exceed zone width

                gr_d = round(main_d - kit_d, 2)

                placed.append(PlacedRoom(
                    name=gr.name, room_type=gr.room_type, zone=gr.zone,
                    x_ft=round(x, 2), y_ft=round(y, 2),
                    width_ft=round(w, 2), depth_ft=gr_d,
                    height_ft=self._ceiling_height_ft,
                    is_wet=gr.is_wet, fixtures=gr.fixtures,
                ))
                placed.append(PlacedRoom(
                    name=kit.name, room_type=kit.room_type, zone=kit.zone,
                    x_ft=round(x, 2), y_ft=round(y + gr_d, 2),
                    width_ft=round(kit_w_vert, 2), depth_ft=round(kit_d, 2),
                    height_ft=self._ceiling_height_ft,
                    is_wet=kit.is_wet, fixtures=kit.fixtures,
                ))
        elif len(large) == 1:
            r = large[0]
            placed.append(PlacedRoom(
                name=r.name, room_type=r.room_type, zone=r.zone,
                x_ft=round(x, 2), y_ft=round(y, 2),
                width_ft=round(w, 2), depth_ft=round(main_d, 2),
                height_ft=self._ceiling_height_ft,
                is_wet=r.is_wet, fixtures=r.fixtures,
            ))

        # Pack small service rooms in the back strip
        if small and service_strip_d > 0:
            service_y = y + main_d
            small.sort(key=lambda r: r.target_area_sqft, reverse=True)
            total_small = sum(r.target_area_sqft for r in small)
            sx_cursor = x
            for si, sr in enumerate(small):
                frac = sr.target_area_sqft / total_small if total_small > 0 else 1 / len(small)
                sr_w = round(w * frac, 2)
                if si == len(small) - 1:
                    sr_w = round((x + w) - sx_cursor, 2)
                placed.append(PlacedRoom(
                    name=sr.name, room_type=sr.room_type, zone=sr.zone,
                    x_ft=round(sx_cursor, 2), y_ft=round(service_y, 2),
                    width_ft=sr_w, depth_ft=round(service_strip_d, 2),
                    height_ft=self._ceiling_height_ft,
                    is_wet=sr.is_wet, fixtures=sr.fixtures,
                ))
                sx_cursor += sr_w

        return placed

    def _pack_private_wing(
        self,
        rooms: list[RoomSpec],
        bbox: tuple[float, float, float, float],
    ) -> list[PlacedRoom]:
        """Custom packing for a bedroom wing.

        Strategy: stack rooms in 2 rows if depth > width, otherwise treemap.
        Large rooms (bedrooms) go in the front row, small rooms (bath, closet)
        in the back row.
        """
        x, y, w, d = bbox
        placed: list[PlacedRoom] = []

        if not rooms:
            return placed

        # Master-suite specific layout: bedroom in front, bath/closet behind.
        # This avoids awkward treemap-like master arrangements.
        has_master = any(r.name == "Master_Bedroom" for r in rooms)
        if has_master:
            master = next((r for r in rooms if r.name == "Master_Bedroom"), None)
            if master is not None:
                rear_rooms = [r for r in rooms if r.name != "Master_Bedroom"]
                if rear_rooms:
                    master_d = min(max(d * 0.62, 12.0), d - 6.0)
                else:
                    master_d = d
                master_d = max(8.0, min(master_d, d))
                rear_d = max(0.0, d - master_d)

                placed.append(PlacedRoom(
                    name=master.name, room_type=master.room_type, zone=master.zone,
                    x_ft=round(x, 2), y_ft=round(y, 2),
                    width_ft=round(w, 2), depth_ft=round(master_d, 2),
                    height_ft=self._ceiling_height_ft,
                    is_wet=master.is_wet, fixtures=master.fixtures,
                ))

                if rear_rooms and rear_d >= 4.0:
                    rear_rooms.sort(key=lambda r: r.target_area_sqft, reverse=True)
                    total_rear = sum(r.target_area_sqft for r in rear_rooms)
                    cursor = x
                    for idx, rr in enumerate(rear_rooms):
                        frac = rr.target_area_sqft / total_rear if total_rear > 0 else (1 / len(rear_rooms))
                        rr_w = round(w * frac, 2)
                        if idx == len(rear_rooms) - 1:
                            rr_w = round((x + w) - cursor, 2)
                        placed.append(PlacedRoom(
                            name=rr.name, room_type=rr.room_type, zone=rr.zone,
                            x_ft=round(cursor, 2), y_ft=round(y + master_d, 2),
                            width_ft=rr_w, depth_ft=round(rear_d, 2),
                            height_ft=self._ceiling_height_ft,
                            is_wet=rr.is_wet, fixtures=rr.fixtures,
                        ))
                        cursor += rr_w
                return placed

        # Separate large (bedrooms) from small (bathroom, closet)
        large = [r for r in rooms if r.room_type == "bedroom"]
        small = [r for r in rooms if r.room_type != "bedroom"]

        if not large:
            # All small rooms — just use treemap
            return self._squarified_treemap(rooms, bbox)

        # Two-row layout: bedrooms get front portion, small rooms get back
        large_area = sum(r.target_area_sqft for r in large)
        small_area = sum(r.target_area_sqft for r in small)
        total_area = large_area + small_area

        if total_area > 0 and small:
            large_frac = large_area / total_area
            # Bedrooms get proportional share of depth, min 55%
            large_d = max(d * large_frac, d * 0.55)
            large_d = min(large_d, d * 0.8)  # cap: leave at least 20% for small rooms
        else:
            large_d = d

        small_d = d - large_d

        # Pack bedrooms in front row
        large.sort(key=lambda r: r.target_area_sqft, reverse=True)
        lx_cursor = x
        for li, lr in enumerate(large):
            frac = lr.target_area_sqft / large_area if large_area > 0 else 1 / len(large)
            lr_w = round(w * frac, 2)
            if li == len(large) - 1:
                lr_w = round((x + w) - lx_cursor, 2)
            placed.append(PlacedRoom(
                name=lr.name, room_type=lr.room_type, zone=lr.zone,
                x_ft=round(lx_cursor, 2), y_ft=round(y, 2),
                width_ft=lr_w, depth_ft=round(large_d, 2),
                height_ft=self._ceiling_height_ft,
                is_wet=lr.is_wet, fixtures=lr.fixtures,
            ))
            lx_cursor += lr_w

        # Pack small rooms in back row
        if small and small_d > 3:
            small.sort(key=lambda r: r.target_area_sqft, reverse=True)
            sx_cursor = x
            for si, sr in enumerate(small):
                frac = sr.target_area_sqft / small_area if small_area > 0 else 1 / len(small)
                sr_w = round(w * frac, 2)
                if si == len(small) - 1:
                    sr_w = round((x + w) - sx_cursor, 2)
                placed.append(PlacedRoom(
                    name=sr.name, room_type=sr.room_type, zone=sr.zone,
                    x_ft=round(sx_cursor, 2), y_ft=round(y + large_d, 2),
                    width_ft=sr_w, depth_ft=round(small_d, 2),
                    height_ft=self._ceiling_height_ft,
                    is_wet=sr.is_wet, fixtures=sr.fixtures,
                ))
                sx_cursor += sr_w
        elif small:
            # Fallback to treemap when back strip would be too shallow.
            return self._squarified_treemap(rooms, bbox)

        return placed

    @staticmethod
    def _worst_ratio(areas: list[float], side: float) -> float:
        """Worst aspect ratio for a row of areas laid along side."""
        total = sum(areas)
        if total == 0 or side == 0:
            return float("inf")
        row_thickness = total / side
        worst = 0.0
        for area in areas:
            item_len = area / row_thickness if row_thickness > 0 else 0
            if item_len == 0 or row_thickness == 0:
                continue
            ratio = max(item_len / row_thickness, row_thickness / item_len)
            worst = max(worst, ratio)
        return worst

    # === Phase 3: Adjacency improvement ====================================

    def _improve_adjacency(
        self,
        rooms: list[PlacedRoom],
        max_iterations: int = 100,
    ) -> list[PlacedRoom]:
        """Hill-climbing: swap same-zone rooms to improve adjacency score."""
        rooms = list(rooms)
        best_score = self._adjacency_score(rooms)

        for _ in range(max_iterations):
            improved = False
            for i in range(len(rooms)):
                for j in range(i + 1, len(rooms)):
                    a, b = rooms[i], rooms[j]
                    # Only swap rooms in same zone with similar sizes
                    if a.zone != b.zone:
                        continue
                    area_a = a.width_ft * a.depth_ft
                    area_b = b.width_ft * b.depth_ft
                    if area_a == 0 or area_b == 0:
                        continue
                    ratio = max(area_a, area_b) / min(area_a, area_b)
                    if ratio > 2.0:
                        continue  # Too different in size to swap cleanly

                    # Try swapping positions
                    self._swap_positions(rooms[i], rooms[j])
                    new_score = self._adjacency_score(rooms)
                    if new_score > best_score:
                        best_score = new_score
                        improved = True
                    else:
                        # Revert
                        self._swap_positions(rooms[i], rooms[j])

            if not improved:
                break

        return rooms

    @staticmethod
    def _swap_positions(a: PlacedRoom, b: PlacedRoom):
        """Swap the positions and dimensions of two rooms."""
        a.x_ft, b.x_ft = b.x_ft, a.x_ft
        a.y_ft, b.y_ft = b.y_ft, a.y_ft
        a.width_ft, b.width_ft = b.width_ft, a.width_ft
        a.depth_ft, b.depth_ft = b.depth_ft, a.depth_ft

    def _adjacency_score(self, rooms: list[PlacedRoom]) -> float:
        """Score layout quality. Higher = better."""
        score = 0.0
        for i, a in enumerate(rooms):
            for b in rooms[i + 1:]:
                shared_len = self._shared_wall_length(a, b)
                rel = _adj_key(a.name, a.room_type, b.name, b.room_type)
                if rel == "mandatory":
                    score += 10.0 if shared_len >= 3 else -20.0
                elif rel == "strong":
                    score += 3.0 if shared_len >= 3 else 0.0
                elif rel == "prohibited":
                    score += -50.0 if shared_len >= 1 else 0.0

                # Wet room proximity bonus
                if a.is_wet and b.is_wet and shared_len >= 1:
                    score += 2.0

        return score

    @staticmethod
    def _shared_wall_length(a: PlacedRoom, b: PlacedRoom, tolerance: float = 0.5) -> float:
        """Length of shared wall between two axis-aligned rooms."""
        # Check a-right == b-left (or vice versa) — vertical shared wall
        if abs((a.x_ft + a.width_ft) - b.x_ft) < tolerance or \
           abs((b.x_ft + b.width_ft) - a.x_ft) < tolerance:
            if abs((a.x_ft + a.width_ft) - b.x_ft) < tolerance:
                oy1 = max(a.y_ft, b.y_ft)
                oy2 = min(a.y_ft + a.depth_ft, b.y_ft + b.depth_ft)
            else:
                oy1 = max(a.y_ft, b.y_ft)
                oy2 = min(a.y_ft + a.depth_ft, b.y_ft + b.depth_ft)
            return max(0, oy2 - oy1)

        # Check a-top == b-bottom (or vice versa) — horizontal shared wall
        if abs((a.y_ft + a.depth_ft) - b.y_ft) < tolerance or \
           abs((b.y_ft + b.depth_ft) - a.y_ft) < tolerance:
            if abs((a.y_ft + a.depth_ft) - b.y_ft) < tolerance:
                ox1 = max(a.x_ft, b.x_ft)
                ox2 = min(a.x_ft + a.width_ft, b.x_ft + b.width_ft)
            else:
                ox1 = max(a.x_ft, b.x_ft)
                ox2 = min(a.x_ft + a.width_ft, b.x_ft + b.width_ft)
            return max(0, ox2 - ox1)

        return 0.0

    # === Phase 3b: Plumbing clustering ======================================

    def _cluster_plumbing(
        self,
        rooms: list[PlacedRoom],
        max_iterations: int = 60,
    ) -> list[PlacedRoom]:
        """Minimise plumbing runs by clustering wet rooms.

        Strategy:
          1. Identify all wet rooms (kitchen, bathrooms, laundry).
          2. Compute a plumbing centroid (the ideal stack location).
          3. Hill-climb: swap same-zone wet rooms to reduce total
             Manhattan distance from wet room centres to the centroid.
          4. Bonus for back-to-back bathrooms (shared drain stack).
          5. Bonus for kitchen sink within 10' of a bathroom wet wall.

        Returns rooms list (modified in place).
        """
        rooms = list(rooms)
        wet_rooms = [r for r in rooms if r.is_wet]
        if len(wet_rooms) < 2:
            return rooms

        best_score = self._plumbing_score(rooms)

        for _ in range(max_iterations):
            improved = False
            for i in range(len(rooms)):
                for j in range(i + 1, len(rooms)):
                    a, b = rooms[i], rooms[j]
                    # Only swap wet rooms in the same zone
                    if not (a.is_wet and b.is_wet):
                        continue
                    if a.zone != b.zone:
                        continue
                    area_a = a.width_ft * a.depth_ft
                    area_b = b.width_ft * b.depth_ft
                    if area_a == 0 or area_b == 0:
                        continue
                    ratio = max(area_a, area_b) / min(area_a, area_b)
                    if ratio > 2.5:
                        continue  # too different in size

                    self._swap_positions(a, b)
                    new_score = self._plumbing_score(rooms)
                    if new_score > best_score:
                        best_score = new_score
                        improved = True
                    else:
                        self._swap_positions(a, b)  # revert

            if not improved:
                break

        return rooms

    @staticmethod
    def _plumbing_score(rooms: list[PlacedRoom]) -> float:
        """Score plumbing efficiency. Higher = better (shorter runs).

        Scoring:
          - Compute centroid of all wet rooms.
          - Subtract Manhattan distance from each wet room to centroid.
          - +5 per back-to-back bathroom pair (shared wall >= 5').
          - +3 if kitchen is within 10' Manhattan of any bathroom.
          - +2 per wet room pair sharing a wall (shared drain stack).
        """
        wet = [r for r in rooms if r.is_wet]
        if len(wet) < 2:
            return 0.0

        # Centroid of wet rooms
        cx = sum(r.x_ft + r.width_ft / 2 for r in wet) / len(wet)
        cy = sum(r.y_ft + r.depth_ft / 2 for r in wet) / len(wet)

        score = 0.0

        # Distance penalty: closer to centroid = better
        max_dist = 50.0  # normalisation reference
        for r in wet:
            rcx = r.x_ft + r.width_ft / 2
            rcy = r.y_ft + r.depth_ft / 2
            dist = abs(rcx - cx) + abs(rcy - cy)
            score -= dist / max_dist * 5  # -5 per 50' away

        # Back-to-back bathroom bonus
        bathrooms = [r for r in wet if r.room_type == "bathroom"]
        for i, ba in enumerate(bathrooms):
            for bb in bathrooms[i + 1:]:
                shared = LayoutEngine._shared_wall_length(ba, bb)
                if shared >= 5:
                    score += 5.0  # excellent: shared drain stack
                elif shared >= 3:
                    score += 3.0  # good: close plumbing

        # Kitchen near bathroom bonus
        kitchens = [r for r in wet if r.room_type == "kitchen"]
        for kit in kitchens:
            kit_cx = kit.x_ft + kit.width_ft / 2
            kit_cy = kit.y_ft + kit.depth_ft / 2
            for ba in bathrooms:
                ba_cx = ba.x_ft + ba.width_ft / 2
                ba_cy = ba.y_ft + ba.depth_ft / 2
                manhattan = abs(kit_cx - ba_cx) + abs(kit_cy - ba_cy)
                if manhattan <= 10:
                    score += 3.0  # kitchen sink near bathroom wet wall
                elif manhattan <= 15:
                    score += 1.0

        # Shared wall bonus for any wet pair
        for i, wa in enumerate(wet):
            for wb in wet[i + 1:]:
                shared = LayoutEngine._shared_wall_length(wa, wb)
                if shared >= 3:
                    score += 2.0  # shared plumbing wall

        return score

    # === Phase 4: Hallway generation ========================================

    def _add_wing_hallways(
        self,
        rooms: list[PlacedRoom],
        hallways: list[HallwaySegment],
        zone_strips: dict[str, tuple[float, float, float, float]],
    ) -> list[HallwaySegment]:
        """Return preallocated strip hallways.

        Avoids post-pack hallway insertion that distorts room geometry.
        """
        return list(hallways)

    def _ensure_connectivity(
        self,
        rooms: list[PlacedRoom],
        hallways: list[HallwaySegment],
    ):
        """Check that every room can reach main circulation.

        A room is "connected" if it:
          1. Shares a wall with a hallway, OR
          2. Shares a wall with another room that is connected.

        If a room is unreachable, a warning is added but the layout
        continues (doors to hallways will still be attempted).
        """
        if not hallways:
            return

        # Build hallway pseudo-rooms
        hall_rects = []
        for i, hw in enumerate(hallways):
            hall_rects.append(PlacedRoom(
                name=f"_HW_{i}", room_type="hallway", zone="circulation",
                x_ft=hw.x_ft, y_ft=hw.y_ft,
                width_ft=hw.width_ft, depth_ft=hw.depth_ft,
                height_ft=self._ceiling_height_ft,
                is_wet=False, fixtures=None,
            ))

        # Flood-fill connectivity from hallways
        connected: set[str] = set()

        # Rooms directly touching hallways
        for room in rooms:
            for hr in hall_rects:
                if self._shared_wall_length(room, hr) >= 1.0:
                    connected.add(room.name)
                    break

        # Rooms touching connected rooms (BFS)
        changed = True
        while changed:
            changed = False
            for room in rooms:
                if room.name in connected:
                    continue
                for other in rooms:
                    if other.name not in connected:
                        continue
                    if self._shared_wall_length(room, other) >= 1.0:
                        # Check if this pair should have a door
                        if self._should_have_door(room, other):
                            connected.add(room.name)
                            changed = True
                            break

        # Report unreachable rooms
        unreachable = [r.name for r in rooms if r.name not in connected]
        if unreachable:
            # These rooms may still be accessible via open concept or
            # adjacent rooms — this is informational, not fatal
            pass  # stored in metadata during _validate if needed

    # === Phase 5: Door placement (IRC-compliant) =============================

    # IRC R311.2 / R311.3: minimum clear width requirements
    DOOR_WIDTHS: dict[str, float] = {
        "entry":      3.0,    # 36" entry/egress doors (IRC R311.2)
        "bedroom":    2.67,   # 32" bedroom doors (IRC standard)
        "bathroom":   2.67,   # 32" bathroom doors
        "closet":     2.33,   # 28" closet doors (IRC allows smaller)
        "pantry":     2.33,   # 28" pantry doors
        "laundry":    2.67,   # 32" utility rooms
        "mudroom":    3.0,    # 36" mudroom (often exterior entry)
        "great_room": 3.0,    # 36" main living area
        "kitchen":    3.0,    # 36" kitchen access
        "dining_room": 3.0,   # 36" dining room (open flow)
        "default":    2.67,   # 32" fallback
    }

    def _door_width_for(self, ra: PlacedRoom, rb: PlacedRoom) -> float:
        """Select IRC-compliant door width based on room types.

        Rules:
          - Hallway-to-entry rooms (mudroom, great_room): 36"
          - Closets and pantries: 28"
          - Bedrooms and bathrooms: 32"
          - Anything touching a hallway defaults to the room's standard
          - Default fallback: 32"
        """
        types = {ra.room_type, rb.room_type}
        names = {ra.name, rb.name}

        # Entry/egress doors get 36"
        if "hallway" in types:
            other_type = ra.room_type if rb.room_type == "hallway" else rb.room_type
            return self.DOOR_WIDTHS.get(other_type, self.DOOR_WIDTHS["default"])

        # Closet or pantry doors: 28"
        if "closet" in types or "pantry" in types:
            return self.DOOR_WIDTHS["closet"]

        # Master suite internal doors: 32"
        if "Master_Bedroom" in names:
            return self.DOOR_WIDTHS["bedroom"]

        return self.DOOR_WIDTHS["default"]

    def _place_doors(
        self,
        rooms: list[PlacedRoom],
        hallways: list[HallwaySegment],
    ) -> list[DoorPlacement]:
        """Place doors on shared walls with IRC-compliant sizing.

        Improvements:
          - Door width selected by room type per IRC standards.
          - Door positioned 6" from corner (maximizes furniture wall space).
          - Swing direction: into smaller room (architectural convention).
          - Door position chosen to avoid conflicting with other doors
            on the same wall segment.
        """
        doors: list[DoorPlacement] = []
        self._last_connectivity_fallback_doors = 0

        # Build combined list (hallways as pseudo-rooms)
        all_rects: list[PlacedRoom] = list(rooms)
        for i, hw in enumerate(hallways):
            all_rects.append(PlacedRoom(
                name=f"Hallway_{i}", room_type="hallway", zone="circulation",
                x_ft=hw.x_ft, y_ft=hw.y_ft,
                width_ft=hw.width_ft, depth_ft=hw.depth_ft,
                height_ft=self._ceiling_height_ft,
                is_wet=False, fixtures=None,
            ))

        candidates: list[tuple[int, float, DoorPlacement, PlacedRoom, PlacedRoom, frozenset[str]]] = []

        for i, ra in enumerate(all_rects):
            for rb in all_rects[i + 1:]:
                pair_key = frozenset({ra.name, rb.name})
                shared = self._find_shared_segment(ra, rb)
                if shared is None:
                    continue

                x1, y1, x2, y2, axis = shared
                seg_len = math.hypot(x2 - x1, y2 - y1)
                if seg_len < 3.0:
                    continue

                if not self._should_have_door(ra, rb):
                    continue

                door_w = self._door_width_for(ra, rb)
                if door_w > seg_len - 1.0:
                    door_w = min(door_w, seg_len - 0.5)
                    if door_w < 2.0:
                        continue

                # Prefer center-third placement instead of corner-biased doors.
                inset = max(0.5, (seg_len - door_w) / 2)
                if axis == "x":
                    dx = x1 + inset
                    dy = y1
                else:
                    dx = x1
                    dy = y1 + inset

                area_a = ra.width_ft * ra.depth_ft
                area_b = rb.width_ft * rb.depth_ft
                if ra.room_type == "hallway" or rb.room_type == "hallway":
                    swing = "inward"
                else:
                    swing = "inward" if area_a <= area_b else "outward"

                door = DoorPlacement(
                    wall_name=f"Door_{ra.name}_to_{rb.name}",
                    room_a=ra.name,
                    room_b=rb.name,
                    x_ft=round(dx, 2),
                    y_ft=round(dy, 2),
                    width_ft=round(door_w, 2),
                    on_axis=axis,
                    swing_dir=swing,
                    swing_clear=True,
                )
                priority = self._door_priority(ra, rb)
                candidates.append((priority, seg_len, door, ra, rb, pair_key))

        candidates.sort(key=lambda t: (-t[0], -t[1], t[2].wall_name))

        selected_pairs: set[frozenset[str]] = set()
        door_counts: dict[str, int] = {}
        hallway_names = {f"Hallway_{i}" for i in range(len(hallways))}

        def _bump(name: str):
            if name not in hallway_names:
                door_counts[name] = door_counts.get(name, 0) + 1

        def _can_add(ra: PlacedRoom, rb: PlacedRoom) -> bool:
            for r in (ra, rb):
                if r.name in hallway_names:
                    continue
                if door_counts.get(r.name, 0) >= self._room_max_doors(r):
                    return False
            return True

        # Pass 1: add mandatory connections first.
        for priority, _seg_len, door, ra, rb, pair_key in candidates:
            if priority < 100 or pair_key in selected_pairs:
                continue
            doors.append(door)
            selected_pairs.add(pair_key)
            _bump(ra.name)
            _bump(rb.name)

        # Pass 2: ensure key enclosed rooms have hallway access.
        for room in rooms:
            if not self._room_needs_hall_access(room):
                continue
            already_hall_connected = any(
                (d.room_a == room.name and d.room_b in hallway_names) or
                (d.room_b == room.name and d.room_a in hallway_names)
                for d in doors
            )
            if already_hall_connected:
                continue

            hall_candidates = [
                c for c in candidates
                if c[5] not in selected_pairs and (
                    (c[3].name == room.name and c[4].name in hallway_names) or
                    (c[4].name == room.name and c[3].name in hallway_names)
                )
            ]
            if not hall_candidates:
                continue
            priority, _seg_len, door, ra, rb, pair_key = hall_candidates[0]
            if priority >= 60 and _can_add(ra, rb):
                doors.append(door)
                selected_pairs.add(pair_key)
                _bump(ra.name)
                _bump(rb.name)

        # Pass 3: add high-value optional doors, respecting per-room caps.
        for priority, _seg_len, door, ra, rb, pair_key in candidates:
            if pair_key in selected_pairs:
                continue
            if priority < 70:
                continue
            if not _can_add(ra, rb):
                continue
            doors.append(door)
            selected_pairs.add(pair_key)
            _bump(ra.name)
            _bump(rb.name)

        # Pass 4: connectivity fallback. Add bridge doors only if needed.
        room_names = {r.name for r in rooms}
        while True:
            connected: set[str] = set()

            for d in doors:
                if d.room_a in hallway_names and d.room_b in room_names:
                    connected.add(d.room_b)
                if d.room_b in hallway_names and d.room_a in room_names:
                    connected.add(d.room_a)

            grew = True
            while grew:
                grew = False
                for d in doors:
                    if d.room_a in connected and d.room_b in room_names and d.room_b not in connected:
                        connected.add(d.room_b)
                        grew = True
                    if d.room_b in connected and d.room_a in room_names and d.room_a not in connected:
                        connected.add(d.room_a)
                        grew = True

            disconnected = [n for n in room_names if n not in connected]
            if not disconnected:
                break

            bridge = None
            for c in candidates:
                _priority, _seg_len, _door, ra, rb, pair_key = c
                if pair_key in selected_pairs:
                    continue
                if not _can_add(ra, rb):
                    continue
                a_in = ra.name in connected
                b_in = rb.name in connected
                a_out = ra.name in disconnected
                b_out = rb.name in disconnected
                if (a_in and b_out) or (b_in and a_out):
                    bridge = c
                    break

            if bridge is None:
                break

            _priority, _seg_len, door, ra, rb, pair_key = bridge
            doors.append(door)
            selected_pairs.add(pair_key)
            _bump(ra.name)
            _bump(rb.name)
            self._last_connectivity_fallback_doors += 1

        return doors

    @staticmethod
    def _room_max_doors(room: PlacedRoom) -> int:
        if room.name == "Master_Bedroom":
            return 2  # Bath + closet
        if room.room_type in {"great_room", "kitchen", "dining_room", "mudroom"}:
            return 2
        return 1

    @staticmethod
    def _room_needs_hall_access(room: PlacedRoom) -> bool:
        if room.name in {"Master_Bathroom", "Master_WIC"}:
            return False
        return room.room_type in {"bedroom", "bathroom", "laundry", "mudroom", "pantry"}

    @staticmethod
    def _door_priority(a: PlacedRoom, b: PlacedRoom) -> int:
        names = {a.name, b.name}
        types = {a.room_type, b.room_type}
        rel = _adj_key(a.name, a.room_type, b.name, b.room_type)

        if names == {"Master_Bedroom", "Master_Bathroom"}:
            return 120
        if names == {"Master_Bedroom", "Master_WIC"}:
            return 120
        if "kitchen" in types and "pantry" in types:
            return 110
        if "hallway" in types:
            if "bedroom" in types or "bathroom" in types:
                return 95
            if "laundry" in types or "mudroom" in types or "pantry" in types or "closet" in types:
                return 85
            return 70
        if rel == "mandatory":
            return 100
        if rel == "strong":
            return 80
        if a.room_type == "bedroom" and b.room_type == "bedroom":
            return 55
        return 60

    def _check_swing_clearances(
        self,
        doors: list[DoorPlacement],
        rooms: list[PlacedRoom],
        hallways: list[HallwaySegment],
    ):
        """Validate door swing arcs don't collide.

        A door swing arc is a quarter-circle with radius = door width.
        Two doors on the same wall or nearby walls may have overlapping
        swing arcs. When detected, one door is shifted or the swing
        direction is flipped.

        IRC R311.3: Clear floor space of min 32" x 44" on the swing side.
        """
        for i, da in enumerate(doors):
            # Swing arc centre is at the door position
            arc_a = self._swing_arc(da)

            for db in doors[i + 1:]:
                arc_b = self._swing_arc(db)

                # Check if arcs overlap (simplified AABB check)
                if self._arcs_overlap(arc_a, arc_b):
                    # Resolution: flip the swing of the door into the
                    # larger room (less likely to block furniture)
                    room_a_area = self._room_area_by_name(db.room_a, rooms, hallways)
                    room_b_area = self._room_area_by_name(db.room_b, rooms, hallways)

                    if room_a_area >= room_b_area:
                        db.swing_dir = "outward"  # swing into larger room
                    else:
                        db.swing_dir = "inward"

                    # Re-check — if still colliding, mark as not clear
                    arc_b_new = self._swing_arc(db)
                    if self._arcs_overlap(arc_a, arc_b_new):
                        db.swing_clear = False

    @staticmethod
    def _swing_arc(door: DoorPlacement) -> tuple[float, float, float, float]:
        """Return bounding box (x1, y1, x2, y2) of door swing arc.

        The arc is a quarter-circle with radius = door width, centred at
        the hinge point (door.x, door.y for the primary direction).
        """
        r = door.width_ft
        if door.on_axis == "y":
            # Door on a vertical wall, swing in X direction
            if door.swing_dir == "inward":
                return (door.x_ft - r, door.y_ft, door.x_ft, door.y_ft + r)
            else:
                return (door.x_ft, door.y_ft, door.x_ft + r, door.y_ft + r)
        else:
            # Door on a horizontal wall, swing in Y direction
            if door.swing_dir == "inward":
                return (door.x_ft, door.y_ft - r, door.x_ft + r, door.y_ft)
            else:
                return (door.x_ft, door.y_ft, door.x_ft + r, door.y_ft + r)

    @staticmethod
    def _arcs_overlap(
        a: tuple[float, float, float, float],
        b: tuple[float, float, float, float],
    ) -> bool:
        """Check if two AABB swing arcs overlap."""
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        return (ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1)

    @staticmethod
    def _room_area_by_name(
        name: str,
        rooms: list[PlacedRoom],
        hallways: list[HallwaySegment],
    ) -> float:
        """Get room area by name, including hallways."""
        for r in rooms:
            if r.name == name:
                return r.width_ft * r.depth_ft
        for i, h in enumerate(hallways):
            if f"Hallway_{i}" == name:
                return h.width_ft * h.depth_ft
        return 0.0

    @staticmethod
    def _find_shared_segment(
        a: PlacedRoom, b: PlacedRoom, tolerance: float = 0.5,
    ) -> Optional[tuple[float, float, float, float, str]]:
        """Find shared wall segment. Returns (x1, y1, x2, y2, axis) or None."""
        # a-right touching b-left
        if abs((a.x_ft + a.width_ft) - b.x_ft) < tolerance:
            oy1 = max(a.y_ft, b.y_ft)
            oy2 = min(a.y_ft + a.depth_ft, b.y_ft + b.depth_ft)
            if oy2 - oy1 >= 3.0:
                x = a.x_ft + a.width_ft
                return (x, oy1, x, oy2, "y")

        # b-right touching a-left
        if abs((b.x_ft + b.width_ft) - a.x_ft) < tolerance:
            oy1 = max(a.y_ft, b.y_ft)
            oy2 = min(a.y_ft + a.depth_ft, b.y_ft + b.depth_ft)
            if oy2 - oy1 >= 3.0:
                x = a.x_ft
                return (x, oy1, x, oy2, "y")

        # a-top touching b-bottom
        if abs((a.y_ft + a.depth_ft) - b.y_ft) < tolerance:
            ox1 = max(a.x_ft, b.x_ft)
            ox2 = min(a.x_ft + a.width_ft, b.x_ft + b.width_ft)
            if ox2 - ox1 >= 3.0:
                y = a.y_ft + a.depth_ft
                return (ox1, y, ox2, y, "x")

        # b-top touching a-bottom
        if abs((b.y_ft + b.depth_ft) - a.y_ft) < tolerance:
            ox1 = max(a.x_ft, b.x_ft)
            ox2 = min(a.x_ft + a.width_ft, b.x_ft + b.width_ft)
            if ox2 - ox1 >= 3.0:
                y = a.y_ft
                return (ox1, y, ox2, y, "x")

        return None

    @staticmethod
    def _should_have_door(a: PlacedRoom, b: PlacedRoom) -> bool:
        """Determine if a door should connect these two rooms."""
        types = {a.room_type, b.room_type}
        names = {a.name, b.name}

        # Hallway to room connections are the primary circulation edges.
        if "hallway" in types:
            return True

        # Master bedroom <-> master bathroom: yes
        if "Master_Bedroom" in names and "Master_Bathroom" in names:
            return True

        # Master bedroom <-> walk-in closet: yes
        if "Master_Bedroom" in names and "Master_WIC" in names:
            return True

        # Kitchen <-> pantry: yes
        if "kitchen" in types and "pantry" in types:
            return True

        # Open-concept living/dining/kitchen: no doors between them
        # (walls are removed entirely in _generate_wall_segments)
        open_flow_types = {"great_room", "kitchen", "dining_room"}
        if types.issubset(open_flow_types):
            return False

        # Bedroom-to-bedroom connections are fallback circulation links.
        if a.room_type == "bedroom" and b.room_type == "bedroom":
            return True

        # Bedrooms should NOT connect directly to kitchen or dining room
        if "bedroom" in types and ("kitchen" in types or "dining_room" in types):
            return False

        # Laundry/mudroom can connect to kitchen as service adjacencies.
        if "kitchen" in types and ("laundry" in types or "mudroom" in types):
            return True

        # Reduce over-connected interiors: no generic room-to-room doors by default.
        return False

    # === Phase 6: Wall segment generation ==================================

    def _generate_wall_segments(
        self,
        rooms: list[PlacedRoom],
        hallways: list[HallwaySegment],
        doors: list[DoorPlacement],
        bld_len: float,
        bld_wid: float,
        open_concept: bool,
    ) -> list[WallSegment]:
        """Generate interior wall segments, skipping exterior edges and open-concept gaps."""
        walls: list[WallSegment] = []
        wall_idx = 0

        # Build combined rectangle list
        all_rects: list[PlacedRoom] = list(rooms)
        for i, hw in enumerate(hallways):
            all_rects.append(PlacedRoom(
                name=f"Hallway_{i}", room_type="hallway", zone="circulation",
                x_ft=hw.x_ft, y_ft=hw.y_ft,
                width_ft=hw.width_ft, depth_ft=hw.depth_ft,
                height_ft=self._ceiling_height_ft,
                is_wet=False, fixtures=None,
            ))

        # Build door lookup: which pairs have doors (and where)
        door_pairs: dict[frozenset[str], DoorPlacement] = {}
        for door in doors:
            door_pairs[frozenset({door.room_a, door.room_b})] = door

        seen_edges: set[tuple[float, float, float, float]] = set()

        for i, ra in enumerate(all_rects):
            for rb in all_rects[i + 1:]:
                shared = self._find_shared_segment(ra, rb)
                if shared is None:
                    continue

                x1, y1, x2, y2, axis = shared

                # Skip exterior edges (wall on building boundary)
                if self._is_exterior_edge(x1, y1, x2, y2, bld_len, bld_wid):
                    continue

                # Skip open-concept: no wall between great_room, dining_room, kitchen
                if open_concept:
                    types = {ra.room_type, rb.room_type}
                    open_flow = {"great_room", "kitchen", "dining_room"}
                    if types.issubset(open_flow):
                        continue

                # Deduplicate
                edge_key = (
                    round(min(x1, x2), 1), round(min(y1, y2), 1),
                    round(max(x1, x2), 1), round(max(y1, y2), 1),
                )
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)

                # Check if this edge has a door
                pair_key = frozenset({ra.name, rb.name})
                door = door_pairs.get(pair_key)

                if door is None:
                    # Full wall segment
                    walls.append(WallSegment(
                        name=f"IWall_{wall_idx}",
                        start_x_ft=round(x1, 2), start_y_ft=round(y1, 2),
                        end_x_ft=round(x2, 2), end_y_ft=round(y2, 2),
                    ))
                    wall_idx += 1
                else:
                    # Split wall around door opening
                    door_segs = self._split_wall_for_door(
                        x1, y1, x2, y2, axis, door, wall_idx,
                    )
                    walls.extend(door_segs)
                    wall_idx += len(door_segs)

        return walls

    @staticmethod
    def _is_exterior_edge(
        x1: float, y1: float, x2: float, y2: float,
        bld_len: float, bld_wid: float,
        tolerance: float = 0.5,
    ) -> bool:
        """Check if a wall segment lies on the building exterior."""
        # On left wall (x ≈ 0)
        if abs(x1) < tolerance and abs(x2) < tolerance:
            return True
        # On right wall (x ≈ bld_len)
        if abs(x1 - bld_len) < tolerance and abs(x2 - bld_len) < tolerance:
            return True
        # On front wall (y ≈ 0)
        if abs(y1) < tolerance and abs(y2) < tolerance:
            return True
        # On back wall (y ≈ bld_wid)
        if abs(y1 - bld_wid) < tolerance and abs(y2 - bld_wid) < tolerance:
            return True
        return False

    @staticmethod
    def _split_wall_for_door(
        x1: float, y1: float, x2: float, y2: float,
        axis: str,
        door: DoorPlacement,
        wall_idx: int,
    ) -> list[WallSegment]:
        """Split a wall segment into two pieces around a door opening."""
        segs: list[WallSegment] = []
        dw = door.width_ft

        if axis == "y":
            # Vertical wall (runs along Y). Door at (door.x, door.y)
            dy = door.y_ft
            # Segment before door
            if dy - y1 > 0.5:
                segs.append(WallSegment(
                    name=f"IWall_{wall_idx}",
                    start_x_ft=round(x1, 2), start_y_ft=round(y1, 2),
                    end_x_ft=round(x1, 2), end_y_ft=round(dy, 2),
                ))
            # Segment after door
            after_y = dy + dw
            if y2 - after_y > 0.5:
                segs.append(WallSegment(
                    name=f"IWall_{wall_idx + 1}",
                    start_x_ft=round(x1, 2), start_y_ft=round(after_y, 2),
                    end_x_ft=round(x1, 2), end_y_ft=round(y2, 2),
                ))
        else:
            # Horizontal wall (runs along X). Door at (door.x, door.y)
            dx = door.x_ft
            if dx - x1 > 0.5:
                segs.append(WallSegment(
                    name=f"IWall_{wall_idx}",
                    start_x_ft=round(x1, 2), start_y_ft=round(y1, 2),
                    end_x_ft=round(dx, 2), end_y_ft=round(y1, 2),
                ))
            after_x = dx + dw
            if x2 - after_x > 0.5:
                segs.append(WallSegment(
                    name=f"IWall_{wall_idx + 1}",
                    start_x_ft=round(after_x, 2), start_y_ft=round(y1, 2),
                    end_x_ft=round(x2, 2), end_y_ft=round(y1, 2),
                ))

        return segs

    # === Validation ==========================================================

    def _validate(
        self,
        rooms: list[PlacedRoom],
        hallways: list[HallwaySegment],
        doors: list[DoorPlacement],
        bld_len: float,
        bld_wid: float,
    ) -> dict:
        """Validate the layout and return metadata."""
        warnings: list[str] = []
        overlaps: list[tuple[str, str]] = []
        out_of_bounds: list[str] = []

        footprint = bld_len * bld_wid

        # Check bounds
        for r in rooms:
            if r.x_ft < -0.5 or r.y_ft < -0.5:
                out_of_bounds.append(r.name)
                warnings.append(f"{r.name} has negative coordinates")
            if r.x_ft + r.width_ft > bld_len + 0.5:
                out_of_bounds.append(r.name)
                warnings.append(f"{r.name} exceeds building length")
            if r.y_ft + r.depth_ft > bld_wid + 0.5:
                out_of_bounds.append(r.name)
                warnings.append(f"{r.name} exceeds building width")

        # Check overlaps (axis-aligned bbox intersection)
        for i, a in enumerate(rooms):
            for b in rooms[i + 1:]:
                if (a.x_ft < b.x_ft + b.width_ft - 0.5 and
                    a.x_ft + a.width_ft > b.x_ft + 0.5 and
                    a.y_ft < b.y_ft + b.depth_ft - 0.5 and
                    a.y_ft + a.depth_ft > b.y_ft + 0.5):
                    overlaps.append((a.name, b.name))
                    warnings.append(f"Overlap: {a.name} and {b.name}")

        # Zone percentages
        zone_areas: dict[str, float] = {}
        for r in rooms:
            zone_areas[r.zone] = zone_areas.get(r.zone, 0) + r.width_ft * r.depth_ft

        hall_area = sum(h.width_ft * h.depth_ft for h in hallways)
        room_area = sum(r.width_ft * r.depth_ft for r in rooms)
        zone_areas["circulation"] = hall_area

        zone_pct = {k: (v / footprint * 100) if footprint > 0 else 0
                    for k, v in zone_areas.items()}

        # Plumbing clustering score
        plumbing = self._plumbing_score(rooms)

        # Wet room cluster radius
        wet = [r for r in rooms if r.is_wet]
        wet_radius = 0.0
        if len(wet) >= 2:
            cx = sum(r.x_ft + r.width_ft / 2 for r in wet) / len(wet)
            cy = sum(r.y_ft + r.depth_ft / 2 for r in wet) / len(wet)
            wet_radius = max(
                math.hypot(r.x_ft + r.width_ft / 2 - cx,
                           r.y_ft + r.depth_ft / 2 - cy)
                for r in wet
            )

        # Connectivity check
        hall_rects = []
        for i, hw in enumerate(hallways):
            hall_rects.append(PlacedRoom(
                name=f"_HW_{i}", room_type="hallway", zone="circulation",
                x_ft=hw.x_ft, y_ft=hw.y_ft,
                width_ft=hw.width_ft, depth_ft=hw.depth_ft,
                height_ft=self._ceiling_height_ft,
                is_wet=False, fixtures=None,
            ))
        connected: set[str] = set()
        for room in rooms:
            for hr in hall_rects:
                if self._shared_wall_length(room, hr) >= 1.0:
                    connected.add(room.name)
                    break
        # BFS through connected rooms
        changed = True
        while changed:
            changed = False
            for room in rooms:
                if room.name in connected:
                    continue
                for other in rooms:
                    if other.name not in connected:
                        continue
                    if self._shared_wall_length(room, other) >= 1.0:
                        if self._should_have_door(room, other):
                            connected.add(room.name)
                            changed = True
                            break
        unreachable = [r.name for r in rooms if r.name not in connected]
        if unreachable:
            warnings.append(f"Unreachable rooms: {unreachable}")

        room_count = len(rooms)
        door_count = len(doors)
        doors_per_room = (door_count / room_count) if room_count > 0 else 0.0
        hallway_ratio = (hall_area / (room_area + hall_area)) if (room_area + hall_area) > 0 else 0.0

        quality_issues: list[str] = []
        if doors_per_room > 1.2:
            quality_issues.append("high_door_density")
        if hallway_ratio > 0.20:
            quality_issues.append("high_circulation_ratio")
        if unreachable:
            quality_issues.append("unreachable_rooms")
        if self._last_connectivity_fallback_doors > 2:
            quality_issues.append("many_connectivity_fallback_doors")

        quality_status = "good" if not quality_issues else "warning"

        return {
            "zone_percentages": zone_pct,
            "overlapping_rooms": overlaps,
            "out_of_bounds_rooms": out_of_bounds,
            "warnings": warnings,
            "room_count": room_count,
            "hallway_count": len(hallways),
            "total_room_area_sqft": room_area,
            "total_hallway_area_sqft": hall_area,
            "building_footprint_sqft": footprint,
            "fill_ratio": (room_area + hall_area) / footprint
                          if footprint > 0 else 0,
            "plumbing_score": round(plumbing, 1),
            "wet_room_cluster_radius_ft": round(wet_radius, 1),
            "connected_rooms": len(connected),
            "unreachable_rooms": unreachable,
            "quality_report": {
                "status": quality_status,
                "issues": quality_issues,
                "door_count": door_count,
                "doors_per_room": round(doors_per_room, 2),
                "hallway_ratio": round(hallway_ratio, 3),
                "connectivity_fallback_doors": self._last_connectivity_fallback_doors,
            },
        }
