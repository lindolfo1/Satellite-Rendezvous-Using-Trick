# Rendezvous viewer

Offline analysis for Trick rendezvous runs. Python loads the run and derives
everything once; the browser owns the render loop, the clock and the HUD, so
playback is not paced by server round-trips.

## Running it

```
pip install -r requirements.txt
streamlit run app.py
```

Drop each run into `runs/` as a `<stem>.csv` + `<stem>.json` pair and pick it
from the sidebar.

## Publishing it

Put the runs you want public in `published/` — `runs/` is your untracked working
folder, and the split is the decision point, since a published page carries the
whole trajectory and GitHub Pages serves to anyone with the URL even from a
private repository.

```
cp my_run.csv my_run.json published/
git add published/ && git commit -m "publish my_run" && git push
```

Then, once: **Settings → Pages → Source → GitHub Actions**. The workflow builds
one self-contained page per run plus an index and deploys them; every later push
republishes. The site appears at
`https://<user>.github.io/<repo>/`.

To check what it will look like before pushing:

```
python3 tools/export_static.py --runs published --out site
open site/index.html
```

Roughly 1.6 MB per 1800-sample run, against GitHub's 100 MB per-file cap and
about a gigabyte per repository — bandwidth is the practical limit, not size.

## Diagnosing a nav frame mismatch

```
python3 tools/diagnose_relnav.py runs/my_run
```

Run this if the viewer reports that `relNav.xHat` does not match the target's
LVLH; it scores the plausible readings against the run's own geometry.

---

# Rendezvous post-processing viewer

Offline analysis tool for Trick rendezvous runs. Trick writes a `<name>.csv` and
a matching `<name>.json` into `runs/`; this tool lists the available runs, loads
one, and lets you scrub, play back, and inspect the rendezvous. Nothing is
real-time, nothing is streamed, there is no socket.

See `rendezvous_viewer_v2_prompt.md` (build spec v2.2) for *what* and
`rendezvous_viewer_build_plan.md` for *in what order*.

## Status

**Stage 6 complete — `Run` is now complete.** Layout shell, render architecture,
run discovery, the CSV loader, the geometry layer, events and errors, and Earth
orientation. Everything from here is presentation. Selecting a run loads it,
draws both orbits, anchors each of the six views per spec §9, and fills the
timeline strip with burn spans and waypoint arrivals.

`Run` carries the body frames, relative state, burn segments, waypoint
arrivals, one unified event list, the measured-vs-true error series, GMST, and
both ground tracks.

The globe is textured and turns at the **sidereal** rate — 360.9856 degrees per
solar day, driven by GMST per sample, so scrubbing and playback show the same
orientation for the same instant. See `render/static/textures/README.md` for
where to put the map.

Drop a matching `<name>.csv` + `<name>.json` pair into `runs/` and it appears in
the sidebar with no code change. The sidebar starts **open** until a run is
selected, then collapses per spec §1 — it is a load-time choice, not a per-frame
control.

The viewport is a **browser-side three.js component that owns its own render
loop** — three.js via CDN import map, no npm and no build step. Streamlit keeps
the sidebar and the load-time chrome. This replaces the spec's Plotly render
layer; spec §6's framework choice is the one part of v2.2 that did not survive
Stage 0, and `spikes/FINDINGS.md` records why in full.

The short version: driving any chart library at one frame per Streamlit rerun
jitters, because each frame round-trips through an interpreter, a socket and a
diff and lands late by a different amount. Moving the clock into the browser
removes the round trip entirely — and, as a side effect, makes the camera
constraints of acceptance criterion 7 exact rather than best-effort.

## Setup

```
pip install -r requirements.txt
streamlit run app.py
```

## Before Stage 1

All spikes are run and recorded in `spikes/FINDINGS.md`. The superseded ones
are deleted; `spike_c_*` remains, because it is the prototype for
`render/static/` rather than a throwaway:

```
streamlit run spikes/spike_c_threejs.py
```

## Where the state lives

Python owns **one** thing: which run is selected. Everything else — playback,
camera, view choice, toggles, panel visibility — is browser state in
`render/static/js/00_state.js`.

That is not a style preference. Changing the injected HTML remounts the iframe
and resets the scene, so any control wired to a Streamlit widget would reset the
camera and the clock every time it was touched.

## Two rules for the render layer

**Scene units are kilometres past the packing boundary.** float32 (what WebGL
stores vertices as) resolves 0.49 mm at a 6800 km orbit radius, against 0.5 m
for the same geometry in metres. `data/` and `core/` stay float64 SI per spec;
`render/payload.py` is the only place that conversion happens.

