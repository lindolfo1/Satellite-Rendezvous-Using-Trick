/* 30_hud.js — the panels of spec 10.
 *
 * Structure is final as of Stage 1; later stages fill bodies, they do not move
 * panels. Each panel exposes update(S) — the browser-side analogue of the
 * build plan's (run, t_index) signature, and the same rule applies: a panel
 * renders and nothing else. It computes no derived data. Every number it shows
 * comes from S.run, which Python computed once.
 */

const $ = id => document.getElementById(id);
const set = (id, txt, cls) => {
  const el = $(id);
  if (!el) return;
  el.textContent = txt;
  el.className = cls || '';
};

/* Spec 8: metres under 1 km, kilometres above. Scene units are km, so this
 * takes km. The authoritative version is core/units.py; this is the display
 * mirror and must agree with it. */
function fmtRange(km) {
  if (km === null || km === undefined || Number.isNaN(km)) return '—';
  if (S.units === 'km') return km.toFixed(3) + ' km';
  if (S.units === 'm') return (km * 1000).toFixed(1) + ' m';
  return Math.abs(km) < 1 ? (km * 1000).toFixed(1) + ' m' : km.toFixed(3) + ' km';
}
/* Fixed-width signed number. The sign occupies a column of its own, so a value
 * crossing zero during playback does not shift everything to its right --
 * tabular-nums alone does not cover the sign (spec 8). */
function fixed(value, decimals, width) {
  // Pad the whole token, sign included. Padding *after* the sign leaves it
  // stranded a few spaces from its digits ("-   2075.30") and, worse, changes
  // the token count when a value crosses zero -- which is the jitter spec 8
  // exists to prevent.
  const text = (value < 0 ? '-' : '') + Math.abs(value).toFixed(decimals);
  return text.padStart(width, ' ');
}

function vec3(f, base, decimals, width) {
  return `${fixed(f[base], decimals, width)} ${fixed(f[base + 1], decimals, width)} ` +
         `${fixed(f[base + 2], decimals, width)}`;
}

const mag3 = (f, base) => Math.hypot(f[base], f[base + 1], f[base + 2]);

/* One sensor's measured/true/error block. Invalid readings are greyed and
 * labelled stale rather than blanked, so the value that was last believed is
 * still visible without being mistaken for a live one. */
function sensorBlock(name, valid, rows) {
  // One class attribute, not two: `class="row" class="stale"` is a duplicate
  // attribute and the second is silently discarded, so the greying never
  // appeared while the markup looked right.
  const stale = valid ? '' : ' stale';
  const flag = valid
    ? '<span class="k">valid</span>'
    : '<span class="warn">INVALID \u00b7 stale</span>';
  const body = rows.map(([label, measured, truth, error]) =>
    `<div class="row${stale}"><span>${label}</span><span>${measured}</span></div>` +
    `<div class="sub${stale}">true ${truth} \u00b7 err ${error}</div>`).join('');
  return `<h4 style="margin-top:6px">${name} \u2014 ${flag}</h4>${body}`;
}

/* Sub-satellite point, fixed width so the hemisphere letters do not slide as
 * the track crosses the equator or the antimeridian. */
function latLon(lat, lon) {
  const deg = (value, width) =>
    Math.abs(value).toFixed(4).padStart(width, ' ') + '\u00b0';
  return `${deg(lat, 7)}${lat >= 0 ? 'N' : 'S'} ${deg(lon, 8)}${lon >= 0 ? 'E' : 'W'}`;
}
const mmss = s => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

/* ---- view selector (spec 9) ------------------------------------------- */
function buildViewButtons() {
  $('view_buttons').innerHTML = '';
  for (const [id, label, desc] of VIEWS) {
    const b = document.createElement('button');
    b.innerHTML = `${label}<small>${desc}</small>`;
    b.title = desc;                       // hover reveals the purpose
    b.setAttribute('aria-pressed', String(S.view === id));
    b.onclick = () => { S.view = id; recentre(); syncViewButtons(); HUD.options(); };
    $('view_buttons').appendChild(b);
  }
  const r = document.createElement('button');
  r.textContent = 'Recentre';
  r.style.marginTop = '6px';
  r.onclick = recentre;
  $('view_buttons').appendChild(r);
}
function syncViewButtons() {
  [...$('view_buttons').querySelectorAll('button')].forEach((b, i) => {
    if (VIEWS[i]) b.setAttribute('aria-pressed', String(S.view === VIEWS[i][0]));
  });
}

