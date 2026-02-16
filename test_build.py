"""Direct test: Build a 30'x40' post-frame shop using the tool functions.

Includes: slab, posts, girts, trusses, purlins, wainscot, ridge cap,
overhead door, walk door.
"""

import json
from tools.freecad_tools import (
    clear_all,
    create_concrete_slab,
    create_post_layout,
    create_wall_girts,
    create_roof_trusses,
    create_purlins,
    create_wainscot,
    create_ridge_cap,
    create_overhead_door,
    create_walk_door,
    create_window,
    get_building_summary,
    save_document,
    export_step,
    FREECAD_AVAILABLE,
)

LENGTH = 40  # feet (along X)
WIDTH = 30   # feet (along Y)
EAVE = 10    # feet
PITCH = 4    # 4:12

print("=" * 60)
print("Building: 30' x 40' Post-Frame Shop")
print(f"Eave height: {EAVE}', Pitch: {PITCH}:12")
print(f"FreeCAD available: {FREECAD_AVAILABLE}")
print("=" * 60)

clear_all()

# Step 1: Concrete slab
print("\n[1] Creating 4\" concrete slab...")
slab = create_concrete_slab("Slab", length_ft=LENGTH, width_ft=WIDTH, thickness_inches=4)
print(f"    -> {slab}")

# Step 2: Post layout
print("\n[2] Creating post layout (8' OC, 6x6 posts, 4' embed)...")
posts = create_post_layout(
    building_length_ft=LENGTH,
    building_width_ft=WIDTH,
    post_spacing_ft=8,
    height_ft=EAVE,
    size_inches=6,
    embed_ft=4,
)
print(f"    -> {len(posts)} posts")

# Step 3: Wall girts
print("\n[3] Creating wall girts (2' vertical spacing)...")
girts = create_wall_girts(
    building_length_ft=LENGTH,
    building_width_ft=WIDTH,
    wall_height_ft=EAVE,
    girt_spacing_ft=2,
)
print(f"    -> {len(girts)} girts")

# Step 4: Wainscot
print("\n[4] Creating 4' wainscot on all walls...")
wainscot = create_wainscot(
    building_length_ft=LENGTH,
    building_width_ft=WIDTH,
    wainscot_height_ft=4,
    thickness_inches=0.5,
)
print(f"    -> {len(wainscot)} panels")

# Step 5: Roof trusses
print("\n[5] Creating roof trusses (2' OC, 4:12 pitch, 1' overhang)...")
trusses = create_roof_trusses(
    building_length_ft=LENGTH,
    building_width_ft=WIDTH,
    truss_spacing_ft=2,
    eave_height_ft=EAVE,
    pitch=PITCH,
    overhang_ft=1,
)
print(f"    -> {len(trusses)} trusses")

# Step 6: Purlins
print("\n[6] Creating roof purlins (2' OC along slope)...")
purlins = create_purlins(
    building_length_ft=LENGTH,
    building_width_ft=WIDTH,
    eave_height_ft=EAVE,
    pitch=PITCH,
    purlin_spacing_ft=2,
    overhang_ft=1,
)
print(f"    -> {len(purlins)} purlins")

# Step 7: Ridge cap
print("\n[7] Creating ridge cap...")
ridge = create_ridge_cap(
    building_length_ft=LENGTH,
    building_width_ft=WIDTH,
    eave_height_ft=EAVE,
    pitch=PITCH,
)
print(f"    -> {ridge}")

# Step 8: Overhead door - 10'x10' centered on front wall
# Front wall is 40' long -> center = (40-10)/2 = 15'
print("\n[8] Creating 10'x10' overhead door (front wall, centered)...")
oh_door = create_overhead_door(
    name="OH_Door_Front",
    wall="front",
    position_ft=15,
    width_ft=10,
    height_ft=10,
)
print(f"    -> {oh_door}")

# Step 9: Walk door on right side wall, 5' from front corner
print("\n[9] Creating 3'x6'8\" walk door (right wall)...")
walk_door = create_walk_door(
    name="Walk_Door_Right",
    wall="right",
    position_ft=5,
    width_ft=3,
    height_ft=6.67,
)
print(f"    -> {walk_door}")

# Summary
print("\n" + "=" * 60)
print("BUILDING SUMMARY")
print("=" * 60)
summary = get_building_summary()
print(f"Total components: {summary['total_objects']}")
for obj_type, names in summary["by_type"].items():
    print(f"  {obj_type}: {len(names)}")
print("=" * 60)

# Save
print("\nSaving...")
result = save_document("output/30x40_shop.FCStd")
print(result)

# Export STEP
print("\nExporting STEP...")
result2 = export_step("output/30x40_shop.step")
print(result2)

print("\nDone!")