**The scene uses ECI axes directly.** three.js is +Y-up and ECI is +Z-up, but
the obvious permutation `(x, z, y)` is a *mirror*, not a rotation, and quietly
flips the handedness of every orientation. The scene keeps ECI axes and sets
`camera.up` instead.

**The satellites are drawn at true 1 m scale, with a pixel-based fallback.**
Scene units are kilometres, so the mesh is authored in metres and scaled once
(`render/static/js/05_cubesat.js`). When the bus would cover less than one
pixel — which is every frame of the orbit-plane view, where it works out around
4e-5 px — a marker stands in at a fixed 8 px, capped at 10. Below a pixel the
real geometry is not small, it is *invisible*, so the marker is a symbol rather
than a depiction and must not shrink with distance.

**Earth constants live in `core/earth.py` and nowhere else.** The radius is the
WGS84 equatorial 6378137 m, not the 6371 km mean radius spec §9a mentions: the
sim's target sits at 6878137 m, exactly that plus a round 500 km, so the sim is
built on WGS84 and matching it keeps occlusion and ground tracks consistent with
the data.

**Position reads as a place, not a state vector.** Spec §8 asks for ECI xyz
plus a magnitude; the stats panel shows sub-satellite latitude, longitude and
height above the WGS84 ellipsoid instead. The magnitude was only ever the orbit
radius, and the xyz needs a frame held in your head — the sub-satellite point is
the same information, readable straight off the globe behind it. The separate
"sub-sat lat/lon" row is gone with it, since it said the same thing twice.

**The corridor may be written either way round.** Spec §2 asks for
`waypoint_range` outermost to innermost. A file listing it innermost first is
accepted and **not reordered** — `currentWaypoint` indexes the array as written,
so reversing it here would point every waypoint lookup at the wrong entry.
Instead the direction is detected: closing in walks *up* the array in one
ordering and *down* it in the other, so the offset search covers −1 as well as
0 and +1. Both orderings then give the same distance-to-go.

The sidebar always displays the corridor as an approach, outermost first,
noting when the file lists it the other way. A corridor that is not monotonic,
or repeats a standoff, is rejected: an approach goes one way, and a jumbled list
is a broken file rather than another convention.

**The waypoint convention is detected, not assumed.** Spec §3.5 reads
`wp_current` as the waypoint being *approached* and computes
`true_range - waypoint_range[wp_current]`. The real output uses it for the last
waypoint *reached*: the run opens at 1000 m with `wp_current = 0` against a
corridor whose first entry is 1000 m. Under the spec's reading the distance-to-go
shows 0 while holding and counts down to −750 during the transfer — backwards,
and zero exactly when there is furthest to go.

`data/events.detect_waypoint_convention` picks whichever reading keeps the
distance non-negative, since you approach a waypoint from outside it. On the
observed data it is decisive: 100% against 39.5%.

**Coasting reports exactly zero thrust.** The same `THRUST_EPS` that sets the
THRUSTING indicator floors the acceleration readout, so the label and the number
cannot disagree — "coasting · 3.55e-15 m/s²" only invites you to wonder which is
lying. The generator was also leaving that residue behind by computing
`-R·rate² + µ/R²`, two separately-rounded quantities; written as
`R·(ω² − rate²)` it cancels exactly.

**The drawn orbit is propagated, not remembered.** `orbitWindow` sets how much
orbit appears either side of now, in revolutions — 0.7 by default, so 1.4 in
total.

Windowing the *recorded* track was the obvious implementation and it fails where
it matters most: at the first sample there is nothing behind the vehicle,
because nothing has been recorded yet, and at the last there is nothing ahead.
Asking for "0.7 orbits either side" and getting an arc that stops dead at the
vehicle is the wrong answer to the right question.

So `js/08_kepler.js` takes classical elements from the current state and samples
positions across the window: 513 points, odd so that one lands exactly on the
vehicle rather than the centre falling between two. Two bodies, no J2 — over 0.7
of a revolution that is a few kilometres on a line drawn at 6878 km, and the
recorded track is still drawn over it, so anything the propagation misses shows
as the gap between them rather than being hidden.

The recorded track keeps its own window, because it is history and history has
ends.

The relative-motion track is deliberately not windowed: it is not an orbit, and
its whole shape is the point of the view it appears in.

**Orbit tracks are drawn against a moving reference.** float32 resolves 0.49 m
at a 6878 km orbit radius, which made the drawn tracks shimmer. Two changes fix
it, and both are needed:

1. The chaser position is packed across **two float32s** (the double-single
   trick) and added back in JS, where numbers are float64 — reconstructing it to
   picometres, against 0.24 m for the high half alone. The target is that plus
   the exact relative vector.
