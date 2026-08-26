import { useEffect, useState } from 'react'

import { api } from '../api'
import { EmptyListArt, ProgressRing, StepMark } from '../components/Art'
import Banner from '../components/Banner'
import Icon from '../components/Icon'
import { useI18n } from '../i18n'
import { paths, useRouter } from '../router'

export default function Progress() {
  const { t, lang, contentVersion } = useI18n()
  const { navigate } = useRouter()
  const [data, setData] = useState(null)
  const [sessions, setSessions] = useState([])
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [progressData, sessionsData] = await Promise.all([api.progress(), api.sessions()])
        if (cancelled) return
        setData(progressData)
        setSessions(sessionsData.sessions || [])
      } catch (err) {
        if (!cancelled) setError(err.message)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [contentVersion])

  // Sana raqamlarda: `uz-UZ` qisqa oy nomini "M08" qilib beradi, ya'ni
  // o'quvchiga hech narsa demaydi. Raqamli shakl ikkala tilda ham tushunarli.
  const formatWhen = (iso) => {
    if (!iso) return ''
    return new Date(iso).toLocaleString(lang === 'ru' ? 'ru-RU' : 'uz-UZ', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  if (error) return <Banner tone="error">{error}</Banner>
  if (!data) {
    return (
      <div>
        <div className="skeleton" />
        <div className="skeleton" />
      </div>
    )
  }

  const attempted = data.topics.filter((x) => x.sessions_count > 0)
  const mastered = data.topics.filter((x) => x.status === 'mastered').length
  const totalSessions = data.topics.reduce((sum, x) => sum + x.sessions_count, 0)
  const avgAccuracy = attempted.length
    ? Math.round(
        (attempted.reduce((sum, x) => sum + (x.last_accuracy || 0), 0) / attempted.length) * 100
      )
    : 0
  const minutes = Math.round(
    sessions.reduce((sum, s) => sum + (s.duration_seconds || 0), 0) / 60
  )

  return (
    <div className="stack">
      <header className="rise">
        <h1>{t('progress.title')}</h1>
      </header>

      {/* --- o'lchov paneli: bosh sahifa bilan bir xil qatlam --- */}
      <section className="today rise">
        <div className="today__goal">
          <ProgressRing value={avgAccuracy / 100}>
            <div className="ring__value">{avgAccuracy}</div>
            <div className="ring__unit">%</div>
          </ProgressRing>
          <div>
            <div className="today__title">{t('progress.avg')}</div>
            <p className="muted" style={{ fontSize: 13.5 }}>
              {t('progress.lede')}
            </p>
          </div>
        </div>

        <div className="today__stats">
          <div className="stat">
            <div className="stat__value">{totalSessions}</div>
            <div className="stat__label">{t('progress.sessions')}</div>
          </div>
          <div className="stat">
            <div className="stat__value">{minutes}</div>
            <div className="stat__label">{t('feedback.minutes')}</div>
          </div>
          <div className="stat">
            <div className="stat__value">{mastered}</div>
            <div className="stat__label">{t('progress.mastered')}</div>
          </div>
          <div className="stat">
            <div className="stat__value">{data.open_errors}</div>
            <div className="stat__label">{t('progress.openerrors')}</div>
          </div>
        </div>
      </section>

      {/* --- o'tilgan mavzular: bosh sahifadagi yo'l bilan bir xil ko'rinish --- */}
      <section className="rise rise-1">
        <div className="card__head">
          <h2>{t('progress.topics')}</h2>
        </div>

        {data.topics.length === 0 && (
          <div className="empty">
            <EmptyListArt />
            <p>{t('progress.empty')}</p>
          </div>
        )}

        <ol className="path">
          {data.topics.map((topic, i) => (
            <li className={`step step--${topic.status}`} key={topic.topic_id}>
              <StepMark state={topic.status} index={i + 1} />
              <div className="step__body step__body--static">
                <div>
                  <div className="step__title">{topic.title}</div>
                  <div className="title-en">
                    {t('home.sessions.count', { count: topic.sessions_count })}
                  </div>
                </div>
                <div className="step__aside">
                  {topic.best_accuracy != null && (
                    <span className="muted" style={{ fontSize: 12.5 }}>
                      {t('progress.best', { percent: Math.round(topic.best_accuracy * 100) })}
                    </span>
                  )}
                  {topic.last_accuracy != null && (
                    <span className={`tag ${topic.status === 'mastered' ? 'tag--done' : ''}`}>
                      {Math.round(topic.last_accuracy * 100)}%
                    </span>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* --- suhbatlar tarixi --- */}
      {sessions.length > 0 && (
        <section className="rise rise-2">
          <div className="card__head">
            <h2>{t('progress.history')}</h2>
          </div>
          <div className="card card--flush">
            {sessions.map((s) => (
              <button
                type="button"
                key={s.session_id}
                className="row"
                onClick={() => navigate(paths.feedback(s.session_id))}
              >
                <span>
                  <span className="row__title">{s.title}</span>
                  <span className="muted" style={{ fontSize: 12.5 }}>
                    {formatWhen(s.started_at)}
                  </span>
                </span>
                {s.accuracy != null && <span className="tag">{s.accuracy}%</span>}
                <Icon name="chevronRight" size={16} className="muted" />
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
