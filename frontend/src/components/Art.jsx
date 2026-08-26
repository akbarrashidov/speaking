/**
 * EMBLEMALAR — SVG, ingichka chiziqli, bitta rangda.
 *
 * Nega multfilm sahna emas: bu ilovadan 10 yoshli o'quvchi ham, 40 yoshli
 * mutaxassis ham foydalanadi. Bo'yalgan personajlar birinchisini bir kun
 * qiziqtiradi, ikkinchisini esa darhol uzoqlashtiradi. Ingichka chiziqli
 * geometrik belgi ikkalasi uchun ham ishlaydi: u ma'no beradi, lekin
 * o'zini ko'z-ko'z qilmaydi.
 *
 * Qoidalar: 1.5px chiziq, to'ldirish yo'q (yoki juda kam), rang — `currentColor`,
 * ya'ni har emblema o'z bo'limining rangini oladi va mavzu bilan o'zgaradi.
 */

const stroke = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
}

/* --- rejim emblemalari ---------------------------------------------------- */

/** Grammatika: gap qatorlari va tuzatilgan bo'lak. */
function GrammarEmblem(props) {
  return (
    <svg viewBox="0 0 48 48" {...props}>
      <g {...stroke}>
        <rect x="6" y="9" width="36" height="30" rx="3" />
        <path d="M12 18h24M12 24h16" />
        <path d="M12 31h9" />
        <path d="M26 31.5l3.5 3.5L38 26" strokeWidth="2" />
      </g>
    </svg>
  )
}

/** Iboralar: ikkita qo'shtirnoq — tayyor ibora belgisi. */
function PhrasesEmblem(props) {
  return (
    <svg viewBox="0 0 48 48" {...props}>
      <g {...stroke}>
        <path d="M7 12h34a3 3 0 0 1 3 3v18a3 3 0 0 1-3 3H20l-9 7v-7H7a3 3 0 0 1-3-3V15a3 3 0 0 1 3-3z" />
        <path d="M15 27c-2.2 0-4-1.8-4-4s1.8-4 4-4v-3.5c-4.1 0-7.5 3.4-7.5 7.5V27z" />
        <path d="M27 27c-2.2 0-4-1.8-4-4s1.8-4 4-4v-3.5c-4.1 0-7.5 3.4-7.5 7.5V27z" />
      </g>
    </svg>
  )
}

/** Shadowing: bir to'lqin va uning aksi. */
function ShadowingEmblem(props) {
  const bars = [10, 20, 30, 22, 12, 26, 16]
  return (
    <svg viewBox="0 0 48 48" {...props}>
      <g {...stroke}>
        {bars.map((h, i) => (
          <path key={i} d={`M${8 + i * 5.5} ${21 - h / 2}v${h}`} />
        ))}
      </g>
      <g {...stroke} opacity="0.4">
        {bars.map((h, i) => (
          <path key={i} d={`M${8 + i * 5.5} ${39 - h / 3}v${(h / 3) * 2}`} />
        ))}
      </g>
      <path d="M4 30h40" {...stroke} strokeDasharray="2 3" opacity="0.6" />
    </svg>
  )
}

/** Rol suhbat: ikki tomonning gap oynalari — muloqot. */
function RoleplayEmblem(props) {
  return (
    <svg viewBox="0 0 48 48" {...props}>
      <g {...stroke}>
        <path d="M5 9h22a3 3 0 0 1 3 3v11a3 3 0 0 1-3 3H14l-6 5v-5H5a3 3 0 0 1-3-3V12a3 3 0 0 1 3-3z" />
        <path d="M43 20h-9a3 3 0 0 0-3 3v11a3 3 0 0 0 3 3h9l3 4v-4a3 3 0 0 0 0-.4V23a3 3 0 0 0-3-3z" />
        <path d="M9 15h14M9 20h9" />
        <path d="M36 27h7M36 32h4" />
      </g>
    </svg>
  )
}

const EMBLEMS = {
  grammar: GrammarEmblem,
  phrases: PhrasesEmblem,
  shadowing: ShadowingEmblem,
  roleplay: RoleplayEmblem,
}

/** Rejim ranglari — bo'lim belgisi, bezak emas. */
export const MODE_COLOR = {
  grammar: 'var(--primary)',
  phrases: 'var(--violet)',
  shadowing: 'var(--teal)',
  roleplay: 'var(--pink)',
}

export function ModeEmblem({ kind, className = '' }) {
  const Emblem = EMBLEMS[kind] || GrammarEmblem
  return <Emblem className={className} role="presentation" aria-hidden="true" />
}

/* --- kunlik maqsad halqasi ------------------------------------------------
   Til platformalarining asosiy motivatsiya elementi: bugun qancha bajarilgani
   bitta shaklda ko'rinadi. Raqam markazda, halqa esa qancha qolganini
   ko'rsatadi — matn o'qimasdan ham tushunarli.
   ------------------------------------------------------------------------- */

