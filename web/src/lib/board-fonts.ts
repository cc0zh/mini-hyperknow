export const boardFontFamily = 'Excalifont, Xiaolai, sans-serif'

// The official Latin subset has no Han glyphs, so Chinese uses Xiaolai even
// though the same stack is used in HTML, SVG and Mermaid's text measurement.
export const boardFonts = [
  { family: 'Excalifont', source: 'url("/fonts/Excalifont-Regular.woff2") format("woff2")' },
  { family: 'Xiaolai', source: 'url("/fonts/Xiaolai-Regular.ttf") format("truetype")' },
] as const
