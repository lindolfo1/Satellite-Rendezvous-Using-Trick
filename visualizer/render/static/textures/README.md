# Earth texture

Put the map here as **`earth_texture.jpg`** (`.png`, `.jpeg` and `.webp` also
work — the loader tries each in turn):

```
render/static/textures/earth_texture.jpg
```

Nothing else to configure. `render/component.py` finds it, base64-encodes it,
and inlines it into the viewer document. If it is absent the globe falls back to
a plain sphere with a wireframe, so a missing map is not an error.

## What the file has to be

An **equirectangular** projection: longitude linear across the width,
latitude linear down the height, north at the top. The whole globe, -180 to
+180 and -90 to +90. That is the standard "blue marble" layout.

## Where the seam goes

`EARTH_TEXTURE_SEAM_LON_DEG` in `config.py` is the longitude at the **left
edge** of the image. It is currently **-179.814**, derived from the seam sitting
about 30 statute miles west of 51.269181 N, 179.120772 W: at that latitude
48.3 km is 0.693 degrees of longitude.

That is 0.19 degrees off the -180 antimeridian a conventional map uses — about
21 km at the equator. If the map turns out to be conventional after all, set it
to `-180.0`.

## Checking the alignment

Turn the **graticule** on in the view options panel. It draws the prime meridian
in gold and the equator in blue, positioned from the computed GMST with no
knowledge of the texture. If the map's Greenwich sits on the gold line, the seam
constant is right. If it is offset, the graticule is still correct and the
constant needs adjusting by however far it is out.

## Size

The image rides inline in every run load, and base64 adds a third. A 2 MB map
costs 2.7 MB per load. Anything much above that is worth downscaling to
2048x1024, which is more than the globe resolves at any practical zoom.