2. Path vertices are stored **relative to a reference point** near whatever the
   view is anchored on, with the group translated to it. The subtraction is done
   in float64, so nothing inherits a grid, and the residual float32 error scales
   with distance from the reference — 0.12 mm at 1 km out, 1 m at the far side
   of the orbit, i.e. it grows exactly where it stops being visible.

The reference is rewritten when the anchor drifts past `max(25 km, scene
height)`, so a zoomed-out view does not pay for rebuilds it could not benefit
from. Measured across a pass with 17 rebuilds: **0.94 mm** worst error under the
camera, against the 490 mm it used to be.

`runGroup` therefore holds **only the path lines**. Anything positioned in
absolute world coordinates — the vehicles, the burn arrows, the corridor — must
live outside it, or it inherits the reference offset and is drawn at twice the
orbit radius.

**The orbit-plane view is orthographic.** A 500 km orbit is only 7.8% above the
surface, and under perspective the sphere's silhouette is *nearer* than the
orbit ring, so the limb is foreshortened less and the gap collapses — 3% of the
disc at 3.2 orbit radii, and inside 2.68 radii the ring projects *within* the
limb, where the solid globe occludes a track that is genuinely above it. Zooming
in made the orbit disappear into the Earth.

Orthographic has no foreshortening: the ring sits a constant 7.8% outside the
disc at every zoom, and nothing occludes it. Spec §9a asked for a 2D projection
onto the orbit plane — this is that, and this is why. The local and sat-to-sat
views stay perspective, where the distances involved make it the right choice.

**The pair is placed relatively, never absolutely.** Both absolute positions are
float32 kilometres, quantised to 0.49 m and quantised *independently*, so their
difference wanders about 0.12 m from one sample to the next. At orbital scale
that is nothing; at the 1 m separation a rendezvous ends on it is the entire
signal, and it looks like the two vehicles shivering against each other.

So `render/payload.py` packs the relative vector itself — taken in float64,
small enough that float32 resolves it to 3e-8 m — and the renderer places the
target at *the chaser plus that vector*. The camera reads the same helper, since
a camera anchored on the packed absolute position would sit half a metre off the
vehicle it is supposed to be riding. Measured frame-to-frame wander: 120 mm
before, 0.0001 mm after.

The same reasoning covers `true_range`, which is packed rather than differenced
in the stats panel.

**Events carry a sample index, never a time.** Sample times reach the browser as
float32 while event times are computed in float64, so they never compare equal
and time-keyed seeking sticks on the event it just arrived at.

## If the viewer shows "Viewer failed to start"

The scene runs inside a `srcdoc` iframe, where a module that throws fails
silently — nothing binds, nothing renders, and the empty state stays up because
the code that hides it never ran. A watchdog in `viewer.html` catches that and
prints the reason on the page instead. Whatever it says is the actual error;
the browser console has the stack.

three.js is vendored in `render/static/vendor/` and imported from a blob URL, so
there is no network request at runtime. If the blob import is refused, it falls
back to the CDN automatically.

## Relative navigation (`chaser.sat.relNav.xHat`)

An optional filter state — position (3), velocity (3), and optionally attitude
error (3) and gyro bias (3). Runs without the column load unchanged and the
feature switches off.

**The array width is flexible.** Elements 0–5 are required; anything beyond is
taken if logged and ignored if not, so a run carrying only position and velocity
loads. A fixed twelve-wide array turned a sim that stopped logging its filter
internals into a hard load failure. Fewer than six is still an error — position
and velocity are what this reads. Without the attitude tail the ghost carries
the chaser's true attitude, which is what a zero error would give anyway.

`xHat[0:3]` is the **target relative to the chaser, in the target's LVLH**, on
the project's axis convention — x radial, y along-track, z orbit normal. So
where the chaser believes *itself* to be is

```
target − (R·x̂ + V·ŷ + H·ẑ)
```

The sense was read off real output: `xHat` opens at V = +1000.4 m on a run where
the chaser trails by 1000 m. Taking it the other way put the ghost 2000 m out on
the far side of the target.

What remains is a **consistency check**, and it judges the frame by *comparing
hypotheses* rather than against a tolerance: the assumed sense is scored against
its opposite on the same samples. A wrong sense predicts a position on the far
side of the target and is beaten by its own reverse at every range; a right one
is beaten by nothing.

That matters because the obvious test — error divided by separation — fails on
exactly the runs this tool exists for. Near contact a correct filter carrying
1.9 m of error against a 1.5 m gap reads as 127%, so the overlay switched itself
off just as the rendezvous got interesting. The same components are predicted
from the run's own geometry and compared. On a healthy run the residual is simply the
navigation error. If it exceeds half the run's separation, the frame has changed
rather than the navigation degraded — the panel says so and nothing is drawn,
because a ghost placed with the wrong frame reads as a navigation failure. Tests
confirm it trips on a reversed sense, a permuted axis order, and a units change,
and stays quiet on a genuinely noisy filter.

