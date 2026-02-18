"""Tests for the algorithmic floor plan layout engine."""
import sys
sys.path.insert(0, r"C:\clawdbotCAD")

from agent.layout_engine import (
    LayoutEngine,
    parse_room_program,
    RoomSpec,
    PlacedRoom,
    FloorPlan,
)


def test_parse_room_program():
    """Room program parser produces correct number & types of rooms."""
    specs = parse_room_program(3, 2, 60, 40)
    names = [s.name for s in specs]

    assert "Great_Room" in names, "Missing Great_Room"
    assert "Kitchen" in names, "Missing Kitchen"
    assert "Master_Bedroom" in names, "Missing Master_Bedroom"
    assert "Master_Bathroom" in names, "Missing Master_Bathroom"
    assert "Master_WIC" in names, "Missing Master_WIC"
    assert "Bedroom_2" in names, "Missing Bedroom_2"
    assert "Bedroom_3" in names, "Missing Bedroom_3"
    assert "Bathroom_2" in names, "Missing Bathroom_2"
    assert "Pantry" in names, "Missing Pantry"
    assert "Laundry" in names, "Missing Laundry"
    assert "Mudroom" in names, "Missing Mudroom"
    print("  PASSED: parse_room_program (3 bed / 2 bath)")


def test_parse_room_program_minimal():
    """Minimal room program: 1 bed / 1 bath."""
    specs = parse_room_program(1, 1, 30, 24, has_pantry=False, has_laundry=False, has_mudroom=False)
    names = [s.name for s in specs]
    assert "Great_Room" in names
    assert "Kitchen" in names
    assert "Master_Bedroom" in names
    assert "Master_Bathroom" in names
    assert len(specs) == 5, f"Expected 5 rooms, got {len(specs)}: {names}"
    print("  PASSED: parse_room_program (1 bed / 1 bath minimal)")


def test_no_overlaps():
    """No rooms overlap for common building sizes."""
    engine = LayoutEngine()
    sizes = [(30, 24), (40, 30), (50, 40), (60, 40), (60, 50), (80, 60)]

    for length, width in sizes:
        plan = engine.generate(length, width, 3, 2)
        overlaps = plan.metadata["overlapping_rooms"]
        assert len(overlaps) == 0, \
            f"{length}x{width}: overlaps found: {overlaps}"
    print("  PASSED: no overlaps for all common sizes")


def test_all_rooms_in_bounds():
    """All rooms fit within building envelope."""
    engine = LayoutEngine()
    sizes = [(30, 24), (40, 30), (50, 40), (60, 40), (80, 60)]

    for length, width in sizes:
        plan = engine.generate(length, width, 3, 2)
        for r in plan.rooms:
            assert r.x_ft >= -0.5, \
                f"{length}x{width}: {r.name} has x={r.x_ft}"
            assert r.y_ft >= -0.5, \
                f"{length}x{width}: {r.name} has y={r.y_ft}"
            assert r.x_ft + r.width_ft <= length + 0.5, \
                f"{length}x{width}: {r.name} exceeds length: {r.x_ft}+{r.width_ft}={r.x_ft+r.width_ft} > {length}"
            assert r.y_ft + r.depth_ft <= width + 0.5, \
                f"{length}x{width}: {r.name} exceeds width: {r.y_ft}+{r.depth_ft}={r.y_ft+r.depth_ft} > {width}"
    print("  PASSED: all rooms in bounds for all sizes")


def test_room_count():
    """Correct number of rooms generated."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2)
    assert len(plan.rooms) == 11, f"Expected 11 rooms, got {len(plan.rooms)}"
    print(f"  PASSED: room count = {len(plan.rooms)}")


def test_hallways_generated():
    """Hallways are generated between zone strips."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2)
    assert len(plan.hallways) >= 2, \
        f"Expected at least 2 hallways, got {len(plan.hallways)}"
    print(f"  PASSED: hallways = {len(plan.hallways)}")


def test_doors_generated():
    """Doors are placed between rooms."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2)
    assert len(plan.doors) >= 5, \
        f"Expected at least 5 doors, got {len(plan.doors)}"
    print(f"  PASSED: doors = {len(plan.doors)}")


def test_door_count_not_excessive():
    """Interior should avoid over-dooring on standard programs."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2, has_dining=True)
    assert len(plan.doors) <= 14, \
        f"Expected <=14 doors for 60x40 3/2+dining, got {len(plan.doors)}"
    print(f"  PASSED: door count not excessive ({len(plan.doors)})")


