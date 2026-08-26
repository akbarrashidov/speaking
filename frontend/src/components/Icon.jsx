/**
 * Bitta chiziqli ikonka to'plami — tashqi kutubxonasiz (§8 bundle cheklovi).
 *
 * Barchasi 24×24 to'rda, `currentColor` bilan chiziladi va bir xil chiziq
 * qalinligiga ega, shuning uchun matn yonida bir butun bo'lib ko'rinadi.
 */
const PATHS = {
  levels: <path d="M5 20v-5M12 20v-10M19 20v-15" />,
  progress: (
    <>
      <path d="M4 4v14a2 2 0 0 0 2 2h14" />
      <polyline points="8 14 12 10 15 13 20 7" />
    </>
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4" />
    </>
  ),
  moon: <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />,
  logout: (
    <>
      <path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4" />
      <polyline points="9 8 13 12 9 16" />
      <line x1="13" y1="12" x2="3" y2="12" />
    </>
  ),
  arrowLeft: (
    <>
      <line x1="20" y1="12" x2="4" y2="12" />
      <polyline points="10 6 4 12 10 18" />
    </>
  ),
  chevronRight: <polyline points="9 5 16 12 9 19" />,
  // Profil menyusi ochiq/yopiqligini ko'rsatadi.
  chevronUpDown: (
    <>
      <polyline points="8 10 12 6 16 10" />
      <polyline points="8 14 12 18 16 14" />
    </>
  ),
  // Orqaga qaytish uchun. `arrowLeft` dan kaltaroq: 22px li kvadrat ichida
  // uzun o'q chiziqqa aylanib ketadi, uchburchak boshi esa yo'qoladi.
  arrowBack: (
    <>
      <line x1="15.5" y1="12" x2="6" y2="12" />
      <polyline points="10.5 7.5 6 12 10.5 16.5" />
    </>
  ),
  lock: (
    <>
      <rect x="4" y="10" width="16" height="10" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </>
  ),
  check: <polyline points="4 12 9 17 20 6" />,
  play: <path d="M7 4.8v14.4L19.5 12z" fill="currentColor" stroke="none" />,
  stop: <rect x="6" y="6" width="12" height="12" rx="2.5" fill="currentColor" stroke="none" />,
  mic: (
    <>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <line x1="12" y1="18" x2="12" y2="21" />
    </>
  ),
  // Fon shovqini yoqilgan / o'chirilgan (rol suhbat sahnasi).
  sound: (
    <>
      <path d="M5 9v6h4l5 4V5L9 9z" />
      <path d="M17 9.5a3.5 3.5 0 0 1 0 5" />
    </>
  ),
  soundOff: (
    <>
      <path d="M5 9v6h4l5 4V5L9 9z" />
      <line x1="17" y1="9.5" x2="21" y2="14.5" />
      <line x1="21" y1="9.5" x2="17" y2="14.5" />
    </>
  ),
  target: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="3.5" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <polyline points="12 7 12 12 15.5 14" />
    </>
  ),
  speech: <path d="M20 15a2 2 0 0 1-2 2H8l-4 4V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2z" />,
  gauge: (
    <>
      <path d="M3.5 18a8.5 8.5 0 1 1 17 0" />
      <line x1="12" y1="18" x2="16.5" y2="9.5" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <line x1="12" y1="11" x2="12" y2="16.5" />
      <line x1="12" y1="7.5" x2="12" y2="8" />
    </>
  ),
  alert: (
    <>
      <path d="M12 4.5 2.8 19.5h18.4z" />
      <line x1="12" y1="10" x2="12" y2="14" />
      <line x1="12" y1="16.5" x2="12" y2="17" />
    </>
  ),
  error: (
    <>
      <circle cx="12" cy="12" r="9" />
      <line x1="9" y1="9" x2="15" y2="15" />
      <line x1="15" y1="9" x2="9" y2="15" />
    </>
  ),
  // --- mashq rejimlari (§Home) ---
  grammar: (
    <>
      <path d="M4 18V6a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v12" />
      <path d="M4 18a2 2 0 0 0 2 2h13" />
      <path d="M8 9h7M8 13h4" />
    </>
  ),
  phrases: (
    <>
      <path d="M8 11c0-2 1.5-3 3-3M8 11v3h3v-3z" />
      <path d="M15 11c0-2 1.5-3 3-3M15 11v3h3v-3z" />
      <path d="M4 20V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H8z" />
    </>
  ),
  shadowing: (
    <>
      <path d="M4 9a5 5 0 0 1 5-5h6a5 5 0 0 1 5 5" />
      <polyline points="17 3 20 6 17 9" />
      <path d="M20 15a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5" />
      <polyline points="7 21 4 18 7 15" />
    </>
  ),
  roleplay: (
    <>
      <path d="M3 8h18M5 8V6a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v2" />
      <path d="M5 8v10a2 2 0 0 0 2 2h4" />
      <path d="M19 8v4" />
      <path d="M15 20l2-4 2 4z" />
    </>
  ),
  flame: <path d="M12 21a6 6 0 0 0 6-6c0-4-3-5-3-9-3 1.5-4 4-4 6-1 0-2-1-2-2.5C7.5 11 6 13 6 15a6 6 0 0 0 6 6z" />,
  globe: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.5 2.7 2.5 15.3 0 18M12 3c-2.5 2.7-2.5 15.3 0 18" />
    </>
  ),
}

export default function Icon({ name, size = 20, className = '', ...rest }) {
  const glyph = PATHS[name]
  if (!glyph) return null
  return (
    <svg
      className={`icon ${className}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {glyph}
    </svg>
  )
}
