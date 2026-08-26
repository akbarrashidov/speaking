import { useCallback, useEffect, useRef, useState } from 'react'

import Icon from '../components/Icon'
import { useI18n } from '../i18n'

/**
 * Shadowing sahnasi: etalonni eshitasiz → takrorlaysiz → baho olasiz.
 *
 * Etalon ikki xil bo'ladi va ikkalasi ham SHU YERDA o'lchanadi:
 *   • video biriktirilgan bo'lsa — klip aynan o'z oralig'ida o'ynaydi;
 *   • biriktirilmagan bo'lsa — brauzer ovozi gapni aytadi.
 * Har ikkalasida eshittirish qancha davom etgani backendga yuboriladi, ya'ni
 * "videodagidek tezlikda" degani taxmin emas, o'lchov (§shadow.py).
 *
 * Etalon o'ynayotganda mikrofon YOPILADI — aks holda video ovozi o'quvchining
 * navbati bo'lib ketadi.
 */
// Etalon tugagach mikrofon shuncha vaqt yopiq qoladi (aks-sado dumi).
const MIC_TAIL_MS = 450

export default function ShadowStage({
  lines,
  scores,
  mediaSrc,
  mediaKind,
  mediaRef,
  onPlayed,
  onMute,
  micState,
}) {
  const { t, lang } = useI18n()
  const videoRef = useRef(null)
  const stopRef = useRef(null)
  const [idx, setIdx] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [voiceReady, setVoiceReady] = useState(true)
  // Har bosishda YouTube iframe'i qaytadan yuklanishi uchun.
  const [take, setTake] = useState(0)

  const line = lines[idx] || null
  const score = line ? scores[line.idx] : null
  const hasTimings = Boolean(line && line.start_ms != null && line.end_ms != null)
  const isYouTube = mediaKind === 'youtube' && Boolean(mediaRef)
  // Klip = video + shu gapning oralig'i. Oraliq berilmagan bo'lsa videoni
  // o'ynatib bo'lmaydi (qayerdan qayergacha ekani noma'lum) — gapni brauzer
  // ovozi aytadi, mashq esa to'xtamaydi.
  const hasClip = Boolean(mediaSrc && hasTimings)

  const finish = useCallback(
    (startedAt) => {
      setPlaying(false)
      if (line) onPlayed(line.idx, Date.now() - startedAt)
      // Mikrofon darhol ochilmaydi: dinamikdagi ovozning "dumi" va xonaning
      // aks-sadosi shu qisqa oynada tugaydi. Ochib yuborilsa, o'sha dum
      // o'quvchining navbati bo'lib ketadi.
      setTimeout(() => onMute(false), MIC_TAIL_MS)
    },
    [line, onPlayed, onMute]
  )

  /** Etalonni bir marta eshittiradi va uzunligini o'lchaydi. */
  const play = useCallback(() => {
    if (!line || playing) return
    setPlaying(true)
    onMute(true)
    const startedAt = Date.now()

    // YouTube: video YUKLAB OLINMAYDI — YouTube pleyerining o'zi kerakli
    // oraliqni o'ynatadi. Uzunlik oraliqdan aniq ma'lum, shuning uchun
    // sur'at bahosi bu yerda ham o'lchovga tayanadi.
    if (isYouTube && hasTimings) {
      const clipMs = line.end_ms - line.start_ms
      setTake((n) => n + 1)
      stopRef.current = null
      setTimeout(() => {
        setPlaying(false)
        onPlayed(line.idx, clipMs)
        setTimeout(() => onMute(false), MIC_TAIL_MS)
      }, clipMs + 400)
      return
    }

    if (hasClip && videoRef.current) {
      const video = videoRef.current
      video.currentTime = line.start_ms / 1000
      const stopAt = line.end_ms / 1000
      const watch = () => {
        if (video.currentTime >= stopAt) {
          video.pause()
          video.removeEventListener('timeupdate', watch)
          finish(startedAt)
        }
      }
      video.addEventListener('timeupdate', watch)
      stopRef.current = () => {
        video.pause()
        video.removeEventListener('timeupdate', watch)
      }
      video.play().catch(() => finish(startedAt))
      return
    }

    // Video yo'q — gapni brauzer ovozi aytadi. Bu vaqtinchalik yechim emas:
    // etalon uzunligi baribir o'lchanadi, ya'ni sur'at bahosi ishlayveradi.
    const synth = window.speechSynthesis
    if (!synth) {
      setVoiceReady(false)
      finish(startedAt)
      return
    }
    synth.cancel()
    const utter = new SpeechSynthesisUtterance(line.text)
    utter.lang = 'en-US'
    utter.rate = 1
    utter.onend = () => finish(startedAt)
    utter.onerror = () => finish(startedAt)
    stopRef.current = () => synth.cancel()
    synth.speak(utter)
  }, [line, playing, hasClip, isYouTube, hasTimings, finish, onMute, onPlayed])

  // Yangi gapga o'tilganda etalon o'zi eshittiriladi — o'quvchi tugma
  // qidirmasin, mashq oqimda bo'lsin.
  useEffect(() => {
    const timer = setTimeout(play, 400)
    return () => {
      clearTimeout(timer)
      stopRef.current?.()
      stopRef.current = null
      onMute(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx])

  // Baho kelgach keyingi gapga o'tamiz — o'quvchi natijani o'qib ulguradi.
  useEffect(() => {
    if (!score || idx >= lines.length - 1) return undefined
    const timer = setTimeout(() => setIdx((i) => Math.min(i + 1, lines.length - 1)), 3200)
    return () => clearTimeout(timer)
  }, [score, idx, lines.length])

  if (!line) return null

  // `end` sekundlarda, shuning uchun yuqoriga yaxlitlanadi: klipning oxirgi
  // so'zi kesilib qolmasin.
  const youtubeSrc = isYouTube
    ? `https://www.youtube-nocookie.com/embed/${mediaRef}?start=${Math.floor(
        (line.start_ms || 0) / 1000
      )}&end=${Math.ceil((line.end_ms || 0) / 1000)}&autoplay=${take ? 1 : 0}` +
      '&controls=0&rel=0&modestbranding=1&playsinline=1&iv_load_policy=3&fs=0'
    : ''

  const percent = (value) => `${Math.round((value || 0) * 100)}%`
  const tempoText = score ? t(`shadow.tempo.${score.tempo_label}`) : ''

  return (
    <aside className="stage stage--shadow">
      <div className="shadow__head">
        <span className="eyebrow">{t('shadow.line', { n: idx + 1, total: lines.length })}</span>
        <span className={`shadow__mic ${micState === 'listening' ? 'is-on' : ''}`}>
          <Icon name="mic" size={14} />
          {playing ? t('shadow.listening') : t('shadow.yourturn')}
        </span>
      </div>

      {isYouTube ? (
        <iframe
          key={`${line.idx}-${take}`}
          className="shadow__video"
          src={youtubeSrc}
          title="shadowing"
          allow="autoplay; encrypted-media"
          frameBorder="0"
        />
      ) : mediaSrc ? (
        <video
          ref={videoRef}
          className="shadow__video"
          src={mediaSrc}
          playsInline
          preload="auto"
        />
      ) : (
        <div className={`shadow__wave ${playing ? 'is-playing' : ''}`} aria-hidden="true">
          <span />
          <span />
          <span />
          <span />
          <span />
        </div>
      )}

      <p className="shadow__text">{line.text}</p>

      <div className="shadow__controls">
        <button type="button" className="btn btn--ghost" onClick={play} disabled={playing}>
          <Icon name="play" size={15} />
          {t('shadow.again')}
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => setIdx((i) => Math.min(i + 1, lines.length - 1))}
          disabled={idx >= lines.length - 1}
        >
          {t('shadow.next')}
          <Icon name="chevronRight" size={15} />
        </button>
      </div>

      {!voiceReady && <p className="muted shadow__hint">{t('shadow.novoice')}</p>}

      {score && (
        <div className={`shadowcard shadowcard--${score.score >= 75 ? 'ok' : 'work'}`}>
          <div className="shadowcard__score">
            <span className="shadowcard__value">{score.score}</span>
            <span className="shadowcard__unit">/100</span>
          </div>
          <div className="shadowcard__bars">
            <div className="shadowbar">
              <span className="shadowbar__label">{t('shadow.words')}</span>
              <span className="shadowbar__track">
                <span
                  className="shadowbar__fill"
                  style={{ width: percent(score.word_accuracy) }}
                />
              </span>
              <span className="shadowbar__num">{percent(score.word_accuracy)}</span>
            </div>
            <div className="shadowbar">
              <span className="shadowbar__label">{t('shadow.tempo')}</span>
              <span className="shadowbar__track">
                <span
                  className={`shadowbar__fill shadowbar__fill--${score.tempo_label}`}
                  style={{ width: `${Math.min(100, (score.tempo || 0) * 60)}%` }}
                />
              </span>
              <span className="shadowbar__num">{tempoText}</span>
            </div>
          </div>
          {score.note && <p className="shadowcard__note">{score.note}</p>}
          {score.missed?.length > 0 && (
            <p className="shadowcard__missed">
              {t('shadow.missed')}: <b>{score.missed.slice(0, 4).join(', ')}</b>
            </p>
          )}
          {score.heard && (
            <p className="shadowcard__heard" lang={lang}>
              {t('shadow.heard')}: “{score.heard}”
            </p>
          )}
        </div>
      )}
    </aside>
  )
}
