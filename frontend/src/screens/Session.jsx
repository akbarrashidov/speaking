import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { EmptyChatArt } from '../components/Art'
import Banner from '../components/Banner'
import Icon from '../components/Icon'
import Transcript from '../components/Transcript'
import VoiceOrb from '../components/VoiceOrb'
import { useI18n } from '../i18n'
import { paths, useRouter } from '../router'
import SceneStage from '../session/SceneStage'
import ShadowStage from '../session/ShadowStage'
import { useSession } from '../session/useSession'

const STATE_KEY = {
  listening: 'session.listening',
  ai_speaking: 'session.ai',
  evaluating: 'session.evaluating',
  idle: 'session.idle',
}

function formatTime(seconds) {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

/**
 * Jonli suhbat oynasi. Pastga o'zi suriladi, lekin foydalanuvchi yuqoriga
 * qarab o'qiyotgan bo'lsa — tinch qo'yadi.
 */
function LiveTranscript({ items, partial, corrections, translations }) {
  const { t } = useI18n()
  const boxRef = useRef(null)
  const pinnedRef = useRef(true)

  const onScroll = () => {
    const box = boxRef.current
    if (!box) return
    pinnedRef.current = box.scrollHeight - box.scrollTop - box.clientHeight < 48
  }

  useLayoutEffect(() => {
    const box = boxRef.current
    if (box && pinnedRef.current) box.scrollTop = box.scrollHeight
  }, [items, partial, corrections, translations])

  return (
    <div className="chat" ref={boxRef} onScroll={onScroll} aria-live="polite">
      {items.length === 0 && !partial && (
        <div className="chat__empty">
          <EmptyChatArt />
          <p>{t('session.empty')}</p>
        </div>
      )}
      <Transcript
        items={items}
        partial={partial}
        corrections={corrections}
        translations={translations}
      />
    </div>
  )
}

export default function Session({ session, topicTitle, targetStructure }) {
  const { t } = useI18n()
  const { navigate } = useRouter()
  const startedRef = useRef(false)
  const [ending, setEnding] = useState(false)

  const goToFeedback = () => navigate(paths.feedback(session.session_id), { replace: true })

  const {
    status,
    micState,
    level,
    remaining,
    progress,
    transcript,
    partial,
    translations,
    corrections,
    error,
    hint,
    options,
    start,
    stop,
    scene,
    lines,
    shadowScores,
    markShadowLine,
    muteMic,
  } = useSession({
    sessionId: session.session_id,
    wsPath: new URL(session.ws_url, window.location.origin).pathname,
    timeLimit: session.time_limit_s,
    onEnded: goToFeedback,
  })

  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    start().catch((err) => console.error('Sessiya boshlanmadi:', err))
  }, [start])

  const finish = async () => {
    setEnding(true)
    await stop(true)
    goToFeedback()
  }

  const stateText =
    status === 'reconnecting'
      ? t('session.reconnecting')
      : status === 'connecting'
        ? t('session.connecting')
        : t(STATE_KEY[micState] || 'session.idle')

  const track = scene?.track || 'grammar'
  const timerEl = (
    <div className={`timer ${remaining <= 30 ? 'timer--low' : ''}`}>{formatTime(remaining)}</div>
  )
  const stateEl = (
    <div className="state">
      <span className="state__dot" />
      {stateText}
    </div>
  )
  const errorEl = status === 'error' && (
    <Banner tone="error">
      {error === 'gemini_lost' || error === 'gemini_unavailable'
        ? t('session.lost')
        : t('session.dropped')}
    </Banner>
  )

  return (
    <div className="session" data-state={micState} data-track={track}>
      {/* --- o'lchov qatori: bosh sahifadagi "bugungi holat" bilan bir xil qatlam --- */}
      <header className="session__top">
        <div className="session__id">
          <span className="eyebrow">{t(`mode.${track}`)}</span>
          <div className="session__topic">{topicTitle}</div>
        </div>

        {targetStructure && (
          <span className="structure">
            <span className="structure__dot" />
            {targetStructure.replace(/_/g, ' ')}
          </span>
        )}

        <div className="session__stats">
          <div className="stat">
            <div className="stat__value">{progress.correct}</div>
            <div className="stat__label">{t('session.correct')}</div>
          </div>
          <div className="stat">
            <div className="stat__value">{progress.asked}</div>
            <div className="stat__label">{t('session.spoken')}</div>
          </div>
        </div>

        <button type="button" className="btn btn--danger" onClick={finish} disabled={ending}>
          <Icon name="stop" size={16} />
          {ending ? t('session.finishing') : t('session.finish')}
        </button>
      </header>

      <div className="session__body">
        {/* --- asosiy blok: sahifadagi yagona to'q rangli maydon --- */}
        {track === 'shadowing' && lines.length > 0 ? (
          <ShadowStage
            lines={lines}
            scores={shadowScores}
            mediaSrc={scene?.mediaSrc || ''}
            mediaKind={scene?.mediaKind || ''}
            mediaRef={scene?.mediaRef || ''}
            onPlayed={markShadowLine}
            onMute={muteMic}
            micState={micState}
          />
        ) : track === 'roleplay' ? (
          <SceneStage scene={scene} micState={micState} level={level} timer={timerEl}>
            {stateEl}
            {errorEl}
          </SceneStage>
        ) : (
        <aside className="stage">
          <VoiceOrb level={micState === 'listening' ? level : 0.08} state={micState} />

          {timerEl}
          {stateEl}

          {hint && (
            <div className="prompts">
              <span className="prompts__label">{t(`hint.${hint.kind || 'opener'}`)}</span>
              {hint.text && <p style={{ marginTop: 6 }}>{hint.text}</p>}
            </div>
          )}

          {options.length > 0 && (
            <div className="prompts">
              <span className="prompts__label">{t('session.options')}</span>
              <ul className="prompts__list">
                {options.map((option) => (
                  <li key={option.en}>
                    <p className="prompts__en">{option.en}</p>
                    {option.uz && <p className="prompts__tr">{option.uz}</p>}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {errorEl}
        </aside>
        )}

        <LiveTranscript
          items={transcript}
          partial={partial}
          corrections={corrections}
          translations={translations}
        />
      </div>
    </div>
  )
}