Drawn three ways, on one toggle:

- a **dashed skeleton** of the chaser where it believes it is (solid means
  measured, dashed means believed — the same distinction the transported LVLH
  frame uses);
- an **error arrow** from truth to belief, because when the error is small the
  two outlines overlap and the ghost alone is unreadable;
- the **estimated track** beside the true one in the relative-motion view,
  which is where navigation error actually reads — you watch the belief wander
  off the truth and converge back.

The numeric error is in the stats panel whether or not the overlay is on.
`render/payload.py` packs the *error* rather than the estimated position: a
metre-scale number float32 resolves to microns, where an absolute estimate
would land back on the 0.49 m grid.

## Playback

The clock keeps a **continuous sim time** rather than reading it back from the
current sample. Advancing from `time[S.idx]` discards the remainder every frame:
at 60 fps against a 1 s sample spacing, 1× gains 0.017 s, snaps to the sample it
started on, and throws the gain away — so playback sat still at 1×, 5× and 25×
and only moved at 100×, where a single frame finally exceeded a single sample.

Between samples the vehicles are placed by **cubic Hermite interpolation**,
using the logged velocities as the end tangents. That is not a smoothing spline
fitted to the points — it is the trajectory the state vectors describe, so over
one interval it reproduces the orbit to the micron.

Straight-line interpolation came first and was wrong in a way that showed: a
chord cuts the corner by **1053 mm** at 1 Hz, peaking exactly mid-interval and
vanishing at each sample. That is a sawtooth with a period of one data point,
which is what made the orbit appear to jump against a vehicle following the real
trajectory.

The drawn paths are subdivided along the same curve, **8 sub-samples per
interval**, leaving 1053 / 8² = 16 mm. Measured, the vehicle now rides its own
drawn path to 0.0001 m where chords were 1.053 m out. The cost is eight times
the vertices: 0.16 MB per line on a 1800-sample run.

**Quaternions are interpolated too**, which I first skipped as invisible. It is
invisible on a 1 m satellite — but the *camera* is built from those axes, and
the plane view aims down the orbit normal with radial as up, so leaving them on
sample boundaries snapped the whole frame 0.063° once a second while the scene
slid smoothly. Normalised lerp, taking the shorter arc; over 0.063° it agrees
with slerp to about 1e-9 rad. Largest camera step went from 0.063° in one jolt
to 0.0063° spread evenly.

**The bright track ends at the present position, not the last sample.** It used
to stop at sample `i` while the vehicle was drawn between `i` and `i + 1`, so at
1 Hz the tip trailed by up to 7.5 km and snapped forward once a second — which
reads as the line juddering against the satellite. Measured 7516 m before, 1 mm
after. The tip is written into the *next* sample's slot (not yet drawn) and
restored from the source before the clock reaches it; appending a spare vertex
does not work, because `setDrawRange` is a contiguous span and would draw the
next sample instead.

**Everything geometric is interpolated; measurements are not.** Where something
is and which way it points gets read between samples — positions, quaternions,
the target's velocity (which orients the corridor), the Earth's rotation angle.
Rangefinder readings, thrust commands and validity flags stay on their samples:
smoothing a measurement would misrepresent it, and a commanded thrust that steps
on and off is meant to step. The waypoint balls were the last thing reading raw,
and jumped 1.3 px per sample against a satellite moving smoothly.

That, and the camera jump above, were both the same sample-versus-interpolated
split rather than floating point. The float32 vertex path contributes about
0.03 px of shader error at a 50 m scene, which is not what you were seeing.

Stepping, scrubbing and event seeking pin the clock exactly to a sample rather
than leaving it mid-interval.

Mouse pan is **drag-to-grab**: the scene follows the cursor, so dragging right
carries what you are holding to the right. Both axes were inverted, which made
the scene run away from the drag.

## Cinematic mode

A 2×2 grid for screen capture: three panes, each with its own view picker, and a
stats card in the fourth quadrant. The ordinary panels hide with it — the
engineering HUD is unreadable at video size.

The panes are rendered by drawing the scene three times per frame into scissor
rectangles, setting `S.view` and rebuilding the geometry before each pass, since
what is drawn depends on the view.

**Each pane has its own camera.** `CAM` stays the single live camera the rest of
the code reads and writes; `paneCams` holds the saved states. The pane you press
in becomes the one you are driving and stays so until you press in another —
following the cursor instead would hand a drag to a neighbour the moment it
crossed the divider. Rendering does the same swap per pass, saving the live
camera once *before* the loop: saving inside it writes each pane's state into
the next pane's slot.

