import { useEffect, useMemo, useState } from 'react'

import { api } from '../api'
import { useAuth } from '../auth/AuthContext'
import {
  EqualizerMark,
  MODE_COLOR,
  ModeEmblem,
  ProgressRing,
  StepMark,
} from '../components/Art'
import Banner from '../components/Banner'
import Icon from '../components/Icon'
import { MODES } from '../components/Shell'
import { useI18n } from '../i18n'
import { paths, useRouter } from '../router'

const DAY_MS = 86_400_000
const DEFAULT_GOAL_MINUTES = 15

/** Oxirgi 7 kun: kuniga necha daqiqa gapirilgani, bugungisi va ketma-ketlik. */
function useWeek(sessions) {
  return useMemo(() => {
    const days = Array.from({ length: 7 }, () => 0)
    const today = new Date()
    today.setHours(0, 0, 0, 0)

    ;(sessions || []).forEach((s) => {
      if (!s.started_at) return
      const day = new Date(s.started_at)
      day.setHours(0, 0, 0, 0)
      const back = Math.round((today - day) / DAY_MS)
      if (back >= 0 && back < 7) days[6 - back] += (s.duration_seconds || 0) / 60
    })

    let streak = 0
    for (let i = 6; i >= 0; i -= 1) {
      if (days[i] > 0) streak += 1
      else if (i !== 6) break
    }
    return {
      days,
      today: Math.round(days[6]),
      streak,
      sessions: (sessions || []).length,
    }
  }, [sessions])
}

