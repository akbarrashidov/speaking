import { useEffect, useState } from 'react'

import { api } from '../api'
import { EmptyListArt, StepMark } from '../components/Art'
import Banner from '../components/Banner'
import Icon from '../components/Icon'
import { BackLink } from '../components/Shell'
import { useI18n } from '../i18n'
import { paths, useRouter } from '../router'

/**
 * Yo'nalish ro'yxati — to'rttasi uchun bitta ekran.
 *
 * Ro'yxatlar bir xil ishlaydi (tartib, qulf, progress), farq faqat NIMA
 * birinchi qatorda turishida: grammatikada mavzu nomi, iborada iboraning
 * o'zi. Shu farq shu yerda, konfiguratsiyada — to'rt xil fayl emas.
 */
const TRACKS = {
  grammar: {
    title: 'topics.title',
    lede: 'topics.lede',
    empty: 'topics.empty',
    structure: true,
    questions: true,
  },
  phrases: {
    title: 'phrases.title',
    lede: 'phrases.lede',
    empty: 'phrases.empty',
    // Iborada inglizcha shakl birinchi: o'quvchi ro'yxatga qarab "bilaman /
    // bilmayman" deb darhol ajratishi kerak.
    primary: (topic) => topic.focus_phrase || topic.title_en,
    secondary: (topic) => topic.title,
    questions: true,
  },
  shadowing: {
    title: 'shadowing.title',
    lede: 'shadowing.lede',
    empty: 'shadowing.empty',
  },
  roleplay: {
    title: 'roleplay.title',
    lede: 'roleplay.lede',
    empty: 'roleplay.empty',
  },
}

export default function Track({ track }) {
  const config = TRACKS[track] || TRACKS.grammar
  const { t, contentVersion } = useI18n()
  const { navigate } = useRouter()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setData(null)
    api
      .track(track)
      .then((result) => !cancelled && setData(result))
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
    // Til almashsa nomlar serverdan yangi tilda keladi.
  }, [track, contentVersion])

  const primary = config.primary || ((topic) => topic.title)
  const secondary = config.secondary || ((topic) => topic.title_en)

  return (
    <div className="stack">
      <header className="rise">
        <BackLink to={paths.home()}>{t('nav.home')}</BackLink>
        <h1>{t(config.title)}</h1>
        <p className="muted" style={{ marginTop: 6, maxWidth: '58ch' }}>
          {t(config.lede)}
        </p>
      </header>

      {error && <Banner tone="error">{error}</Banner>}

      {!data && !error && (
        <div>
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton" />
        </div>
      )}

      <ol className="path rise rise-1">
        {data?.topics.map((topic, i) => (
          <li className={`step step--${topic.status}`} key={topic.id}>
            <StepMark state={topic.status} index={i + 1} />
            <button
              type="button"
              className="step__body"
              disabled={topic.status === 'locked'}
              onClick={() => navigate(paths.material(topic.id))}
            >
              <div>
                <div className={`step__title ${track === 'phrases' ? 'phrase__en' : ''}`}>
                  {primary(topic)}
                </div>
                {secondary(topic) && <div className="title-en">{secondary(topic)}</div>}
              </div>
              <div className="step__aside">
                {config.structure && topic.target_structure && (
                  <span className="structure">
                    <span className="structure__dot" />
                    {topic.target_structure.replace(/_/g, ' ')}
                  </span>
                )}
                {config.questions && (
                  <span className="muted" style={{ fontSize: 12.5 }}>
                    {t('topics.questions', { count: topic.questions_count })}
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

      {data?.topics.length === 0 && (
        <div className="empty">
          <EmptyListArt />
          <p>{t(config.empty)}</p>
        </div>
      )}
    </div>
  )
}
