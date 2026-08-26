import { useState } from 'react'

import Banner from '../components/Banner'
import { EqualizerMark } from '../components/Art'
import Icon from '../components/Icon'
import { api } from '../api'
import { prepareAudio, releaseAudio } from '../audio/bootstrap'
import { useAuth } from '../auth/AuthContext'
import { useI18n } from '../i18n'
import { paths, useRouter } from '../router'

/**
 * Birinchi suhbat — daraja aniqlanadigan joy.
 *
 * Ekran nima QILMAYDI: darajani so'ramaydi, ballni ko'rsatmaydi va "test"
 * so'zini ishlatmaydi. O'quvchi buni imtihon deb bilsa, o'zini ko'rsatishga
 * urinadi va o'lchov buziladi — model ham buni aytmasligi kerak
 * (§backend/prompts/modes/placement.md).
 *
 * Nima QILADI: mikrofon ruxsatini AYNAN bosish ichida ochadi (iOS Safari
 * boshqa yo'lni rad etadi), so'ng sessiyani boshlab, sessiya ekraniga o'tadi.
 */
export default function Placement() {
  const { t } = useI18n()
  const { refreshMe } = useAuth()
  const { navigate } = useRouter()
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')

  const insecure = typeof window !== 'undefined' && !window.isSecureContext

  const start = async () => {
    setStarting(true)
    setError('')
    try {
      await prepareAudio()
      const session = await api.startPlacement()
      refreshMe().catch(() => {})
      navigate(paths.session(session.session_id), {
        state: { session, topicTitle: t('placement.title') },
      })
    } catch (err) {
      releaseAudio()
      setStarting(false)
      if (err.name === 'NotAllowedError') setError(t('error.mic.denied'))
      else if (err.name === 'NotFoundError') setError(t('error.mic.missing'))
      else if (err.code === 'quota_exceeded') setError(t('error.quota'))
      else if (err.code === 'cost_cap_reached') setError(t('error.cost'))
      else if (err.code === 'placement_unavailable') setError(t('placement.unavailable'))
      else setError(err.message || t('error.session.start'))
    }
  }

  return (
    <div className="placement">
      <header className="placement__head">
        <p className="onboarding__step">{t('placement.step')}</p>
        <h1>{t('placement.title')}</h1>
        <p className="muted" style={{ maxWidth: '54ch' }}>
          {t('placement.lede')}
        </p>
      </header>

      <ul className="placement__points">
        <li>
          <span>
            <Icon name="mic" size={17} />
          </span>
          {t('placement.point.talk')}
        </li>
        <li>
          <span>
            <Icon name="check" size={17} />
          </span>
          {t('placement.point.nofix')}
        </li>
        <li>
          <span>
            <Icon name="progress" size={17} />
          </span>
          {t('placement.point.start')}
        </li>
      </ul>

      {insecure && <Banner tone="warn">{t('material.insecure')}</Banner>}
      {error && <Banner tone="error">{error}</Banner>}

      <button
        type="button"
        className="btn btn--primary btn--lg"
        onClick={start}
        disabled={starting || insecure}
      >
        {starting ? t('placement.starting') : t('placement.start')}
      </button>

      <EqualizerMark className="placement__eq" />
    </div>
  )
}
