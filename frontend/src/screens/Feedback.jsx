import { useEffect, useRef, useState } from 'react'

import { api } from '../api'
import { useAuth } from '../auth/AuthContext'
import { ProgressRing } from '../components/Art'
import Banner from '../components/Banner'
import Icon from '../components/Icon'
import Transcript from '../components/Transcript'
import { useI18n } from '../i18n'
import { paths, useRouter } from '../router'

const POLL_MS = 2500
const MAX_POLLS = 40 // ~100 soniya

export default function Feedback({ sessionId }) {
  const { t, contentVersion } = useI18n()
  const { navigate } = useRouter()
  const { refreshMe } = useAuth()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const pollsRef = useRef(0)

  useEffect(() => {
    let cancelled = false
    let timer = null

    const poll = async () => {
      try {
        const result = await api.feedback(sessionId)
        if (cancelled) return
        if (result.status === 'ready' || result.status === 'failed') {
          setData(result)
          refreshMe().catch(() => {})
          return
        }
        pollsRef.current += 1
        if (pollsRef.current > MAX_POLLS) {
          setError(t('feedback.slow'))
          return
        }
        timer = setTimeout(poll, POLL_MS)
      } catch (err) {
        if (!cancelled) setError(err.message)
      }
    }

    pollsRef.current = 0
    poll()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, contentVersion])

  if (error) {
    return (
      <div className="center">
        <Banner tone="error">{error}</Banner>
        <button type="button" className="btn btn--primary" onClick={() => navigate(paths.home())}>
          {t('nav.home')}
        </button>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="stack">
        <header>
          <h1>{t('feedback.waiting')}</h1>
          <p className="muted" style={{ marginTop: 6 }}>
            {t('feedback.waiting.hint')}
          </p>
        </header>
        <div>
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton" />
        </div>
      </div>
    )
  }

  if (data.status === 'failed') {
    return (
      <div className="center">
        <h1>{t('feedback.failed')}</h1>
        <p className="muted">{t('feedback.failed.hint')}</p>
        <button type="button" className="btn btn--primary" onClick={() => navigate(paths.home())}>
          {t('nav.home')}
        </button>
      </div>
    )
  }

  const m = data.metrics
  const accuracy = m.first_attempt_accuracy / 100

  return (
    <div className="stack">
      {/* --- o'lchov paneli: bosh sahifadagi "bugungi holat" bilan bir xil qatlam --- */}
      <section className="today rise">
        <div className="today__goal">
          <ProgressRing value={accuracy}>
            <div className="ring__value">{m.first_attempt_accuracy}</div>
            <div className="ring__unit">%</div>
          </ProgressRing>
          <div>
            <div className="today__title">{t('feedback.title')}</div>
            <p className="muted" style={{ fontSize: 13.5 }}>
              {data.topic.title} ·{' '}
              {t('feedback.accuracy', {
                correct: m.first_attempt_correct,
                total: m.questions_total,
              })}
            </p>
          </div>
        </div>

        <div className="today__stats">
          <div className="stat">
            <div className="stat__value">{Math.round(data.duration_seconds / 60)}</div>
            <div className="stat__label">{t('feedback.minutes')}</div>
          </div>
          <div className="stat">
            <div className="stat__value">{m.talk_time_pct}%</div>
            <div className="stat__label">{t('feedback.talktime')}</div>
          </div>
          <div className="stat">
            <div className="stat__value">{m.wpm}</div>
            <div className="stat__label">{t('feedback.wpm')}</div>
          </div>
        </div>
      </section>

      {/* --- asosiy blok: xulosa va keyingi qadam --- */}
      <section className="continue rise rise-1">
        <div>
          <span className="eyebrow">{t('feedback.summary')}</span>
          <p className="continue__summary">
            {data.summary_uz || t('feedback.waiting.hint')}
          </p>
          {m.avg_response_latency_ms > 0 && (
            <div className="continue__meta">
              <span>
                {t('feedback.latency', {
                  seconds: (m.avg_response_latency_ms / 1000).toFixed(1),
                })}
              </span>
              {m.filler_count > 0 && <span>{t('feedback.fillers', { count: m.filler_count })}</span>}
            </div>
          )}
        </div>

        <button
          type="button"
          className="btn btn--white btn--lg"
          onClick={() => navigate(paths.home())}
        >
          {data.next_action === 'next_topic' ? t('feedback.next') : t('feedback.again')}
        </button>
      </section>

      {/* --- tuzatishlar: aytilgan gap → to'g'ri shakli --- */}
      {data.errors?.length > 0 && (
        <section className="rise rise-2">
          <div className="card__head">
            <h2>{t('feedback.fixes')}</h2>
            <span className="tag">{data.errors.length}</span>
          </div>
          <ol className="path">
            {data.errors.map((err, i) => (
              <li className="step" key={i}>
                <span className="step__mark step__mark--fix">{i + 1}</span>
                <div className="step__body step__body--static">
                  <div>
                    <span className="fix__wrong">{err.utterance}</span>
                    <span className="fix__right">{err.correction}</span>
                  </div>
                  {err.error_type && (
                    <span className="structure">
                      <span className="structure__dot" />
                      {String(err.error_type).replace(/_/g, ' ')}
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}

      {/* --- takrorlangan xatolar --- */}
      {data.patterns?.length > 0 && (
        <section className="rise rise-3">
          <div className="card__head">
            <h2>{t('feedback.patterns')}</h2>
          </div>
          <div className="grid">
            {data.patterns.map((p, i) => (
              <div className="card" key={i}>
                <div className="card__head" style={{ marginBottom: 10 }}>
                  <span className="structure">
                    <span className="structure__dot" />
                    {String(p.type || '').replace(/_/g, ' ')}
                  </span>
                  <span className="tag">{p.count}×</span>
                </div>
                {p.explain_uz && <p style={{ fontSize: 14 }}>{p.explain_uz}</p>}
                {p.example && (
                  <div style={{ marginTop: 10 }}>
                    <span className="fix__wrong">{p.example}</span>
                    <span className="fix__right">{p.fix}</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* --- keyingi safar mashq qilinadigan gaplar --- */}
      {data.next_drills?.length > 0 && (
        <section className="rise rise-4">
          <div className="card__head">
            <h2>{t('feedback.drills')}</h2>
          </div>
          <div className="card pairs">
            {data.next_drills.map((line, i) => (
              <div className="pair" key={i}>
                <span className="sentence" style={{ fontSize: 17 }}>
                  {line}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {data.strengths_uz?.length > 0 && (
        <section>
          <div className="card__head">
            <h2>{t('feedback.strengths')}</h2>
          </div>
          <div className="card">
            {data.strengths_uz.map((line, i) => (
              <p key={i} style={{ display: 'flex', gap: 10, marginTop: i ? 10 : 0 }}>
                <Icon
                  name="check"
                  size={17}
                  style={{ color: 'var(--green)', flex: '0 0 auto', marginTop: 3 }}
                />
                {line}
              </p>
            ))}
          </div>
        </section>
      )}

      {data.transcript?.length > 0 && (
        <details className="card card--flush">
          <summary className="disclosure">
            <Icon name="speech" size={17} className="muted" />
            <span style={{ fontWeight: 600 }}>{t('feedback.transcript')}</span>
            <span className="muted" style={{ fontSize: 13 }}>
              {t('feedback.transcript.count', { count: data.transcript.length })}
            </span>
          </summary>
          <div style={{ padding: '0 22px 22px' }}>
            <Transcript items={data.transcript} />
          </div>
        </details>
      )}

      {data.struggling_hint && <Banner tone="warn">{data.struggling_hint.message}</Banner>}


      <div className="btnrow">
        <button type="button" className="btn btn--ghost" onClick={() => navigate(paths.progress())}>
          <Icon name="progress" size={17} />
          {t('progress.title')}
        </button>
      </div>
    </div>
  )
}