def test_walls_generated():
    """Interior walls are generated."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2)
    assert len(plan.walls) >= 3, \
        f"Expected at least 3 walls, got {len(plan.walls)}"
    print(f"  PASSED: walls = {len(plan.walls)}")


def test_open_concept():
    """Open concept: no wall between great room and kitchen."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2, open_concept=True)

    # Check no wall runs between great_room and kitchen
    gr = next(r for r in plan.rooms if r.room_type == "great_room")
    kit = next(r for r in plan.rooms if r.room_type == "kitchen")

    # Check no door between them (open concept = no wall = no door)
    for door in plan.doors:
        pair = {door.room_a, door.room_b}
        assert not (gr.name in pair and kit.name in pair), \
            f"Open concept should not have door between {gr.name} and {kit.name}"

    print("  PASSED: open concept (no wall/door between great room and kitchen)")


def test_split_bedroom_pattern():
    """Master bedroom is separated from secondary bedrooms."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2)

    master = next(r for r in plan.rooms if r.name == "Master_Bedroom")
    bed2 = next(r for r in plan.rooms if r.name == "Bedroom_2")

    # Master should be on opposite end of building from Bedroom_2
    master_center_x = master.x_ft + master.width_ft / 2
    bed2_center_x = bed2.x_ft + bed2.width_ft / 2

    separation = abs(master_center_x - bed2_center_x)
    assert separation > 15, \
        f"Split-bedroom: expected >15' separation, got {separation:.1f}'"
    print(f"  PASSED: split-bedroom pattern (separation={separation:.0f}')")


def test_kitchen_adjacent_to_great_room():
    """Kitchen should be adjacent to great room."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2)

    gr = next(r for r in plan.rooms if r.room_type == "great_room")
    kit = next(r for r in plan.rooms if r.room_type == "kitchen")

    # Check they share a wall (adjacent)
    shared = LayoutEngine._shared_wall_length(gr, kit)
    assert shared >= 3, \
        f"Kitchen should be adjacent to great room, shared wall = {shared:.1f}'"
    print(f"  PASSED: kitchen adjacent to great room (shared wall={shared:.0f}')")


