import { useState } from 'react'

import Banner from '../components/Banner'
import Icon from '../components/Icon'
import Steps from '../components/Steps'
import { api } from '../api'
import { useAuth } from '../auth/AuthContext'
import { useI18n } from '../i18n'

/**
 * Ro'yxatdan o'tishning IKKINCHI qadami.
 *
 * Nega alohida ekran. Birinchi qadamda akkaunt yaratiladi — email, parol, ism.
 * Bu yerda o'quvchi o'zi haqida gapiradi. Ikkalasi bitta formaga qo'yilsa,
 * ro'yxatdan o'tish tashlab ketiladigan darajada uzun bo'lardi.
 *
 * Nega bu daraja EMAS. Bu yerdagi javob faqat boshlang'ich taxmin: keyingi
 * qadamdagi suhbat o'quvchini eshitib, haqiqiy o'lchovni o'zi chiqaradi
 * (§backend/apps/practice/placement.py). Shu bois ekran hech qanday daraja
 * e'lon qilmaydi va "sizning darajangiz" degan gap aytmaydi.
 */

const LEVELS = ['beginner', 'elementary', 'intermediate', 'advanced']

export default function Onboarding() {
  const { t } = useI18n()
  const { refreshMe } = useAuth()
  const [level, setLevel] = useState('')
  const [background, setBackground] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event) => {
    event.preventDefault()
    if (!level || busy) return
    setBusy(true)
    setError('')
    try {
      await api.onboarding({ declared_level: level, learning_background: background.trim() })
      // Profil yangilangach `App` o'zi keyingi qadamga o'tkazadi — bu ekran
      // hech qayerga navigatsiya qilmaydi, shart bitta joyda qolsin.
      await refreshMe()
    } catch (err) {
      setError(err.code === 'network_error' ? t('error.network') : t('onboarding.error'))
      setBusy(false)
    }
  }

  return (
    <div className="onboarding">
      <header className="onboarding__head">
        <Steps total={2} current={2} />
        <h1>{t('onboarding.title')}</h1>
      </header>

      {error && <Banner tone="error">{error}</Banner>}

      <form onSubmit={submit} className="onboarding__form">
        <fieldset className="onboarding__levels">
          <legend>{t('onboarding.level.label')}</legend>
          {LEVELS.map((key) => (
            <label
              key={key}
              className={`onboarding__level${level === key ? ' is-chosen' : ''}`}
              aria-checked={level === key}
            >
              <input
                type="radio"
                name="declared_level"
                value={key}
                checked={level === key}
                onChange={() => setLevel(key)}
              />
              <span className="onboarding__level-text">
                <strong>{t(`onboarding.level.${key}`)}</strong>
                <span className="muted">{t(`onboarding.level.${key}.hint`)}</span>
              </span>
              {level === key && <Icon name="check" size={18} />}
            </label>
          ))}
        </fieldset>

        <label className="field">
          <span className="field__label">{t('onboarding.background.label')}</span>
          <textarea
            rows={4}
            maxLength={1000}
            value={background}
            onChange={(event) => setBackground(event.target.value)}
            placeholder={t('onboarding.background.placeholder')}
          />
        </label>

        <button type="submit" className="btn btn--primary" disabled={!level || busy}>
          {busy ? t('auth.busy') : t('onboarding.submit')}
        </button>
      </form>
    </div>
  )
}
