/**
 * OVOZ ORBI — sessiyaning jonli vizuali.
 *
 * Nega ikkita chiziq emas: chiziqli to'lqin "ochilib-yopilib" turadi va
 * gapirish jarayonini emas, shunchaki amplitudani ko'rsatadi. Suhbat esa
 * uzluksiz — vizual ham uzluksiz bo'lishi kerak.
 *
 * Shakl: bir-birining ustidagi uchta yumshoq gradient dog'. Ular doim sekin
 * aylanadi (suhbat tirik), mikrofon darajasi esa ularning KATTALIGINI
 * o'zgartiradi. Gapirilmasa orb kichrayadi, lekin yo'qolmaydi.
 *
 * Holatlar rangda ajraladi:
 *   listening   — ko'k/binafsha (siz gapiryapsiz)
 *   ai_speaking — pushti/sariq (AI gapiryapti)
 *   evaluating  — sokin ko'k, sekin aylanish
 */
const PALETTE = {
  listening: ['#4361ee', '#7c5cf0', '#17a2a2'],
  ai_speaking: ['#e2618c', '#ffcf3d', '#7c5cf0'],
  evaluating: ['#7d94f5', '#a58bff', '#8fd3d3'],
  idle: ['#8f9dbb', '#b0a6cf', '#9fc7c7'],
}

export default function VoiceOrb({ level = 0, state = 'idle', size = 210 }) {
  const colors = PALETTE[state] || PALETTE.idle
  // Daraja 0..1 → 0.72..1.18 oralig'idagi masshtab. Pastki chegara bor:
  // jim turganda ham orb ko'rinib turadi, ya'ni ekran "o'lik" bo'lmaydi.
  const scale = 0.72 + Math.min(1, Math.max(0, level)) * 0.46

  return (
    <div className="orb" style={{ width: size, height: size }} aria-hidden="true">
      <div className="orb__field" style={{ transform: `scale(${scale.toFixed(3)})` }}>
        <span className="orb__blob orb__blob--1" style={{ background: colors[0] }} />
        <span className="orb__blob orb__blob--2" style={{ background: colors[1] }} />
        <span className="orb__blob orb__blob--3" style={{ background: colors[2] }} />
      </div>
      <div className="orb__ring" />
      <div className="orb__core" />
    </div>
  )
}
