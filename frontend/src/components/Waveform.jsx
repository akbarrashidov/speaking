import { useEffect, useRef } from 'react'

/**
 * Ilovaning imzo elementi. Ikki rejimda ishlaydi:
 *  - `live`: mikrofon signalini surilib boruvchi to'lqin sifatida chizadi;
 *  - `values`: 0..1 massivini ustunlar balandligiga aylantiradi (aniqlik tarixi,
 *    savol natijalari). Ya'ni to'lqin bezak emas, ma'lumot tashiydi.
 *
 * Jonli rejimda React qayta render qilinmaydi — balandliklar to'g'ridan-to'g'ri
 * DOM'ga yoziladi, shuning uchun sessiya davomida ortiqcha yuk bermaydi.
 */
const MIN_SCALE = 0.08
const FRAME_MS = 55

export default function Waveform({
  bars = 28,
  level = 0,
  live = false,
  values = null,
  tone = 'signal',
  className = '',
  style = undefined,
}) {
  const rootRef = useRef(null)
  const heightsRef = useRef(new Array(bars).fill(MIN_SCALE))
  const lastFrameRef = useRef(0)
  const levelRef = useRef(0)

  levelRef.current = level

  useEffect(() => {
    if (!live) return undefined

    let raf = 0
    const tick = (now) => {
      raf = requestAnimationFrame(tick)
      if (now - lastFrameRef.current < FRAME_MS) return
      lastFrameRef.current = now

      const heights = heightsRef.current
      heights.shift()
      // Kvadrat ildiz — jim ovoz ham ko'rinadigan bo'lsin.
      heights.push(Math.max(MIN_SCALE, Math.min(1, Math.sqrt(levelRef.current * 2.2))))

      const node = rootRef.current
      if (!node) return
      for (let i = 0; i < node.children.length; i += 1) {
        node.children[i].style.transform = `scaleY(${heights[i]})`
      }
    }

    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [live])

  const count = values ? values.length : bars

  return (
    <div
      ref={rootRef}
      className={`wave wave--${tone} ${className}`}
      style={style}
      aria-hidden="true"
    >
      {Array.from({ length: count }, (_, i) => (
        <span
          key={i}
          className="wave__bar"
          style={{
            transform: `scaleY(${
              values ? Math.max(MIN_SCALE, values[i]) : MIN_SCALE
            })`,
          }}
        />
      ))}
    </div>
  )
}