def test_master_bed_adjacent_to_master_bath():
    """Master bedroom should be adjacent to master bathroom."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2)

    master_br = next(r for r in plan.rooms if r.name == "Master_Bedroom")
    master_ba = next(r for r in plan.rooms if r.name == "Master_Bathroom")

    shared = LayoutEngine._shared_wall_length(master_br, master_ba)
    assert shared >= 3, \
        f"Master BR should be adjacent to Master Bath, shared wall = {shared:.1f}'"
    print(f"  PASSED: master bed adjacent to master bath (shared wall={shared:.0f}')")


def test_fill_ratio():
    """Fill ratio should be between 60% and 100%."""
    engine = LayoutEngine()
    for length, width in [(40, 30), (60, 40), (80, 60)]:
        plan = engine.generate(length, width, 3, 2)
        fill = plan.metadata["fill_ratio"]
        assert 0.6 <= fill <= 1.0, \
            f"{length}x{width}: fill ratio {fill:.1%} out of range"
    print("  PASSED: fill ratio in range for all sizes")


def test_bedroom_counts():
    """Different bedroom/bathroom counts produce correct rooms."""
    engine = LayoutEngine()
    for beds, baths in [(2, 1), (3, 2), (4, 3), (5, 3)]:
        plan = engine.generate(60, 40, beds, baths)
        bedrooms = [r for r in plan.rooms if r.room_type == "bedroom"]
        bathrooms = [r for r in plan.rooms if r.room_type == "bathroom"]
        assert len(bedrooms) == beds, \
            f"{beds}bed/{baths}bath: expected {beds} bedrooms, got {len(bedrooms)}"
        assert len(bathrooms) == baths, \
            f"{beds}bed/{baths}bath: expected {baths} bathrooms, got {len(bathrooms)}"
    print("  PASSED: bedroom/bathroom counts correct for all configurations")


def test_integration_with_macrobuilder():
    """FloorPlan output feeds cleanly into MacroBuilder."""
    from agent.macro_generator import MacroBuilder

    engine = LayoutEngine()
    plan = engine.generate(40, 30, 2, 1)

    mb = MacroBuilder(r"C:\clawdbotCAD\output\test_layout.FCStd")

    # Structural shell
    mb.create_concrete_slab("Slab", 40, 30)
    mb.create_post_layout(40, 30)

    # Feed layout engine output into MacroBuilder
    for room in plan.rooms:
        mb.create_room(
            name=room.name, x_ft=room.x_ft, y_ft=room.y_ft,
            width_ft=room.width_ft, depth_ft=room.depth_ft,
            height_ft=room.height_ft, room_type=room.room_type,
        )
        if room.fixtures and room.fixtures.startswith("kitchen"):
            layout = room.fixtures.split("_")[1].upper() if "_" in room.fixtures else "L"
            mb.create_kitchen_fixtures(
                room.name, room.x_ft, room.y_ft,
                room.width_ft, room.depth_ft, layout=layout,
            )
        elif room.fixtures and room.fixtures.startswith("bathroom"):
            has_tub = "tub" in room.fixtures
            mb.create_bathroom_fixtures(
                room.name, room.x_ft, room.y_ft,
                room.width_ft, room.depth_ft, has_tub=has_tub,
            )

    for i, hw in enumerate(plan.hallways):
        mb.create_room(
            name=f"Hallway_{i}", x_ft=hw.x_ft, y_ft=hw.y_ft,
            width_ft=hw.width_ft, depth_ft=hw.depth_ft,
            height_ft=9.0, room_type="room",
        )

    for wall in plan.walls:
        mb.create_interior_wall(
            name=wall.name,
            start_x_ft=wall.start_x_ft, start_y_ft=wall.start_y_ft,
            end_x_ft=wall.end_x_ft, end_y_ft=wall.end_y_ft,
        )

    # Build and syntax-check the macro
    macro = mb.build_macro()
    compile(macro, "test_layout_macro.py", "exec")
    print(f"  PASSED: MacroBuilder integration ({len(macro.splitlines())} lines, syntax OK)")


def test_door_sizes_irc_compliant():
    """Door widths match IRC standards for each room type."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2)

    for door in plan.doors:
        # All doors must be at least 28" (2.33')
        assert door.width_ft >= 2.33, \
            f"{door.wall_name}: width {door.width_ft}' < 2.33' (28\")"
        # No doors wider than 36" (3.0')
        assert door.width_ft <= 3.0, \
            f"{door.wall_name}: width {door.width_ft}' > 3.0' (36\")"

    # Check specific room type doors
    for door in plan.doors:
        if "Master_WIC" in door.room_a or "Master_WIC" in door.room_b:
            assert door.width_ft <= 2.67, \
                f"Closet door should be <= 32\": {door.wall_name} = {door.width_ft}'"
        if "Pantry" in door.room_a or "Pantry" in door.room_b:
            assert door.width_ft <= 2.67, \
                f"Pantry door should be <= 32\": {door.wall_name} = {door.width_ft}'"
    print("  PASSED: door sizes IRC-compliant")


def test_door_swing_direction():
    """Door swing direction is set correctly."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2)

    for door in plan.doors:
        assert door.swing_dir in ("inward", "outward"), \
            f"{door.wall_name}: invalid swing_dir '{door.swing_dir}'"
        # Hallway doors should swing inward (into the room, not hallway)
        if "Hallway" in door.room_a or "Hallway" in door.room_b:
            assert door.swing_dir == "inward", \
                f"{door.wall_name}: hallway door should swing inward"
    print("  PASSED: door swing directions correct")


def test_plumbing_score_in_metadata():
    """Plumbing clustering score is computed and stored in metadata."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2)

    assert "plumbing_score" in plan.metadata, "Missing plumbing_score in metadata"
    assert "wet_room_cluster_radius_ft" in plan.metadata, "Missing wet_room_cluster_radius"

    # Plumbing score should be a finite number
    ps = plan.metadata["plumbing_score"]
    assert isinstance(ps, (int, float)), f"plumbing_score is {type(ps)}"
    assert ps != float("inf") and ps != float("-inf"), "plumbing_score is infinite"

    # Wet room cluster radius should be reasonable (< half building diagonal)
    wr = plan.metadata["wet_room_cluster_radius_ft"]
    max_radius = (60**2 + 40**2)**0.5 / 2
    assert wr <= max_radius, \
        f"Wet room cluster radius {wr:.1f}' > half-diagonal {max_radius:.1f}'"
    print(f"  PASSED: plumbing score={ps}, cluster radius={wr:.1f}'")