export default function Home() {
  const { quota, refreshMe } = useAuth()
  const { t, contentVersion } = useI18n()
  const { navigate } = useRouter()
  const [progress, setProgress] = useState(null)
  const [sessions, setSessions] = useState(null)
  const [path, setPath] = useState(null)
  const [material, setMaterial] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [topicsData, progressData, sessionsData] = await Promise.all([
          api.topics(),
          api.progress(),
          api.sessions(),
        ])
        if (cancelled) return
        setProgress(progressData)
        setSessions(sessionsData.sessions)
        setPath(topicsData)
        refreshMe().catch(() => {})
      } catch (err) {
        if (!cancelled) setError(err.message)
      }
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contentVersion])

  const week = useWeek(sessions)
  const activeTopic = progress?.topics?.find((x) => x.topic_id === progress?.active_topic_id)
  // Yo'lda hozir ochiq turgan qadam — davom etish kartasi shundan quriladi.
  const currentStep = path?.topics?.find((x) => x.status === 'active') || path?.topics?.[0]
  const currentId = activeTopic?.topic_id || currentStep?.id

  useEffect(() => {
    if (!currentId) return undefined
    let cancelled = false
    api
      .material(currentId)
      .then((result) => !cancelled && setMaterial(result))
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [currentId, contentVersion])

  const goal = quota?.duration_seconds
    ? Math.round(quota.duration_seconds / 60)
    : DEFAULT_GOAL_MINUTES
  const example = material?.examples?.[0]
  const title = material?.title || currentStep?.title || activeTopic?.title

  return (
    <div className="stack">
      {/* --- bugungi holat: maqsad halqasi va raqamlar --- */}
      <section className="today rise">
        <div className="today__goal">
          <ProgressRing value={week.today / goal}>
            <div className="ring__value">{week.today}</div>
            <div className="ring__unit">/{goal}</div>
          </ProgressRing>
          <div>
            <div className="today__title">{t('home.goal.title')}</div>
            <p className="muted" style={{ fontSize: 13.5 }}>
              {week.today >= goal ? t('home.goal.done') : t('home.goal.left')}
            </p>
          </div>
        </div>

        <div className="today__stats">
          <div className="stat">
            <div className="stat__value">{week.streak}</div>
            <div className="stat__label">{t('home.streak.label')}</div>
          </div>
          <div className="stat">
            <div className="stat__value">{week.sessions}</div>
            <div className="stat__label">{t('progress.sessions')}</div>
          </div>
          <div className="stat stat--week">
            <div className="week">
              {week.days.map((m, i) => (
                <span
                  key={i}
                  className={`week__day ${m > 0 ? 'week__day--on' : ''}`}
                  style={{ '--h': `${Math.max(10, Math.min(100, (m / goal) * 100))}%` }}
                />
              ))}
            </div>
            <div className="stat__label">{t('home.week')}</div>
          </div>
        </div>
      </section>

      {error && <Banner tone="error">{error}</Banner>}

      {/* --- asosiy harakat --- */}
      {currentId && (
        <section className="continue rise rise-1">
          <div>
            <span className="eyebrow">{t('home.resume')}</span>
            <h2 className="continue__title">{title}</h2>

            {example && (
              <div className="sentence sentence--on-dark" style={{ marginTop: 14 }}>
                {example.en}
                <div className="sentence__tr">{example.tr}</div>
              </div>
            )}

            <div className="continue__meta">
              {material?.target_structure && (
                <span className="structure structure--on-dark">
                  <span className="structure__dot" />
                  {material.target_structure.replace(/_/g, ' ')}
                </span>
              )}
              <span>{t('home.sessions.count', { count: activeTopic?.sessions_count || 0 })}</span>
            </div>
          </div>

          <div className="continue__side">
            <EqualizerMark className="continue__eq" />
            <button
              type="button"
              className="btn btn--primary btn--lg"
              onClick={() =>
                navigate(paths.material(currentId))
              }
            >
              <Icon name="play" size={17} />
              {activeTopic?.sessions_count ? t('mode.continue') : t('mode.start')}
            </button>
          </div>
        </section>
      )}

      {/* --- mashq turlari --- */}
      <section className="rise rise-2">
        <div className="card__head">
          <h2>{t('home.tracks')}</h2>
        </div>
        <div className="modes">
          {MODES.map((mode) => (
            <div
              key={mode.id}
              className={`mode ${mode.ready ? 'mode--ready' : 'mode--soon'}`}
              style={{ '--mode-color': MODE_COLOR[mode.id] }}
              onClick={mode.ready ? () => navigate(mode.to()) : undefined}
              role={mode.ready ? 'button' : undefined}
              tabIndex={mode.ready ? 0 : undefined}
            >
              <div className="mode__top">
                <ModeEmblem kind={mode.id} className="mode__emblem" />
                {!mode.ready && <span className="soon">{t('mode.soon')}</span>}
              </div>
              <div className="mode__title">{t(`mode.${mode.id}`)}</div>
              <p className="mode__desc">{t(`mode.${mode.id}.desc`)}</p>
              <div className="mode__example">{t(`mode.${mode.id}.example`)}</div>
            </div>
          ))}
        </div>
      </section>

      {/* --- o'quv yo'li --- */}
      <section className="rise rise-3">
        <div className="card__head">
          <h2>{t('home.path')}</h2>
          <button type="button" className="linkbtn" onClick={() => navigate(paths.topics())}>
            {t('home.path.all')}
          </button>
        </div>

        {!path && (
          <>
            <div className="skeleton" />
            <div className="skeleton" />
          </>
        )}

        <ol className="path">
          {path?.topics.map((topic, i) => (
            <li className={`step step--${topic.status}`} key={topic.id}>
              <StepMark state={topic.status} index={i + 1} />
              <button
                type="button"
                className="step__body"
                disabled={topic.status === 'locked'}
                onClick={() =>
                  navigate(paths.material(topic.id))
                }
              >
                <div>
                  <div className="step__title">{topic.title}</div>
                  {topic.title_en && <div className="title-en">{topic.title_en}</div>}
                </div>
                <div className="step__aside">
                  {topic.target_structure && (
                    <span className="structure">
                      <span className="structure__dot" />
                      {topic.target_structure.replace(/_/g, ' ')}
                    </span>
                  )}
                  {topic.accuracy != null && (
                    <span className="tag tag--done">{Math.round(topic.accuracy * 100)}%</span>
                  )}
                  {topic.status !== 'locked' && (
                    <Icon name="chevronRight" size={16} className="muted" />
                  )}
                </div>
              </button>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}
