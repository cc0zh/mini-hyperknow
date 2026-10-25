// Opaque-origin preview: scripts cannot read the host or its credentials.
// This is not a resource sandbox or a guarantee against arbitrary script-driven
// self-navigation. Static navigation is removed; CSP blocks third-party loads.
export const ANIMATION_SANDBOX = 'allow-scripts'
export const ANIMATION_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; frame-src 'none'; child-src 'none'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none';"

export function animationScriptIssue(script: string): string | null {
  // Reject obvious navigation/import constructs without pretending that a
  // deny-list can constrain arbitrary JavaScript or computed property access.
  return /\b(?:location|open|importScripts|import|eval)\s*(?:[.(=]|\b)|\b(?:parent|top|opener)\s*[.[]/i.test(script)
    ? '动画脚本包含导航或外部执行入口，已停止预览。' : null
}

export function sanitizeAnimationHtml(html: string): string {
  const parsed = new DOMParser().parseFromString(html, 'text/html')
  parsed.querySelectorAll('meta,base,form,iframe,frame,frameset,object,embed,applet,portal,link,audio,video,source,track,template').forEach(element => element.remove())
  for (const script of parsed.querySelectorAll('script')) {
    if (script.hasAttribute('src') || script.hasAttribute('type') && !['text/javascript', 'application/javascript', ''].includes(script.getAttribute('type') || '')) {
      script.remove()
      continue
    }
    const issue = animationScriptIssue(script.textContent || '')
    if (issue) throw new Error(issue)
  }
  for (const element of parsed.querySelectorAll('*')) {
    for (const attribute of [...element.attributes]) {
      const name = attribute.name.toLowerCase()
      const value = attribute.value.trim()
      if (name.startsWith('on') || ['action', 'formaction', 'target', 'download', 'ping', 'srcdoc', 'srcset', 'http-equiv', 'nonce'].includes(name)) element.removeAttribute(attribute.name)
      else if (name === 'href' || name === 'xlink:href') {
        if (element.localName === 'a' || !value.startsWith('#')) element.removeAttribute(attribute.name)
      } else if (['src', 'poster', 'data', 'background'].includes(name) && !(element.localName === 'img' && /^data:image\/(png|gif|jpeg|webp);base64,[a-z0-9+/=\s]+$/i.test(value))) element.removeAttribute(attribute.name)
      else if (name === 'style' && /@import|url\(/i.test(value)) element.removeAttribute(attribute.name)
    }
  }
  for (const style of parsed.querySelectorAll('style')) {
    // CSP remains authoritative for escaped CSS URLs and any dynamic styles.
    style.textContent = (style.textContent || '').replace(/@import[^;]*;?/gi, '').replace(/url\([^)]*\)/gi, 'none')
  }
  // Full documents commonly put teaching scripts/styles in <head>; preserve
  // those safe nodes rather than accidentally dropping the animation itself.
  return [...parsed.head.querySelectorAll('style,script')].map(element => element.outerHTML).join('\n') + parsed.body.innerHTML
}

export function animationSrcDoc(html: string): string {
  return `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="${ANIMATION_CSP}"><meta name="viewport" content="width=device-width,initial-scale=1"><style>html,body{margin:0;min-height:100%;font-family:system-ui,sans-serif}body{overflow:auto}</style></head><body>${sanitizeAnimationHtml(html)}</body></html>`
}