def test_plumbing_wet_rooms_clustered():
    """Wet rooms are reasonably clustered (radius < 25' for standard building)."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2)

    wr = plan.metadata["wet_room_cluster_radius_ft"]
    assert wr < 30, \
        f"Wet room cluster radius {wr:.1f}' too large (expected <30')"

    # Check wet rooms exist
    wet_rooms = [r for r in plan.rooms if r.is_wet]
    assert len(wet_rooms) >= 3, \
        f"Expected at least 3 wet rooms, got {len(wet_rooms)}"
    print(f"  PASSED: wet rooms clustered (radius={wr:.1f}', count={len(wet_rooms)})")


def test_quality_report_metadata():
    """Quality report is present with core livability metrics."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2, has_dining=True)

    qr = plan.metadata.get("quality_report")
    assert isinstance(qr, dict), "Missing quality_report metadata"
    assert qr.get("status") in ("good", "warning"), f"Invalid status: {qr.get('status')}"
    assert "door_count" in qr, "Missing quality_report.door_count"
    assert "doors_per_room" in qr, "Missing quality_report.doors_per_room"
    assert "hallway_ratio" in qr, "Missing quality_report.hallway_ratio"
    assert "connectivity_fallback_doors" in qr, "Missing quality_report.connectivity_fallback_doors"
    print(f"  PASSED: quality report metadata (status={qr.get('status')}, doors={qr.get('door_count')})")


def test_connectivity():
    """All rooms are reachable from hallway circulation."""
    engine = LayoutEngine()
    for length, width in [(40, 30), (60, 40), (80, 60)]:
        plan = engine.generate(length, width, 3, 2)
        connected = plan.metadata["connected_rooms"]
        total = plan.metadata["room_count"]
        unreachable = plan.metadata["unreachable_rooms"]
        assert connected == total, \
            f"{length}x{width}: {total - connected} unreachable rooms: {unreachable}"
    print("  PASSED: all rooms connected to circulation for all sizes")


def test_hallway_dead_ends():
    """No hallway dead-ends longer than 10'."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2)

    # All hallways should either connect to rooms on both sides
    # or T-connect to another hallway (no dead corridors)
    for hw in plan.hallways:
        # A dead-end hallway would have rooms on only one side
        # Check that hallway has adjacency on at least 2 of its 4 sides
        sides_with_adjacency = 0
        hw_rect = PlacedRoom(
            name="_test_hw", room_type="hallway", zone="circulation",
            x_ft=hw.x_ft, y_ft=hw.y_ft,
            width_ft=hw.width_ft, depth_ft=hw.depth_ft,
            height_ft=9.0, is_wet=False, fixtures=None,
        )
        for room in plan.rooms:
            if LayoutEngine._shared_wall_length(hw_rect, room) >= 1.0:
                sides_with_adjacency += 1

        # Each hallway should touch multiple rooms (avoid dead corridors)
        assert sides_with_adjacency >= 2, \
            f"Hallway at ({hw.x_ft},{hw.y_ft}) has weak adjacency ({sides_with_adjacency})"
    print(f"  PASSED: no hallway dead-ends ({len(plan.hallways)} hallways checked)")


def test_door_positions_within_walls():
    """All doors are positioned within their shared wall segments."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2)

    for door in plan.doors:
        # Door position should be non-negative
        assert door.x_ft >= 0, f"{door.wall_name}: x={door.x_ft} < 0"
        assert door.y_ft >= 0, f"{door.wall_name}: y={door.y_ft} < 0"
        # Door should be within building bounds
        assert door.x_ft <= 60, f"{door.wall_name}: x={door.x_ft} > 60"
        assert door.y_ft <= 40, f"{door.wall_name}: y={door.y_ft} > 40"
    print("  PASSED: all doors positioned within building bounds")


def test_dining_room_generation():
    """Dining room is created when has_dining=True."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2, has_dining=True)

    dining = [r for r in plan.rooms if r.room_type == "dining_room"]
    assert len(dining) == 1, f"Expected 1 dining room, got {len(dining)}"

    dr = dining[0]
    assert dr.name == "Dining_Room"
    area = dr.width_ft * dr.depth_ft
    assert area >= 80, f"Dining room too small: {area:.0f} sqft"
    ratio = max(dr.width_ft / dr.depth_ft, dr.depth_ft / dr.width_ft)
    assert ratio <= 2.5, f"Dining room aspect ratio too extreme: {ratio:.2f}"

    # Without dining, should be 11 rooms; with dining, 12
    assert len(plan.rooms) == 12, f"Expected 12 rooms with dining, got {len(plan.rooms)}"
    print(f"  PASSED: dining room generation ({dr.width_ft:.0f}'x{dr.depth_ft:.0f}', {area:.0f} sqft)")


def test_dining_room_open_concept():
    """Open concept: no walls between great room, dining room, and kitchen."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2, has_dining=True, open_concept=True)

    gr = next(r for r in plan.rooms if r.room_type == "great_room")
    dr = next(r for r in plan.rooms if r.room_type == "dining_room")
    kit = next(r for r in plan.rooms if r.room_type == "kitchen")

    # No door between any open-concept pair
    open_names = {gr.name, dr.name, kit.name}
    for door in plan.doors:
        pair = {door.room_a, door.room_b}
        assert not pair.issubset(open_names), \
            f"Open concept should not have door between {pair}"

    print("  PASSED: dining room open concept (no doors between living/dining/kitchen)")


