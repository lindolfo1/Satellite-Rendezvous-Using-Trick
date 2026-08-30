# Vendored dependencies

`three.module.min.js` — three.js r160, copied from npm.

Vendored rather than fetched from a CDN at runtime. The viewer renders inside a
`srcdoc` iframe, where a failed import is invisible: no listeners bind, nothing
renders, and the empty state stays up because the code that hides it never ran.
That looks like "the app is broken" rather than "a network request failed".

Inlining it also means the viewer works offline and cannot break because a CDN
changed.

To update:

```
npm install --no-save three@<version>
cp node_modules/three/build/three.module.min.js render/static/vendor/
```

Then re-run `npm test` — `tests/_realtest.mjs` loads the real library.