The card is its own module (`js/45_cinepanel.js`, numbered before `50_main.js`
because main builds it at load), designed around one reader: someone who has
never seen the tool, on a phone, sound off, deciding in a second whether to keep
watching. Five decisions follow from that and nothing else on the card is
decided any other way.

**One axis.** Everything the viewer reads is left-aligned on the same line. An
earlier version put three figures in a right-aligned column beside the hero,
which gave the eye two axes to track and left a dead area between them. The only
right-aligned element is the eased-rate note, which belongs to the transport
rather than to the data.

**One rhythm.** `--step` is the single vertical unit and every gap is 1, 2 or 3
of it. Nothing is spaced by eye.

**Four sizes** — label, eyebrow, figure, hero — all in use, each carrying a
distinct rank. A fifth would have to earn its place.

**No rules.** Grouping is done with space. The two hairlines this had ran under
the header and above the footer, where the spacing had already grouped things;
a line that repeats what the layout says is decoration.

**Three colours with fixed jobs**: ink for values, dim for labels, green for
progress and state. Amber appears only on burns, because a burn is the one event
that is neither.

Closing rate sits *under* the range rather than beside it, because it modifies
the range: one fact on two lines, not a fourth number competing for the eye.
Elapsed switches to `h:mm:ss` once there are hours — mm:ss with an unbounded
minutes field reads "378:27" six hours into a run. The chosen rate is shown once,
by the pressed button; only the *difference* under easing is worth words, so the
note reads "eased to 12×" and is empty when there is none.

A settings menu behind one control holds everything that is a *choice*, so the
recorded frame carries data rather than switches: the three navigation overlays
(position, attitude, estimate track), and the pacing controls. An exit button
sits beside it. Both fade to 45% until hovered — this frame is going to be
recorded.

**The clock eases near waypoints.** A rendezvous is mostly waiting punctuated by
arrivals, so at the one rate that makes transits watchable, every arrival is
over in a few frames. Within `easeRange` of a waypoint the rate falls towards
`easeFloor` of the chosen one.

Measured to the nearest waypoint the chaser has **not yet entered**. Once it has
arrived there is nothing left to watch there — station keeping is a vehicle
holding still — so the target returns to full speed. Measuring to the nearest
waypoint of any kind left the terminal hold eased for the rest of the run:
parked a few metres from the innermost waypoint's centre, that gap stays small
forever.

Entry is a step, so the applied factor **chases** the target rather than
snapping to it, on an asymmetric envelope: quick to brake, gentle to recover. A
single time constant cannot serve both ends — at 100× the whole ease band is
crossed in a fraction of a wall second, and a gentle one left the rate at 65×
with the chaser 6 m from the waypoint, while a quick one would snap back to full
the instant it arrived, which is the step this exists to remove.

Measured over a full run at 100×: braking to 14.5× on the run in, recovering to
100× once station keeping begins, and never changing by more than 5.3× in a
single frame. The card shows both rates
("12×, eased from 100×"), because a clip that silently changes speed cannot be
read. Off by default and switched on when cinematic mode is entered: someone
scrubbing their own run should get the rate they asked for.

A **timeline** carries the burns as bars at their true duration and the waypoint
arrivals as ticks with a diamond head, each labelled. They are drawn as
different kinds of mark on purpose: a burn has duration, an arrival is an
instant, and making both coloured bars had arrivals reading as very short burns.
Burn bars have a floor width, or a 12 s burn on a 1800 s run would be a
sub-pixel sliver — the very thing the timeline exists to show.

**Restart** sits beside play, because a take that goes wrong needs another take
and dropping out to the engineering transport loses the pane framing along with
the moment. It keeps playing if it was playing, and stays paused if it was
paused — which is why it calls `startPlayback` rather than `togglePlay`.

**Burns are marked on the relative track too.** The plane view marks each
ignition on the orbit; the relative views need the same information in the frame
they are drawn in, because "a burn happened here" is only useful beside the
track it changed. Position and direction are both resolved into the target's
LVLH at the ignition sample, length follows delta-V on the same policy the plane
view uses, and burns later than the current time stay hidden. It answers to a different reader than the
engineering HUD — someone watching a twenty-second video with the sound off —
so it carries one hero number, a phase name so no caption is needed, a corridor
rail whose segments show the shape of the approach, and a transport, because a
capture is useless if you cannot start it. Closing rate is a magnitude with a
direction glyph rather than a signed number: a minus sign in front of "closing"
is a puzzle, an arrow is not.

Anything sized against the viewport (arrow lengths, the level-of-detail switch)
measures the pane rather than the window, or a quadrant would be drawn as if it
had the whole screen.