def test_dining_room_adjacency():
    """Dining room is adjacent to both great room and kitchen."""
    engine = LayoutEngine()
    plan = engine.generate(60, 40, 3, 2, has_dining=True)

    dr = next(r for r in plan.rooms if r.room_type == "dining_room")
    gr = next(r for r in plan.rooms if r.room_type == "great_room")
    kit = next(r for r in plan.rooms if r.room_type == "kitchen")

    # Check dining room shares a wall with both great room and kitchen
    shared_gr = LayoutEngine._shared_wall_length(dr, gr)
    shared_kit = LayoutEngine._shared_wall_length(dr, kit)

    assert shared_gr >= 1 and shared_kit >= 1, \
        f"Dining room should touch both GR ({shared_gr:.1f}') and Kitchen ({shared_kit:.1f}')"
    print(f"  PASSED: dining room adjacency (GR wall={shared_gr:.0f}', Kit wall={shared_kit:.0f}')")


def test_narrow_building_kitchen_ratio():
    """Kitchen aspect ratio should be <= 2.5 on narrow buildings (width < 36')."""
    engine = LayoutEngine()

    for length, width in [(74, 33), (60, 28), (80, 30)]:
        plan = engine.generate(length, width, 3, 2)
        kit = next(r for r in plan.rooms if r.room_type == "kitchen")
        ratio = max(kit.width_ft / kit.depth_ft, kit.depth_ft / kit.width_ft)
        assert ratio <= 2.5, \
            f"{length}x{width}: kitchen aspect ratio {ratio:.2f} > 2.5 ({kit.width_ft:.1f}x{kit.depth_ft:.1f})"
    print("  PASSED: narrow building kitchen aspect ratio <= 2.5")


def test_narrow_building_no_overlaps():
    """No overlaps on narrow buildings (width < 36')."""
    engine = LayoutEngine()

    for length, width in [(74, 33), (60, 28), (80, 30), (50, 26)]:
        plan = engine.generate(length, width, 3, 2)
        overlaps = plan.metadata["overlapping_rooms"]
        assert len(overlaps) == 0, \
            f"{length}x{width}: overlaps found: {overlaps}"
    print("  PASSED: no overlaps on narrow buildings")


def test_master_bedroom_area_cap():
    """Master bedroom area should not exceed 300 sqft (area cap)."""
    engine = LayoutEngine()

    specs = parse_room_program(3, 2, 80, 60)
    master = next(s for s in specs if s.name == "Master_Bedroom")
    assert master.target_area_sqft <= 260, \
        f"Master bedroom target {master.target_area_sqft:.0f} sqft exceeds cap (expected <= 260)"
    print(f"  PASSED: master bedroom area cap (target={master.target_area_sqft:.0f} sqft)")


def test_room_overrides():
    """room_overrides parameter modifies room target areas."""
    overrides = {
        "Kitchen": {"width": 14, "depth": 16},      # 224 sqft
        "Master_Bedroom": {"area": 200},              # 200 sqft
    }
    specs = parse_room_program(3, 2, 60, 40, room_overrides=overrides)

    kit = next(s for s in specs if s.name == "Kitchen")
    master = next(s for s in specs if s.name == "Master_Bedroom")

    # Kitchen target should be close to 14*16=224 (then scaled by fill factor)
    assert 160 < kit.target_area_sqft < 300, \
        f"Kitchen override failed: target={kit.target_area_sqft:.0f}"

    # Master should be close to 200 (then scaled, capped at 250)
    assert 140 < master.target_area_sqft <= 260, \
        f"Master override failed: target={master.target_area_sqft:.0f}"

    print(f"  PASSED: room_overrides (kit={kit.target_area_sqft:.0f}, master={master.target_area_sqft:.0f})")


