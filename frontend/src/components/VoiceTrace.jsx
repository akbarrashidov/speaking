/**
 * OVOZ IZI — shu ilovaning imzosi.
 *
 * Bitta shakl uch o'lchamda takrorlanadi: hafta (bosh sahifa), sessiya (jonli),
 * gap (ro'yxat kartalari). Bu bezak emas — u har doim o'quvchining o'z ovozidan
 * o'lchangan qiymatlarni ko'rsatadi: qancha gapirgani, qanchasi to'g'ri chiqqani.
 *
 * Shakl markaz chizig'iga nisbatan simmetrik va chekkalari yumshoq: abr
 * matosida bo'yoq chegarasi qanday oqib ketsa, nutqda ham tovushlar shunday
 * bir-biriga oqib o'tadi — aniq chegara yo'q.
 */
const W = 100
const H = 34

function smoothBand(values, { height = H, floor = 0.06 } = {}) {
  const points = values.length ? values : [0]
  const step = W / Math.max(points.length - 1, 1)
  const half = height / 2
  const top = []
  const bottom = []

  points.forEach((raw, i) => {
    const value = Math.max(floor, Math.min(1, Number(raw) || 0))
    const x = i * step
    top.push([x, half - value * half])
    bottom.push([x, half + value * half])
  })

  // Katmull-Rom uslubidagi yumshatish: burchaklar emas, oqim.
  const curve = (list) =>
    list
      .map(([x, y], i) => {
        if (i === 0) return `M ${x.toFixed(2)} ${y.toFixed(2)}`
        const [px, py] = list[i - 1]
        const cx = (px + x) / 2
        return `C ${cx.toFixed(2)} ${py.toFixed(2)} ${cx.toFixed(2)} ${y.toFixed(2)} ${x.toFixed(
          2
        )} ${y.toFixed(2)}`
      })
      .join(' ')

  return `${curve(top)} L ${W} ${bottom[bottom.length - 1][1].toFixed(2)} ${curve(
    [...bottom].reverse()
  ).replace(/^M/, 'L')} Z`
}

let gradientSeed = 0

export default function VoiceTrace({
  values = [],
  tone = 'firuza',
  height = H,
  enter = false,
  className = '',
  ...rest
}) {
  const id = `trace-${(gradientSeed += 1)}`
  const stroke =
    tone === 'white'
      ? '#ffffff'
      : tone === 'gold'
        ? 'var(--gold)'
        : tone === 'sage'
          ? 'var(--green)'
          : 'var(--violet)'

  return (
    <svg
      className={`trace ${enter ? 'trace--enter' : ''} ${className}`}
      viewBox={`0 0 ${W} ${height}`}
      preserveAspectRatio="none"
      role="presentation"
      aria-hidden="true"
      {...rest}
    >
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.12" />
          <stop offset="18%" stopColor={stroke} stopOpacity="0.72" />
          <stop offset="82%" stopColor={stroke} stopOpacity="0.72" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0.12" />
        </linearGradient>
      </defs>
      <path className="trace__band" d={smoothBand(values, { height })} fill={`url(#${id})`} />
    </svg>
  )
}

/**
 * Jonli to'lqin — sessiya davomida mikrofon darajasini ko'rsatadi. Bu yerda
 * shakl vaqt bo'ylab suriladi: o'quvchi o'z ovozining izini real vaqtda ko'radi.
 */
export function LiveTrace({ level = 0, bars = 48, className = '' }) {
  const values = []
  for (let i = 0; i < bars; i += 1) {
    // Markazga yaqin joyda balandroq — ovoz manbai o'rtada turgandek.
    const shape = Math.sin((i / (bars - 1)) * Math.PI)
    values.push(Math.max(0.05, level * (0.45 + shape * 0.75)))
  }
  return <VoiceTrace values={values} height={72} className={className} />
}
