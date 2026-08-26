/**
 * Ilova logotipi — gap pufagi ichida to'lqinning uch ustuni.
 *
 * Belgi ilovaning imzo elementini (Waveform) qotib qolgan holatda takrorlaydi:
 * yon paneldagi nishon va sessiyada harakatlanadigan to'lqin bir tildan
 * gapiradi. Pufak dumi esa nima qilinishini aytadi — gapirish.
 *
 * Ranglar mavzu bilan ALMASHMAYDI, garchi qolgan hamma narsa almashsa ham:
 * bu logotip, holat ko'rsatkichi emas. Shuning uchun `--primary` kabi
 * o'zgaruvchilar bu yerda ishlatilmaydi — brauzer yorlig'idagi favicon.svg va
 * shu belgi bir xil ko'rinishi kerak. To'q ko'k-siyoh juftlik oq sirtda ham,
 * qorong'i panelda ham ochiq turadi (`preview` bilan uch fonda tekshirilgan).
 *
 * Shakl public/favicon.svg dagi bilan bir xil. Belgi o'zgarsa — ikkalasi ham
 * o'zgaradi va `npm run icons` qayta chaqiriladi.
 */
import { useId } from 'react'

export default function Logo({ size = 30, className = '' }) {
  // Bitta sahifada bir nechta logotip bo'lsa, gradient id'lari to'qnashmasin.
  const id = useId()

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#4361ee" />
          <stop offset="1" stopColor="#7c5cf0" />
        </linearGradient>
      </defs>
      <path
        fill={`url(#${id})`}
        d="M10 2h12a8 8 0 0 1 8 8v8a8 8 0 0 1-8 8h-5l-8 5.5 2-5.5h-1a8 8 0 0 1-8-8v-8a8 8 0 0 1 8-8z"
      />
      <g fill="#fff">
        <rect x="7.7" y="10.25" width="4.6" height="7.5" rx="2.3" />
        <rect x="19.7" y="8.25" width="4.6" height="11.5" rx="2.3" />
      </g>
      {/* O'rtadagi ustun marker rangida: 16px da ham nishon ikki rangli
          bo'lib tanaladi, bir dog'ga aylanmaydi. */}
      <rect x="13.7" y="6.25" width="4.6" height="15.5" rx="2.3" fill="#ffcf3d" />
    </svg>
  )
}
