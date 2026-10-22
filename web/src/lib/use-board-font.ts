import { useEffect, useState } from 'react'
import { boardFonts } from './board-fonts'

export function useBoardFont() {
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let stopped = false
    setState('loading')
    // Both real resources must load before any glyph-dependent measurement.
    // A system fallback or just one successful download is not font-ready.
    const faces = boardFonts.map(font => new FontFace(font.family, font.source))
    void Promise.all(faces.map(face => face.load())).then(loaded => {
      if (stopped) return
      loaded.forEach(face => document.fonts.add(face))
      return document.fonts.ready.then(() => { if (!stopped) setState('ready') })
    }).catch(() => { if (!stopped) setState('error') })
    return () => { stopped = true; faces.forEach(face => document.fonts.delete(face)) }
  }, [attempt])
  return { state, retry: () => setAttempt(value => value + 1) }
}
