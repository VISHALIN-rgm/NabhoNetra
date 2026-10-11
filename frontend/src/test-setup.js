// jsdom has no SVG support, so Leaflet finds no renderer for circles and lines. This lets the map page render in tests.
if (typeof SVGElement !== "undefined") SVGElement.prototype.createSVGRect ||= () => ({});