export function ProgressRing({ value = 0, size = 76, thickness = 7, tone = '', children }) {
  const r = (size - thickness) / 2
  const c = 2 * Math.PI * r
  const done = Math.max(0, Math.min(1, value))
  return (
    <div
      className={`ring ${tone === 'dark' ? 'ring--on-dark' : ''}`}
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--ring-track)"
          strokeWidth={thickness}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--ring-fill)"
          strokeWidth={thickness}
          strokeLinecap="round"
          strokeDasharray={`${c * done} ${c}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <div className="ring__center">{children}</div>
    </div>
  )
}

/* --- o'quv yo'li belgilari ------------------------------------------------ */

export function StepMark({ state = 'locked', index }) {
  if (state === 'mastered') {
    return (
      <span className="step__mark step__mark--done" aria-hidden="true">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <path
            d="M5 12.5l4.5 4.5L19 7.5"
            stroke="currentColor"
            strokeWidth="2.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    )
  }
  if (state === 'locked') {
    return (
      <span className="step__mark step__mark--locked" aria-hidden="true">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
          <rect x="4" y="10" width="16" height="10" rx="2" stroke="currentColor" strokeWidth="2" />
          <path d="M8 10V7a4 4 0 0 1 8 0v3" stroke="currentColor" strokeWidth="2" />
        </svg>
      </span>
    )
  }
  return (
    <span className="step__mark step__mark--active" aria-hidden="true">
      {index}
    </span>
  )
}

/* --- audio belgilari ------------------------------------------------------
   Ilova ovoz haqida, shuning uchun bo'limlarda ovoz shakllari takrorlanadi:
   ekvalayzer, mikrofon halqalari, tovush yoyi. Hammasi ingichka chiziqli va
   `currentColor` bilan — ular bo'limning rangini oladi.
   ------------------------------------------------------------------------- */

/** Ekvalayzer — "bu yerda gapiriladi" belgisi. */
export function EqualizerMark({ className = '', bars = 9 }) {
  const heights = [12, 26, 40, 22, 34, 16, 30, 20, 10]
  return (
    <svg
      viewBox="0 0 96 48"
      className={className}
      role="presentation"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="3"
      strokeLinecap="round"
    >
      {Array.from({ length: bars }, (_, i) => {
        const h = heights[i % heights.length]
        return <path key={i} d={`M${6 + i * 11} ${24 - h / 2}v${h}`} opacity={0.35 + (h / 40) * 0.65} />
      })}
    </svg>
  )
}

/** Mikrofon va tovush halqalari. */
export function MicMark({ className = '' }) {
  return (
    <svg viewBox="0 0 64 64" className={className} role="presentation" aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <rect x="26" y="10" width="12" height="24" rx="6" />
        <path d="M20 30a12 12 0 0 0 24 0" />
        <path d="M32 42v8M26 50h12" />
        <path d="M14 24a18 18 0 0 0 0 12" opacity="0.5" />
        <path d="M50 24a18 18 0 0 1 0 12" opacity="0.5" />
        <path d="M7 20a28 28 0 0 0 0 20" opacity="0.28" />
        <path d="M57 20a28 28 0 0 1 0 20" opacity="0.28" />
      </g>
    </svg>
  )
}

/** Tovush yoyi — matn yonidagi kichik bezak. */
export function SoundArc({ className = '' }) {
  return (
    <svg viewBox="0 0 28 28" className={className} role="presentation" aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <path d="M10 18a10 10 0 0 0 0-8" />
        <path d="M17 22a18 18 0 0 0 0-16" opacity="0.55" />
        <path d="M24 26a26 26 0 0 0 0-24" opacity="0.3" />
      </g>
    </svg>
  )
}

/* --- bo'sh holatlar ------------------------------------------------------- */

export function EmptyChatArt() {
  return (
    <svg width="96" height="72" viewBox="0 0 96 72" role="presentation" aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="1.5" opacity="0.5">
        <path d="M8 8h56a4 4 0 0 1 4 4v28a4 4 0 0 1-4 4H30l-10 8v-8h-12a4 4 0 0 1-4-4V12a4 4 0 0 1 4-4z" />
        <path d="M18 20h32M18 30h18" />
        <path d="M78 30a12 12 0 0 0 0-16" strokeLinecap="round" />
        <path d="M88 36a22 22 0 0 0 0-28" strokeLinecap="round" />
      </g>
    </svg>
  )
}

export function EmptyListArt() {
  return (
    <svg width="88" height="72" viewBox="0 0 88 72" role="presentation" aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="1.5" opacity="0.5">
        <rect x="8" y="8" width="72" height="14" rx="3" />
        <rect x="8" y="29" width="72" height="14" rx="3" />
        <rect x="8" y="50" width="72" height="14" rx="3" strokeDasharray="3 3" />
        <path d="M16 15h20M16 36h28M16 57h16" />
      </g>
    </svg>
  )
}
