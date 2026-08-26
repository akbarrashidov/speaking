import { useI18n } from '../i18n'

/**
 * Qadam ko'rsatkichi: nuqtalar, joriy qadam esa uzun chiziqcha bo'lib cho'ziladi.
 *
 * Nega matn emas. "1-qadam — 2 dan" o'qishni talab qiladi, shakl esa bir
 * qarashda ko'rinadi: nechta qadam bor va qayerdasiz. Ro'yxatdan o'tishda
 * o'quvchining diqqati formada bo'lishi kerak, ko'rsatkichda emas.
 *
 * Ko'rinish ma'lumot uzatadi, ya'ni ekran o'qish dasturi uchun u yo'q. Shu
 * bois o'sha ma'lumot `aria-label` da so'z bilan ham beriladi — nuqtalarning
 * o'zi esa `aria-hidden`.
 */
export default function Steps({ total = 2, current = 1 }) {
  const { t } = useI18n()
  return (
    <div
      className="steps"
      role="img"
      aria-label={t('steps.aria', { current, total })}
    >
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          aria-hidden="true"
          className={`steps__dot${i + 1 === current ? ' is-current' : ''}`}
        />
      ))}
    </div>
  )
}