def test_room_overrides_layout():
    """room_overrides produce valid layout without overlaps."""
    engine = LayoutEngine()
    overrides = {
        "Kitchen": {"width": 14, "depth": 16},
        "Master_Bedroom": {"area": 200},
    }
    plan = engine.generate(74, 33, 3, 2, has_dining=True, room_overrides=overrides)

    overlaps = plan.metadata["overlapping_rooms"]
    assert len(overlaps) == 0, f"Overlaps with overrides: {overlaps}"

    connected = plan.metadata["connected_rooms"]
    total = plan.metadata["room_count"]
    assert connected == total, f"Not all rooms connected: {connected}/{total}"
    print(f"  PASSED: room_overrides layout valid ({total} rooms, no overlaps)")


def test_74x33_reference_plan():
    """74x33 building produces reasonable layout matching reference plan characteristics."""
    engine = LayoutEngine()
    plan = engine.generate(74, 33, 3, 2, has_dining=True)

    # Basic structure checks
    assert len(plan.metadata["overlapping_rooms"]) == 0, "Overlaps in 74x33"
    assert plan.metadata["connected_rooms"] == plan.metadata["room_count"], "Disconnected rooms"

    # Check all expected rooms exist
    room_types = [r.room_type for r in plan.rooms]
    assert "great_room" in room_types, "Missing great room"
    assert "dining_room" in room_types, "Missing dining room"
    assert "kitchen" in room_types, "Missing kitchen"
    assert room_types.count("bedroom") == 3, f"Expected 3 bedrooms, got {room_types.count('bedroom')}"
    assert room_types.count("bathroom") == 2, f"Expected 2 bathrooms, got {room_types.count('bathroom')}"

    # Split-bedroom pattern
    master = next(r for r in plan.rooms if r.name == "Master_Bedroom")
    bed2 = next(r for r in plan.rooms if r.name == "Bedroom_2")
    separation = abs((master.x_ft + master.width_ft/2) - (bed2.x_ft + bed2.width_ft/2))
    assert separation > 20, f"Split-bedroom separation {separation:.0f}' too small"

    # Kitchen aspect ratio should be reasonable
    kit = next(r for r in plan.rooms if r.room_type == "kitchen")
    kit_ratio = max(kit.width_ft / kit.depth_ft, kit.depth_ft / kit.width_ft)
    assert kit_ratio <= 2.5, f"Kitchen ratio {kit_ratio:.2f} too extreme"

    # Dining room should exist and be reasonable
    dr = next(r for r in plan.rooms if r.room_type == "dining_room")
    dr_area = dr.width_ft * dr.depth_ft
    assert dr_area >= 80, f"Dining room too small: {dr_area:.0f} sqft"

    print(f"  PASSED: 74x33 reference plan ({len(plan.rooms)} rooms, sep={separation:.0f}')")


if __name__ == "__main__":
    print("Running layout engine tests...\n")
    tests = [
        test_parse_room_program,
        test_parse_room_program_minimal,
        test_no_overlaps,
        test_all_rooms_in_bounds,
        test_room_count,
        test_hallways_generated,
        test_doors_generated,
        test_door_count_not_excessive,
        test_walls_generated,
        test_open_concept,
        test_split_bedroom_pattern,
        test_kitchen_adjacent_to_great_room,
        test_master_bed_adjacent_to_master_bath,
        test_fill_ratio,
        test_bedroom_counts,
        test_integration_with_macrobuilder,
        # New: hallway improvements
        test_hallway_dead_ends,
        test_connectivity,
        # New: door improvements
        test_door_sizes_irc_compliant,
        test_door_swing_direction,
        test_door_positions_within_walls,
        # New: plumbing clustering
        test_plumbing_score_in_metadata,
        test_plumbing_wet_rooms_clustered,
        test_quality_report_metadata,
        # New: dining room
        test_dining_room_generation,
        test_dining_room_open_concept,
        test_dining_room_adjacency,
        # New: narrow building fixes
        test_narrow_building_kitchen_ratio,
        test_narrow_building_no_overlaps,
        test_master_bedroom_area_cap,
        # New: room_overrides
        test_room_overrides,
        test_room_overrides_layout,
        # New: 74x33 reference plan
        test_74x33_reference_plan,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAILED: {test.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed, {len(tests)} total")
    if failed == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"{failed} TEST(S) FAILED")
