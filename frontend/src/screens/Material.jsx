import { useEffect, useState } from 'react'

import { api } from '../api'
import { prepareAudio, releaseAudio } from '../audio/bootstrap'
import { useAuth } from '../auth/AuthContext'
import { MicMark } from '../components/Art'
import Banner from '../components/Banner'
import Icon from '../components/Icon'
import { BackLink } from '../components/Shell'
import { useI18n } from '../i18n'
import { paths, useRouter } from '../router'

// Yo'nalish → yon paneldagi rejim nomi. Bog'lam kartasida "Grammatika" yoki
// "Iboralar" deb turadi, ya'ni o'quvchi qayerga o'tishini oldindan biladi.
const TRACK_MODE = {
  grammar: 'grammar',
  phrases: 'phrases',
  shadowing: 'shadowing',
  roleplay: 'roleplay',
}

export default function Material({ topicId }) {
  const { t, contentVersion } = useI18n()
  const { navigate } = useRouter()
  const { refreshMe } = useAuth()
  const [material, setMaterial] = useState(null)
  const [error, setError] = useState('')
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    let cancelled = false
    api
      .material(topicId)
      .then((result) => !cancelled && setMaterial(result))
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
    // Til almashsa qoida, misollar va iboralar yangi tilda qayta tortiladi.
  }, [topicId, contentVersion])

  // MUHIM: mikrofon ruxsati va audio playback aynan SHU bosish ichida ochiladi.
  // Brauzerlar (ayniqsa iOS Safari) buni foydalanuvchi imo-ishorasidan tashqarida
  // ruxsat etmaydi.
  const startSession = async () => {
    setStarting(true)
    setError('')
    try {
      await prepareAudio()
      const session = await api.startSession(topicId)
      refreshMe().catch(() => {})
      navigate(paths.session(session.session_id), {
        state: {
          session,
          topicTitle: material?.title,
          targetStructure: material?.target_structure,
        },
      })
    } catch (err) {
      releaseAudio()
      setStarting(false)
      if (err.name === 'NotAllowedError') setError(t('error.mic.denied'))
      else if (err.name === 'NotFoundError') setError(t('error.mic.missing'))
      else if (err.code === 'quota_exceeded') setError(t('error.quota'))
      else if (err.code === 'cost_cap_reached') setError(t('error.cost'))
      else if (err.code === 'topic_locked') setError(t('error.topic.locked'))
      else setError(err.message || t('error.session.start'))
    }
  }

  const insecure = typeof window !== 'undefined' && !window.isSecureContext

  if (error && !material) return <Banner tone="error">{error}</Banner>
  if (!material) {
    return (
      <div>
        <div className="skeleton" />
        <div className="skeleton" />
      </div>
    )
  }

  // To'rt yo'nalish uchun BITTA sahifa. Bloklar bir xil joyda turadi —
  // faqat sarlavhalar yo'nalishga qarab o'zgaradi, chunki "Qoida" iborada
  // "Qanday tuziladi", shadowingda esa "Qanday mashq qilinadi" degani.
  const track = material.track || 'grammar'
  const copy =
    {
      grammar: {
        back: ['topics.back', paths.topics()],
        first: 'home.structure',
        rule: 'material.rule',
        examples: 'material.examples',
      },
      phrases: {
        back: ['phrases.back', paths.phrases()],
        first: 'phrases.say',
        rule: 'phrases.form',
        usage: 'phrases.usage',
        examples: 'material.examples',
      },
      shadowing: {
        back: ['shadowing.back', paths.shadowing()],
        first: 'shadowing.first',
        rule: 'shadowing.how',
        usage: 'shadowing.listen',
        examples: 'shadowing.lines',
      },
      roleplay: {
        back: ['roleplay.back', paths.roleplay()],
        first: 'roleplay.first',
        rule: 'roleplay.roles',
        usage: 'roleplay.scene',
        examples: 'material.examples',
      },
    }[track] || {}

  return (
    <div className="stack page--narrow" style={{ margin: 0 }}>
      <header className="rise">
        <BackLink to={copy.back[1]}>{t(copy.back[0])}</BackLink>
        <h1>{material.title}</h1>
        {material.focus_phrase && <p className="phrase__badge">{material.focus_phrase}</p>}
      </header>

      {/* Shadowing videosi — mashqdan oldin ko'rib olish uchun. Video
          biriktirilmagan bo'lsa blok umuman chizilmaydi. */}
      {material.media_src && (
        <section className="rise rise-1">
          <div className="card__head">
            <h2>{t('shadow.video')}</h2>
          </div>
          {material.media_kind === 'youtube' ? (
            <iframe
              className="material__video"
              src={`https://www.youtube-nocookie.com/embed/${material.media_ref}?rel=0&modestbranding=1`}
              title={material.title}
              allow="encrypted-media"
              allowFullScreen
              frameBorder="0"
            />
          ) : (
            <video className="material__video" src={material.media_src} controls playsInline />
          )}
        </section>
      )}

      {material.examples?.[0] && (
        <section className="rise rise-1">
          <div className="card__head">
            <h2>{t(copy.first)}</h2>
          </div>
          <div className="card">
            <div className="sentence">
              {material.examples[0].en}
              <div className="sentence__tr">{material.examples[0].tr}</div>
            </div>
          </div>
        </section>
      )}

      {/* Shakl to'g'ri bo'lsa ham, noto'g'ri joyda aytilgan ibora g'alati
          eshitiladi — shuning uchun bu blok qoidadan OLDIN turadi. */}
      {material.usage && copy.usage && (
        <section className="rise rise-2">
          <div className="card__head">
            <h2>{t(copy.usage)}</h2>
          </div>
          <div className="card">
            <p>{material.usage}</p>
          </div>
        </section>
      )}

      {/* Sarlavha blokdan TASHQARIDA — "Misollar" va "Foydali iboralar"
          bilan bir xil naqsh: nima kelayotgani karta ochilmasdan oldin
          o'qiladi. */}
      <section className="rise rise-2">
        <div className="card__head">
          <h2>{t(copy.rule)}</h2>
        </div>
        <div className="card">
          <p>{material.rule}</p>
        </div>
      </section>

      {/* Nimaga tayanadi: shadowing matni ham grammatikadan, ham iboradan
          foydalanadi — ikkalasi ham bosiladigan havola. */}
      {material.related?.length > 0 && (
        <section className="rise rise-3">
          <div className="card__head">
            <h2>{t('related.title')}</h2>
          </div>
          <div className="stack stack--tight">
            {material.related.map((item) => (
              <button
                key={item.topic_id}
                type="button"
                className="card card--link"
                onClick={() => navigate(paths.material(item.topic_id))}
              >
                <span>
                  <span className="card__linkkind">{t(`mode.${TRACK_MODE[item.track]}`)}</span>
                  <span className="card__linktext">{item.focus_phrase || item.title}</span>
                </span>
                <span className="card__linkgo">
                  {t('related.go')}
                  <Icon name="chevronRight" size={15} />
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="rise rise-3">
        <div className="card__head">
          <h2>{t(copy.examples)}</h2>
        </div>
        <div className="card pairs">
          {material.examples?.slice(1).map((example, i) => (
            <div className="pair" key={i}>
              <span className="pair__en">{example.en}</span>
              <span className="pair__tr">{example.tr}</span>
            </div>
          ))}
        </div>
      </section>

      {material.chunks?.length > 0 && (
        <section className="rise rise-4">
          <div className="card__head">
            <h2>{t('material.chunks')}</h2>
          </div>
          <div className="card pairs">
            {material.chunks.map((chunk, i) => (
              <div className="pair" key={i}>
                <span className="pair__en">{chunk.text}</span>
                <span className="pair__tr">{chunk.translation}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="continue rise rise-4">
        <div>
          <span className="eyebrow">{t('material.talk')}</span>
          <p style={{ margin: '10px 0 18px', maxWidth: '52ch' }}>{t('material.lede')}</p>

          {insecure && <Banner tone="warn">{t('material.insecure')}</Banner>}
          {error && <Banner tone="error">{error}</Banner>}

          <button
            type="button"
            className="btn btn--primary btn--lg"
            onClick={startSession}
            disabled={starting || insecure}
          >
            <Icon name={starting ? 'mic' : 'play'} size={18} />
            {starting ? t('material.starting') : t('material.start')}
          </button>
        </div>

        <MicMark className="continue__mic" />
      </section>
    </div>
  )
}