/* ---- rate presets (spec 7) -------------------------------------------- */
function buildRateButtons() {
  $('rate_buttons').innerHTML = '';
  for (const r of RATES) {
    const b = document.createElement('button');
    b.textContent = r + '×';
    b.onclick = () => { S.rate = r; syncRateButtons(); };
    $('rate_buttons').appendChild(b);
  }
  syncRateButtons();
}
function syncRateButtons() {
  [...$('rate_buttons').children].forEach((b, i) =>
    b.setAttribute('aria-pressed', String(S.rate === RATES[i])));
}

const HUD = {
  stats() {
    if (!S.run) return;
    // Stage 8 fills the rest from Run's derived arrays. What is shown here is
    // only what Stage 3 loads directly: no derived math in a panel.
    const b = S.idx * S.run.stride;
    const f = S.run.flat;
    const c = b + OFF.chaser_pos, t = b + OFF.target_pos;

    // Packed by render/payload.py in metres. Differencing the two float32
    // kilometre positions here would be wrong by up to half a metre, which is
    // most of the answer once the vehicles are metres apart.
    const range_km = f[b + OFF.true_range] / 1000;
    set('f_range', fmtRange(range_km));
    set('f_trange', fmtRange(range_km));

    /* Position as the sub-satellite point and height above the ellipsoid.
     * Deliberately not the ECI xyz of spec 8: three numbers in a frame you have
     * to hold in your head, next to a magnitude that is just the orbit radius.
     * This is the same information you can read off the globe behind it. */
    const cl = b + OFF.chaser_llh, tl = b + OFF.target_llh;
    set('f_cpos', latLon(f[cl], f[cl + 1]));
    set('f_calt', (f[cl + 2] / 1000).toFixed(3).padStart(10, ' ') + ' km up');
    set('f_tpos', latLon(f[tl], f[tl + 1]));
    set('f_talt', (f[tl + 2] / 1000).toFixed(3).padStart(10, ' ') + ' km up');

    const cv = b + OFF.chaser_vel, tv = b + OFF.target_vel;
    set('f_cvel', mag3(f, cv).toFixed(3) + ' m/s');
    set('f_cvel_xyz', vec3(f, cv, 2, 9));
    set('f_tvel', mag3(f, tv).toFixed(3) + ' m/s');
    set('f_tvel_xyz', vec3(f, tv, 2, 9));

    /* The relative position resolved in the *target's* LVLH: R-bar, V-bar,
     * H-bar. This is the reading the target's frame exists for -- the drawn
     * axes cannot show which vehicle's frame they are, because the two are
     * parallel to 0.008 degrees, but these components can only be taken in
     * one of them. */
    const rv = b + OFF.rel_lvlh;
    set('f_rvh', vec3(f, rv, 2, 9) + ' m');

    const thrusting = f[b + OFF.thrusting] > 0.5;
    const ta = b + OFF.thrust_acc;
    /* Coasting means zero. The same THRUST_EPS that decides the THRUSTING
     * indicator decides this, so the label and the number cannot disagree --
     * reporting "coasting · 3.55e-15 m/s²" invites you to wonder which is
     * lying. Numerical residue below the threshold is not a small thrust. */
    const accel = thrusting ? mag3(f, ta) : 0;
    set('f_cacc', (accel === 0 ? '0.00000'
                 : accel >= 1e-3 ? accel.toFixed(5)
                 : accel.toExponential(2)) + ' m/s²');
    set('f_cacc_xyz', thrusting ? vec3(f, ta, 5, 9)
                                : vec3([0, 0, 0], 0, 5, 9));
    set('f_dv', f[b + OFF.dv].toFixed(4) + ' m/s');
    /* The waypoint being *approached*, and how far is left to it. Both come
     * from the payload: choosing the right corridor entry needs the convention
     * detected at load (see data/events.detect_waypoint_convention), which is
     * not a decision a panel should be making. */
    const target = Math.round(f[b + OFF.wp_target]);
    const corridor = META.waypoint_range_m || [];
    const complete = target < 0 || target >= corridor.length;
    set('f_wp', complete ? 'corridor complete'
                         : `\u2192 ${target} · ${corridor[target]} m`);

    set('f_wpdist', complete ? '—' : fmtRange(f[b + OFF.wp_distance] / 1000));

    set('f_thrust', thrusting ? 'THRUSTING' : 'coasting',
        thrusting ? 'k' : 'muted');

    /* How far the chaser's belief is from the truth. Shown whenever the run
     * carries a usable filter state, toggle or not -- the number costs no room
     * and is the reason the estimate is interesting. */
    if (META.has_relnav) {
      const e = b + OFF.nav_err;
      set('f_naverr', fmtRange(mag3(f, e) / 1000));
      set('f_naverr_xyz', vec3(f, e, 3, 9) + ' m ECI');

    } else {
      set('f_naverr', '\u2014');
      set('f_naverr_xyz', 'no relNav.xHat in this run', 'muted');
    }

    /* Attitude error, from `attNav.qHat` where the run carries it. That is an
     * absolute attitude estimate; xHat[6:9] was only the filter's leftover
     * correction, so where both exist the qHat figure is the one that answers
     * "how far off is the pointing". Degrees, because a pointing error large
     * enough to matter is degrees, not milliradians. */
    if (META.has_attnav) {
      set('f_navatt',
          (f[b + OFF.att_err_rad] * 180 / Math.PI).toFixed(3) + '\u00b0');
      const a = b + OFF.att_err_rvh;
      set('f_navatt_xyz',
          [0, 1, 2].map(k => fixed(f[a + k] * 1e3, 3, 8)).join(' ')
          + ' mrad R\u00b7V\u00b7H');
    } else if (META.has_relnav && OFF.nav_att_err !== undefined) {
      // The older source: xHat[6:9], the filter's leftover correction. Absent
      // on runs that log only the first six elements, which is why this row
      // read NaN before qHat arrived.
      const a = b + OFF.nav_att_err;
      set('f_navatt', (f[b + OFF.nav_att_rad] * 1e3).toFixed(3) + ' mrad');
      const known = [0, 1, 2].every(k => Number.isFinite(f[a + k]));
      set('f_navatt_xyz', known
          ? [0, 1, 2].map(k => fixed(f[a + k] * 1e3, 3, 8)).join(' ')
            + ' mrad R\u00b7V\u00b7H'
          : 'no attitude state logged', known ? '' : 'muted');
    } else {
      set('f_navatt', '\u2014');
      set('f_navatt_xyz', 'no attNav.qHat in this run', 'muted');
    }
  },

  /* The WASD hint changes meaning with the view, because the policy decides
   * what those keys do. Saying "rotate" in a view that cannot rotate would be
   * worse than saying nothing. */
  keyhints() {
    const p = POLICY[viewDef(S.view)[3]];
    const el = $('hint_wasd');
    if (!el) return;
    el.textContent = p.rotate ? 'rotate' : (p.pan ? 'pan' : '— (locked)');
  },

  options() {
    // Sensor toggles are chaser-only (spec 9b): the target carries no sensors.
    const ok = isChaserView();
    $('t_imu').disabled = !ok;
    $('t_rf').disabled = !ok;
    $('t_body').disabled = !ok;
    $('t_imu').setAttribute('aria-pressed', String(S.imu && ok));
    $('t_rf').setAttribute('aria-pressed', String(S.rangefinder && ok));
    $('t_arrowscale').setAttribute('aria-pressed', String(S.arrowScale === 'relative'));
    $('t_graticule').setAttribute('aria-pressed', String(S.graticule));
    $('t_nav').disabled = !META.has_relnav;
    $('t_nav').setAttribute('aria-pressed', String(S.showNav && !!META.has_relnav));
    $('t_attnav').disabled = !META.has_attnav;
    $('t_attnav').setAttribute('aria-pressed',
                               String(S.showAttNav && !!META.has_attnav));

    /* Say which reading of xHat was identified. A ghost drawn in the wrong
     * frame looks like a navigation error rather than a misreading, so the
     * frame is stated rather than assumed silently. */
    const navNote = $('nav_note');
    if (!META.relnav) {
      navNote.textContent = META.has_relnav ? '' : 'No relNav.xHat in this run.';
    } else if (META.relnav.usable === false) {
      navNote.innerHTML = `<span class="warn">xHat is not usable</span> \u2014 `
        + `non-finite, or too far out to place in the scene. Nothing drawn.`;
    } else if (!META.relnav.consistent) {
      /* The estimate does not sit where the target's LVLH says it should, so
       * the sim's frame has moved and drawing it would look like a navigation
       * failure rather than a mismatch. If the opposite sense fits, say so --
       * that is the one thing worth knowing here, and it is a one-line fix. */
      /* Reported in metres against the widest separation in the run, not as a
       * fraction of the instantaneous one: near contact a correct filter is
       * routinely a larger number than the gap it is measuring. */
      /* A warning, not a veto. The estimate is still drawn: a filter sitting
       * 860 m off a 1000 m separation is exactly what this overlay is for, and
       * switching it off to complain about the frame hides the thing being
       * investigated. */
      navNote.innerHTML = `<span class="warn">xHat does not match the target\u2019s `
        + `LVLH</span> \u2014 ${META.relnav.residual_m.toFixed(2)} m against a `
        + `${META.relnav.scale_m.toFixed(0)} m widest separation. `
        + `Drawn anyway; treat the ghost with suspicion.`
        + (META.relnav.alternative
           ? `<br>${META.relnav.alternative} fits at `
             + `${META.relnav.alternative_residual_m.toFixed(2)} m. `
             + `Run <code>tools/diagnose_relnav.py</code> on this file.`
           : '');
    } else {
      navNote.textContent = `xHat: ${META.relnav.frame}`;
    }
    $('t_eci').setAttribute('aria-pressed', String(S.showEci));
    $('t_body').setAttribute('aria-pressed', String(S.showBody && ok));
    $('t_lvlh').setAttribute('aria-pressed', String(S.showLvlh));
    $('t_navframe').disabled = !META.has_relnav;
    $('t_navframe').setAttribute('aria-pressed',
                                 String(S.showNavFrame && !!META.has_relnav));

    /* The legend carries the axis definitions, because the two frames are the
     * same triad under different names and the arrows alone cannot say so. */
    const legend = [];
    if (S.showEci) legend.push('ECI · x vernal eq, z pole');
    if (S.showBody && ok) {
      legend.push('sensor · x radial, y along-track, z normal \u2014 the '
                  + 'chaser\u2019s own LVLH triad; no attitude in the data');
    }
    if (S.showLvlh) legend.push('LVLH · x radial, y along-track, z normal \u2014 the target\u2019s, drawn on both');
    if (S.showNavFrame && META.has_relnav) {
      legend.push('est \u00b7 the sensor frame as the filter believes it '
                  + '\u2014 same axes, turned by xHat[6:9]');
    }
    /* Answer "that looks like the chaser's frame" with a number. It is the
     * target's; the two are simply near-parallel at rendezvous separations. */
    const angleEl = $('lvlh_angle');
    if (S.showLvlh && S.run) {
      const urad = S.run.flat[S.idx * S.run.stride + OFF.lvlh_angle];
      angleEl.innerHTML =
        `dashed + tether = the target\u2019s frame, carried to the chaser.<br>`
        + `The chaser\u2019s own is ${urad.toFixed(1)} \u00b5rad away `
        + `(${(urad * 180e-6 / Math.PI).toFixed(4)}\u00b0), so it cannot look different.`;
    } else {
      angleEl.textContent = '';
    }

    $('frame_legend').innerHTML = legend.length
      ? 'x <span style="color:#ff5252">\u2588</span> y <span style="color:#69f0ae">\u2588</span> '
        + 'z <span style="color:#448aff">\u2588</span><br>' + legend.join('<br>')
      : 'No frames shown.';

    /* The burn arrow scale, stated rather than left to be inferred -- an arrow
     * whose length means something needs to say what (spec 9a). */
    const legendEl = $('burn_legend');
    if (S.view.startsWith('plane') && META.burn_dv_max) {
      legendEl.textContent =
        `burn arrows \u2192 length \u221d \u0394v, longest = `
        + `${META.burn_dv_max.toFixed(2)} m/s at `
        + `${((META.burn_arrow_max_frac || 0.08) * 100).toFixed(0)}% of Earth radius`;
    } else {
      legendEl.textContent = '';
    }

    /* Which reading of qHat was used, and how far the belief is from truth.
     * Reading a quaternion scalar-last turns a near-identity rotation into
     * roughly a half turn, so a mismatch is worth stating rather than drawing
     * a body frame pointing somewhere absurd. */
    const attNote = $('att_note');
    if (!META.attnav) {
      attNote.textContent = META.has_attnav ? '' : '';
    } else if (!META.relnav || META.attnav.consistent) {
      attNote.textContent =
        `${META.attnav.reading} \u2014 attitude error `
        + `${META.attnav.error_deg.toFixed(2)}\u00b0`;
    } else {
      attNote.textContent = '';
    }
    if (META.attnav && !META.attnav.consistent) {
      attNote.innerHTML = `<span class="warn">qHat does not match the true `
        + `attitude</span> \u2014 ${META.attnav.error_deg.toFixed(0)}\u00b0 out. `
        + `Read ${META.attnav.other} it is ${META.attnav.other_deg.toFixed(1)}\u00b0.`;
    }

    this.sensors();
  },

  /* Measured vs. true vs. error, spec 9b. Validity is prominent and an invalid
   * reading is greyed and labelled stale -- its arrow is already hidden. */
  sensors() {
    const box = $('sensor_readout');
    if (!isChaserView()) {
      box.innerHTML = 'Target view \u2014 no onboard sensors in this data.';
      box.className = 'muted';
      return;
    }
    if (!S.run || (!S.imu && !S.rangefinder)) {
      box.innerHTML = 'No sensor selected.';
      box.className = 'muted';
      return;
    }
    const b = S.idx * S.run.stride, f = S.run.flat;
    const rows = [];

    if (S.rangefinder) {
      const valid = f[b + OFF.rf_valid] > 0.5;
      const range = f[b + OFF.rf_range], trueRange = f[b + OFF.true_range];
      const az = f[b + OFF.rf_az], azTrue = f[b + OFF.az_true];
      const el = f[b + OFF.rf_el], elTrue = f[b + OFF.el_true];
      rows.push(sensorBlock('rangefinder', valid, [
        ['range', `${range.toFixed(3)} m`, `${trueRange.toFixed(3)} m`,
         `${(range - trueRange).toFixed(3)} m`],
        ['azimuth', `${(az * 1e3).toFixed(3)} mrad`, `${(azTrue * 1e3).toFixed(3)} mrad`,
         `${((az - azTrue) * 1e3).toFixed(3)} mrad`],
        ['elevation', `${(el * 1e3).toFixed(3)} mrad`, `${(elTrue * 1e3).toFixed(3)} mrad`,
         `${((el - elTrue) * 1e3).toFixed(3)} mrad`],
      ]));
    }

    if (S.imu) {
      const valid = f[b + OFF.imu_valid] > 0.5;
      const m = b + OFF.imu_dvel, t2 = b + OFF.dv_true;
      const measured = Math.hypot(f[m], f[m + 1], f[m + 2]);
      const truth = Math.hypot(f[t2], f[t2 + 1], f[t2 + 2]);
      const err = Math.hypot(f[m] - f[t2], f[m + 1] - f[t2 + 1], f[m + 2] - f[t2 + 2]);
      rows.push(sensorBlock('IMU \u0394v', valid, [
        ['|\u0394v|', measured.toExponential(3) + ' m/s', truth.toExponential(3) + ' m/s',
         err.toExponential(3) + ' m/s'],
      ]));
    }

    box.innerHTML = rows.join('');
    box.className = '';
  },

  status() {
    set('f_run', META.stem || '—');
    set('f_utc0', META.utc_start ? META.utc_start.replace('T', ' ').slice(0, 19) + 'Z' : '—');
    set('f_sample', S.run ? `${S.idx.toLocaleString()} / ${(S.run.n - 1).toLocaleString()}` : '—');
    set('f_wpbase',
        META.wp_base === undefined || META.wp_base === null ? '—'
        : `${META.wp_base}-based${META.wp_base_ambiguous ? ' (ambiguous)' : ''}`,
        META.wp_base_ambiguous ? 'warn' : '');
    const burns = (META.burns || []).length;
    const wps = (META.events || []).filter(e => e.kind === 'waypoint').length;
    set('f_events', S.run ? `${burns} burns · ${wps} waypoints` : '—');
    set('f_dvsum', META.total_dv_mps === undefined ? '—'
        : META.total_dv_mps.toFixed(3) + ' m/s');
    /* Line of sight, spec 9c. On a rendezvous the two vehicles are within a
     * kilometre on the same orbit, so this reads "clear" throughout; it earns
     * its keep on wider separations. */
    if (!S.run) set('f_los', '—');
    else {
      const clear = S.run.flat[S.idx * S.run.stride + OFF.los_clear] > 0.5;
      set('f_los', clear ? 'clear' : 'BLOCKED by Earth', clear ? '' : 'warn');
    }
    set('f_gmst', S.run
        ? (S.run.flat[S.idx * S.run.stride + OFF.gmst] * 180 / Math.PI).toFixed(3) + '\u00b0'
        : '—');
    $('t_units').textContent = 'units: ' + S.units;
  },

  time() {
    const sc = $('scrub');
    if (!S.run) { sc.max = '0'; sc.disabled = true; return; }
    sc.disabled = false;
    sc.max = String(S.run.n - 1);
    sc.value = String(S.idx);
    const el = S.run.time[S.idx] - S.run.time[0];
    set('f_elapsed', `${el.toFixed(1)} s · ${mmss(el)}`);
    if (META.utc_start) {
      set('f_utc', new Date(Date.parse(META.utc_start) + el * 1000)
        .toISOString().slice(11, 19) + 'Z');
    }
    $('playhead').style.left = (100 * S.idx / Math.max(1, S.run.n - 1)) + '%';
  },

  /* Delegated to 60_cinepanel.js: a different reader, a different design. */
  cinematic() { updateCinePanel(); },

  all() {
    this.stats(); this.options(); this.status(); this.time(); this.keyhints();
    this.cinematic();
  },
};