## HUD notes

Orbit tracks are **brightened, not thickened**: WebGL ignores `linewidth`, so
every `THREE.Line` is one pixel wide whatever the material says. Real thickness
would mean vendoring three's `Line2`, which rebuilds each segment as
screen-space quads — a much larger change than these tracks warrant.

The bottom-left corner is a flex stack, frame counter above the panel, so
neither needs to know the other's height. Both bottom panels sit on the bottom
edge, level with the time controls.

Spec §10 asks for independently show/hide-able panels. The toggle bar that
provided it has been **removed** — it sat across the top centre, inside the
render area, offering to hide panels that are small and useful.

## Views

| View | What it shows | Camera |
|---|---|---|
| Plane · chaser / target | Earth-centred, down the orbit normal, orthographic | zoom + pan |
| Local · chaser / target | Over the shoulder, 50 m back, tilted so the other vehicle is in frame | zoom + rotate |
| Relative · on target | The chaser's track in the target's rotating frame | zoom + rotate + pan |
| Relative · on chaser | The same track, framed on the chaser | zoom + rotate + pan |

The local views used to look nadir from a fixed radial standoff, which put the
other vehicle off-screen for most of an approach. They now sit 50 m *behind* the
anchored vehicle on the line to the other one, lifted off that line so the near
one does not hide the far one — both are in frame whenever the Earth is not
between them, which is what the LOS flag reports.

The relative-motion view centres on the target and draws the chaser's position
in the target's LVLH, which is the shape a rangefinder plot has. It opens at 45°
in both azimuth and elevation, so R, V and H are all foreshortened rather than
one of them pointing straight at the camera; `R` (recentre) returns to that
orientation rather than to zero. It keeps the target's orbit for orientation and drops the chaser's — a second
absolute line says nothing in a frame that is entirely about relative motion. The track's vertices are the packed
relative position resolved in the target's frame, so they are metre-scale and
exact, unlike the orbit tracks on their 0.49 m grid.

`rel_lvlh` is the **chaser relative to the target**, the opposite sense from
`rel_pos_eci` (which is target minus chaser, what the rangefinder bearing
needs). A chaser trailing by a kilometre reads V = −1000 m, on the negative
V-bar, which is the convention.

The sat-to-sat views are gone.

## Orbit-plane view

Burn arrows are rooted at each ignition point along that segment's mean thrust
direction, with length proportional to Δv and the largest burn in the run drawn
at 8% of the Earth's radius. Burns later than the current time are hidden — a
plot that shows a manoeuvre before it happens gives away the answer. The panel
states the scale explicitly.

## Waypoints

A waypoint is a **place**, not a range. It sits at its standoff behind the
target along the target's velocity vector, and the ball drawn around it is the
position tolerance:

```
centre  = target − standoff · v̂
radius  = |tolerance × standoff|
```

The drawn sphere is **10% wider than the tolerance**, so a vehicle sitting
exactly on the limit is inside a visible shell rather than embedded in the
wireframe. Display only: entry is still decided against the true tolerance in
`data/waypoints.py`, because inflating that instead would quietly redefine what
green means and leave the spheres and the panel answering different questions.

`tolerance` comes from the sidecar as a fraction of each standoff, so the ball
around a 750 m waypoint is larger than the one around 20 m. Sidecars without the
field still load; the ball is then drawn at `DEFAULT_TOLERANCE_ASSUMED` and the
sidebar says "not in sidecar" rather than quoting a tolerance the simulation
never stated.

The velocity vector is taken from `target.sat.vel_eci` directly, not from the
body quaternion's along-track axis — those differ by the radial component of
velocity, which is zero only on a circular orbit.

Waypoints turn **green once the chaser has been inside the ball** — not when it
reaches that range. The two are different: a chaser 751 m out can still be 40 m
from the 750 m waypoint's centre when it is off the V-bar, and range alone
turned balls green before the vehicle arrived in them.

Not from `currentWaypoint` either: that needs both the index base and the naming
convention to be right, and those are not always separable. An index counting
the waypoint being *approached* spans 1..N, indistinguishable from a 1-based
index counting the last one *reached* — which is what made the stats panel skip
the first waypoint.

Entry is measured in `data/waypoints.py` and packed as a bitmask, so the balls and the
stats panel read the same thing and cannot disagree. "Distance to go" is the
distance to the waypoint's **centre**, so it reports the real remaining flight
rather than `range − standoff`.

A tight tolerance on a close waypoint can be a ball the run never enters — 1% of
20 m is 200 mm. The flag then correctly stays false and the ball stays grey.

Drawn in **every view**.

## Coordinate frames

