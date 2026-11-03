# Static water material

Water floors can use the source texture as a visible bed instead of repeating a
water tile over the whole river. Add `water` to a polygon or rectangle layer:

```json
{
  "id": "river",
  "asset": "tileset/elwynn/elwynnrivermudbase.blp",
  "tile_cells": 1.8,
  "shape": {"type": "polygon", "points": [[2,0],[8,0],[8,10],[2,10]], "feather": 0},
  "water": {
    "shore_color": "#718e78",
    "shoal_color": "#4e8e85",
    "deep_color": "#244f5c",
    "depth_cells": 4.3,
    "ripple_cells": 0.48,
    "ripple_strength": 0.12,
    "bed_visibility": 0.65,
    "flow": [0,1],
    "shallow_shapes": []
  }
}
```

The shader derives visual depth from distance to the bank, ignoring polygon
edges along the scene frame so inlets and outlets do not become shallow dams.
`shallow_shapes` accepts normal scene shapes as soft hints within the original
water mask. Polygon and rectangle cutouts create island shorelines. The source
geometry, collision and scene interfaces are untouched. Color, bottom detail
and warped highlights are deterministic for the scene seed and layer ID.

`depth_cells` controls an artistic color falloff, not actual water depth.
`flow` only orients the static ripples. This does not implement Foundry water
movement, animation, physical reflections or point-light interaction. The
compositor still clips the result with the original layer mask.

The work plane is bounded to 1600 pixels on its longest side before resizing to
the requested map resolution. No dependencies beyond NumPy and Pillow are added.