Three toggles in the view options panel, all drawn from the same packed
quaternions. Axes are x red, y green, z blue; the frames are told apart by
length and named in the panel legend.

| Frame | Axes |
|---|---|
| ECI | x to the vernal equinox, z to the pole |
| Sensor (chaser) | x along-track, y orbit normal, z radial |
| LVLH | x radial, y along-track, z orbit normal |

Axes are labelled with their frame — `x_ECI`, `x_LVLH`, `x_IMU` — because
without the subscript an "x" identifies nothing, and two of these frames are
genuinely the same triad. Vector arrows are labelled too: `v_ECI`, `a_thrust`,
`Δv_IMU`, `LOS_rf`.

**The chaser's sensor frame *is* an LVLH triad.** Spec §3.4 builds it from the
chaser's own position and velocity — radial, along-track, orbit normal — because
the data carries no attitude quaternion. So the sensor axes and any LVLH triad
drawn at the chaser occupy the same three lines in space, and the target's LVLH
is parallel to the chaser's to 145 µrad. No rendering can separate them; only
the axis *naming* differs, by the cyclic relabelling below.

The transported frame therefore says so by style rather than by direction: the
target's LVLH drawn at the chaser has **dashed** shafts and a **tether** back to
the target, against solid shafts for a vehicle's own frame.

**The sensor frame and LVLH share their axis naming** — x radial, y along-track,
z orbit normal — so the only difference between them is which vehicle's state
defines the triad.

Spec §3.4 reads the sensor axes with x along-track, and an early sample appeared
to confirm it. That sample had `isValid` false, with azimuth and elevation both
written as zero, and the x-along-track prediction happened to be zero too —
zeros matching zeros is not a check. Against valid measurements the recorded
azimuth is **1.5694 rad** where x-along-track predicts 0 and x-radial predicts
1.57087. The full repository keeps eight samples of real output as a fixture so
this cannot drift back.

**The two frames are the same triad** — LVLH's x̂ is the sensor frame's z, ŷ is its x, ẑ is its y. The sensor
naming is not a preference: azimuth is `atan2(by, bx)` with x along-track, and
that is what reproduces the recorded rangefinder bearings. Label the sensor
frame LVLH-style and the azimuth reads 90° where the file says 0°.

LVLH is the **target's**, drawn on both vehicles: LVLH is the target's frame and
a rendezvous is flown in it. Measured at the widest separation in the mock run,
the axis drawn at the chaser sits **0.00 µrad** from the target's radial and
**145.50 µrad** from the chaser's own — the full angle between the two frames.

But 145 µrad is **0.0083°**. Two vehicles a kilometre apart on the same orbit
have near-parallel LVLH frames, so no rendering can show which one you are
looking at. Three things carry what the geometry cannot: the chaser's copy is
labelled `x_LVLH(tgt)`, the panel prints the angle to the chaser's own frame,
and the stats panel resolves the relative position in the target's LVLH as
**R-bar / V-bar / H-bar** — components that can only be taken in one of the two
frames, and the reading the frame exists for.

**The Δv arrow is hidden below a noise floor.** Coasting samples read ~1e-6 m/s
of pure sensor noise against a 3e-2 m/s peak, and under the direction-only
policy the arrow is drawn full length whatever the magnitude — so it was thrown
across the scene and span 75–146° between frames. Below
`IMU_DVEL_FLOOR_FRACTION` of the run's peak there is no direction worth drawing.
The panel still reports the measurement; it is the arrow that is meaningless,
not the number.

## Camera controls

| Keys | Action |
|---|---|
| `W A S D` | rotate, or pan — whichever the view's policy allows |
| `Q` / `E` | zoom out / in |
| `R` | recentre |
| `Shift` | 3× faster |
| `Space` | play / pause |
| `←` `→` | step one sample · `Home` / `End` jump to the ends |

The keyboard obeys the same per-view locks as the mouse: a key that panned in a
no-pan view would be a hole in acceptance criterion 7, not a convenience. Held
keys are applied per frame scaled by frame time, so the rate is the same on
every machine.

**The frame check warns, it does not veto.** An estimate is drawn unless it is
non-finite or so far out that the ghost would leave the scene. A filter sitting
860 m off a 1000 m separation is exactly what a navigation overlay is for;
switching it off to complain about the frame hides the thing being investigated.

## Attitude estimate (`chaser.sat.attNav.qHat`)

An optional four-element quaternion, **body to ECI, scalar first** — `qHat[0]`
is w. Read directly; nothing is inferred.

Drawn as a **triad at the chaser** showing where it believes each body axis
points, labelled `x_qHat` / `y_qHat` / `z_qHat`. A frame rather than an arrow
because an attitude estimate is an orientation: three labelled axes say which
way each body axis is believed to point, and a single vector cannot. It has its
own toggle — position and pointing come from different filters and go wrong
independently, so seeing one should not require showing the other. The position
ghost also carries the believed attitude, since a ghost that always faces the
right way hides half of what navigation is getting wrong.

**The mesh needs a permutation the triad does not.** The cubesat is authored
with its nose on +x and wings on ±y, matching the internal triad order
(along-track, normal, radial), while `qHat` is in the sim's body frame,
(radial, along-track, normal). Applying it straight to the mesh put the ghost's
nose on radial — pointing up — with a 90° roll about it. `MESH_FROM_BODY` is
that difference, a 120° turn about (1, 1, 1). The triad needs no such fix: its
axes *are* the body axes, which is what `x_qHat` labels. The check that catches
this is a sample where the attitude error is zero — the ghost must then sit
exactly on the vehicle, and any fixed permutation shows up as 90° or 120°.

The stats panel shows the total error in degrees and its **rotation vector**
resolved on the chaser's R · V · H axes — which way the belief is tipped, not
just how far. Those components used to come from `xHat[6:9]`, so a run logging
only the first six elements displayed `NaN NaN NaN`; they come from `qHat` now,
and their magnitude equals the total angle to 4e-7°.

The consistency check scores the other three readings of the same four numbers
as a tripwire. Reading a quaternion scalar-last turns a near-identity rotation
into roughly a half turn, so a mismatch is worth stating rather than drawing a
body frame pointing somewhere absurd: on the mock run the documented reading
fits at 3.00° against 40.3° for the nearest alternative.

## Diagnosing a frame mismatch

```
python3 tools/diagnose_relnav.py runs/my_run
```

Scores the plausible readings of `xHat[0:3]` against the run's own geometry and
prints each residual over the first 5%, the last 5%, and the whole run.

The time breakdown is the point. **The target's LVLH axes coincide with ECI at
the start of a run** and rotate away at orbital rate — about 0.5° in the first
eight seconds. So a short sample cannot distinguish the two frames at all, and a
reading that fits early and drifts later is in the wrong frame, while one that is
wrong from the first sample has the wrong sense or axis order.

That distinction cost a round trip: the real sample held as a fixture is eight
seconds long, so it confirmed the sense and axis order and said nothing about
the frame, while appearing to confirm everything.

## Renamed variables

The simulation moves things between modules, and a rename should not strand
every run recorded before it. `data/loader.py` gives each column a list of
former names:

| Current | Former |
|---|---|
| `chaser.sat.thruster.thrustAcc_eci` | `chaser.thruster.thrustAcc_eci`, `chaser.sat.thrustAcc_eci` |
| `chaser.sat.thruster.dVAccumulated` | `chaser.sat.guidance.dVAccumulated` |

The canonical name comes from **real output, not the data-recording script** —
the script adds `chaser.thruster.thrustAcc_eci` while the emitted header carries
`chaser.sat.thruster.thrustAcc_eci`. The file is what has to load, so the file
is what the tests assert, and `test_loader.py` checks the generator reproduces
the current header byte for byte.

Either name loads, and a file mixing them loads too. A file carrying **both**
names for one variable is rejected as ambiguous rather than guessed at.

## The payload contract

A contract test in the full repository greps every `OFF.x` and `META.x` the
viewer reads and checks the payload actually packs it. A missing key becomes
`undefined`, which survives arithmetic silently and dies at the `.toFixed` — as
a blank screen reading "Viewer failed to start", naming no field.

That is how `META.relnav.residual_m` shipped: the panel read it, the payload
packed `relative_error`, and every test passed because they all exercised the
*consistent* branch and never rendered the message that used it. A static audit
covers every branch at once, including the ones no test happens to reach.

## Two rules that hold at every stage

- **No derived math outside `data/` and `core/`.** If a panel or view needs a
  number, it comes from `Run` or a helper in `core/`, never computed inline.
- **Each stage ends runnable.** `streamlit run app.py` works at the end of every
  stage, even if what it shows is a placeholder.

## Layout

```
app.py         entry point, page config, layout composition
config.py      paths, THRUST_EPS, arrow scales, colours, panel sizes
state.py       session-state schema and defaults
data/          discovery, loader, Run, events, errors
core/          frames, earth, geometry, units
views/         the six views, cubesat mesh, arrows
panels/        run selector, time controls, timeline, stats, view selector,
               view options, status
spikes/        Stage 0 only -- throwaway
runs/          drop `<name>.csv` + `<name>.json` pairs here
```

Only `data/loader.py` and `data/discovery.py` may change when the input file
format changes (acceptance criterion 11).
