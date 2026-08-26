import { useCallback, useEffect, useRef, useState } from 'react'

import { getToken, wsUrl } from '../api'
import { takeAudio } from '../audio/bootstrap'
import { closeAudioContext } from '../audio/context'
import { PCMPlayer } from '../audio/player'
import { MicRecorder } from '../audio/recorder'

const MAX_RECONNECTS = 3 // §8 — server grace oynasi 60 s
const BACKOFF_MS = [1000, 3000, 7000]
const VAD_THRESHOLD = 0.06
// Javobdan oldingi sof jimlik shu yerdan boshlanadi, shuning uchun har 100 ms
// bevosita seziladi — va bu KUTISHNING BOSHI: backend `speech_end` kelgunicha
// baholashni umuman boshlamaydi.
//
// Qiymat past bo'lishi mumkin, chunki gap o'rtasidagi pauzani backend ushlaydi:
// u `speech_end` dan keyin yana TURN_END_GRACE_SECONDS (0.75 s) kutadi va o'sha
// oyna ichida kelgan davomni o'sha navbatga qo'shadi. Ya'ni pauzaga chidam
// 300 + 750 ms, javob esa 100 ms tezroq boshlanadi.
const VAD_SILENCE_MS = 300
// Navbat ochish uchun ketma-ket shuncha "ovozli" chunk kerak. Bitta chunk
// (100 ms) yetarli emas edi: eshik taqillashi, stol turtilishi va klaviatura
// ham ostonadan o'tib, navbat ochib yuborardi — o'quvchi jim turgan bo'lsa
// ham AI "eshitgan" gapini tuzatib ketardi.
const MIN_OPEN_CHUNKS = 2
// Navbat baholanishi uchun kerakli eng qisqa nutq. Bundan qisqasi — shovqin,
// va u serverga umuman yuborilmaydi (`speech_cancel`).
const MIN_TURN_CHUNKS = 4
// Nutq boshlanishidan oldingi bufer: VAD ostona kechikkanda birinchi so'z
// kesilib qolmasligi uchun. 6 × 100 ms chunk = 600 ms — barge-in tasdiqlash
// oynasini ham qoplaydi.
const PREFIX_CHUNKS = 6

// --- Echo himoyasi ---------------------------------------------------------
// AI dinamikdan gapirganda ovozi mikrofonga qaytadi. Uni o'quvchining nutqi
// deb hisoblash halqa hosil qiladi: AI o'z ovozini Gemini'ga qaytarib yuboradi,
// o'zini bo'ladi va transkriptda AI gapi o'quvchi navbati bo'lib chiqadi.
// Brauzer AEC'i ko'p qurilmada echo'ni to'liq o'chira olmaydi, shuning uchun
// AI gapirayotgan paytda VAD uch qavat qattiqlashadi:
//   1) ostona ko'tariladi (BARGE_IN_THRESHOLD),
//   2) mikrofon signali playback darajasidan ECHO_MARGIN barobar baland
//      bo'lishi shart — sekin gapirayotgan AI ostida ham ishlaydi,
//   3) bitta cho'qqi yetmaydi, BARGE_IN_HOLD chunk uzluksiz talab qilinadi.
const BARGE_IN_THRESHOLD = 0.18
const ECHO_MARGIN = 1.8
const BARGE_IN_HOLD = 3 // 300 ms
const ECHO_TAIL_MS = 300 // audio tugagach echo shuncha davom etadi

/**
 * Sessiya WebSocket'i + audio I/O. Bitta joyda: ulanish, reconnect, mikrofon,
 * playback va UI holati.
 */
export function useSession({ sessionId, wsPath, timeLimit, onEnded }) {
  const [status, setStatus] = useState('connecting') // connecting|live|reconnecting|ended|error
  const [micState, setMicState] = useState('idle') // idle|listening|ai_speaking|evaluating
  const [level, setLevel] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const [progress, setProgress] = useState({ asked: 0, total: 0, correct: 0 })
  const [error, setError] = useState(null)
  // Mikrofon chunklarining necha foizi haqiqatan yuborilgani (100 = darvoza yo'q).
  const [micDuty, setMicDuty] = useState(100)
  // Joriy podkaska (o'quvchi qotib qolganda) — gapirsa yo'qoladi.
  const [hint, setHint] = useState(null)
  // Yakunlangan gaplar + hozir yozilayotgan (tugallanmagan) gap.
  const [transcript, setTranscript] = useState([])
  const [partial, setPartial] = useState(null) // {speaker, text} | null
  // AI gaplarining o'zbekchasi, navbat raqami bo'yicha: {[idx]: "..."}.
  // Ovozdan ~1 s keyin keladi, shuning uchun matndan alohida saqlanadi.
  const [translations, setTranslations] = useState({})
  // Jim qolganda ekranga chiqadigan tayyor javoblar: [{en, uz}].
  const [options, setOptions] = useState([])
  // Grammatik tuzatishlar, o'quvchi navbati raqami bo'yicha:
  // {[turn_idx]: {errors: [{span, fix, type}], verdict}}. Coach 2–6 s kechikib
  // javob beradi, shuning uchun ular gapga aynan idx orqali bog'lanadi.
  const [corrections, setCorrections] = useState({})
  // Yo'nalish muhiti: shadowing videosi yoki rol suhbat sahnasi.
  const [scene, setScene] = useState(null)
  const [lines, setLines] = useState([])
  // Shadowing baholari: {[idx]: {score, word_accuracy, tempo, note, ...}}.
  const [shadowScores, setShadowScores] = useState({})

  const socketRef = useRef(null)
  const playerRef = useRef(null)
  const recorderRef = useRef(null)
  const attemptRef = useRef(0)
  const closedRef = useRef(false)
  const speakingRef = useRef(false)
  const silenceTimerRef = useRef(null)
  // Ketma-ket nechta chunk ostonadan baland chiqdi (barge-in tasdig'i uchun).
  const voicedRef = useRef(0)
  // Joriy navbatda nechta chunk haqiqatan ovozli chiqdi.
  const turnVoicedRef = useRef(0)
  const prefixRef = useRef([]) // gapirish boshlanishidan oldingi chunklar
  const gateOpenRef = useRef(false)
  // Etalon eshittirilayotganda mikrofon butunlay yopiladi: video ovozi
  // o'quvchining navbati bo'lib ketmasligi kerak (§shadowing).
  const mutedRef = useRef(false)
  const micStatsRef = useRef({ sent: 0, total: 0 })
  const startedAtRef = useRef(null)
  const onEndedRef = useRef(onEnded)

  useEffect(() => {
    onEndedRef.current = onEnded
  }, [onEnded])

  const send = useCallback((payload) => {
    const socket = socketRef.current
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload))
    }
  }, [])

  // --- Mikrofon darvozasi: audio FAQAT o'quvchi gapirayotganda yuboriladi.
  //
  // Gemini Live kirish audiosi daqiqa bo'yicha hisoblanadi, jimlik esa
  // sessiyaning yarmidan ko'pini egallaydi. Darvoza shu qismni butunlay
  // yo'q qiladi. Barge-in buzilmaydi: o'quvchi AI ustidan gapirsa VAD
  // ishlaydi va audio yana oqadi.
  const handleChunk = useCallback(
    (b64) => {
      const stats = micStatsRef.current
      stats.total += 1

      if (mutedRef.current) {
        prefixRef.current = []
        gateOpenRef.current = false
        return
      }

      if (speakingRef.current) {
        if (!gateOpenRef.current) {
          gateOpenRef.current = true
          // Ostona kechikkanda yo'qolgan boshlanishni ham yuboramiz.
          for (const buffered of prefixRef.current) {
            send({ type: 'audio_chunk', data: buffered })
            stats.sent += 1
          }
          prefixRef.current = []
        }
        send({ type: 'audio_chunk', data: b64 })
        stats.sent += 1
        return
      }

      if (gateOpenRef.current) {
        gateOpenRef.current = false
        prefixRef.current = []
      }
      prefixRef.current.push(b64)
      if (prefixRef.current.length > PREFIX_CHUNKS) prefixRef.current.shift()
    },
    [send]
  )

  // --- mikrofon signalidan oddiy VAD: javob kechikishini aniq o'lchash uchun.
  // AI gapirayotgan paytda ostona echo darajasiga qarab ko'tariladi.
  const handleLevel = useCallback(
    (peak) => {
      setLevel(peak)
      // Etalon o'ynayotganda VAD ham jim: aks holda video ovozi "gapirdi"
      // bo'lib, navbat o'quvchisiz yopilib ketadi.
      if (mutedRef.current) {
        voicedRef.current = 0
        return
      }

      const player = playerRef.current
      const echoRisk = player ? player.echoRisk(ECHO_TAIL_MS) : false
      // Dinamikdan hozir chiqayotgan signal — echo'ning yuqori chegarasi.
      const outPeak = echoRisk && player ? player.outputPeak() : 0
      const threshold = echoRisk
        ? Math.max(BARGE_IN_THRESHOLD, outPeak * ECHO_MARGIN)
        : VAD_THRESHOLD

      if (peak > threshold) voicedRef.current += 1
      else voicedRef.current = 0

      const voiced = voicedRef.current >= (echoRisk ? BARGE_IN_HOLD : MIN_OPEN_CHUNKS)

      if (voiced) {
        turnVoicedRef.current += 1
        if (!speakingRef.current) {
          speakingRef.current = true
          turnVoicedRef.current = voicedRef.current
          send({ type: 'speech_start' })
          // Gapira boshladi — podkaska ham, tayyor javoblar ham endi kerak emas.
          setHint(null)
          setOptions([])
          // Haqiqiy barge-in: playbackni darhol o'chiramiz. Serverning
          // `ai_audio_interrupt` xabarini kutsak, AI ovozi yana bir necha
          // yuz ms mikrofonga tushib turadi — halqa aynan shu yerda tug'iladi.
          if (echoRisk) player?.interrupt()
        }
        if (silenceTimerRef.current) {
          clearTimeout(silenceTimerRef.current)
          silenceTimerRef.current = null
        }
      } else if (speakingRef.current && !silenceTimerRef.current) {
        silenceTimerRef.current = setTimeout(() => {
          speakingRef.current = false
          silenceTimerRef.current = null
          // Juda qisqa "gap" — bu nutq emas. Server buni baholamasin: navbat
          // bekor qilinadi va bufer tozalanadi.
          const long = turnVoicedRef.current >= MIN_TURN_CHUNKS
          turnVoicedRef.current = 0
          send({ type: long ? 'speech_end' : 'speech_cancel' })
        }, VAD_SILENCE_MS)
      }
    },
    [send]
  )

  const connect = useCallback(() => {
    if (closedRef.current) return
    const token = getToken()
    const socket = new WebSocket(`${wsUrl(wsPath)}?token=${encodeURIComponent(token)}`)
    socketRef.current = socket

    socket.onopen = () => {
      attemptRef.current = 0
      setStatus('live')
      setError(null)
      if (!startedAtRef.current) startedAtRef.current = Date.now()
    }

    socket.onmessage = (event) => {
      let msg
      try {
        msg = JSON.parse(event.data)
      } catch {
        return
      }

      switch (msg.type) {
        case 'session_ready':
          if (typeof msg.elapsed_s === 'number') {
            startedAtRef.current = Date.now() - msg.elapsed_s * 1000
          }
          setProgress((p) => ({ ...p, total: msg.questions_total || p.total }))
          setScene({
            track: msg.track || '',
            mediaSrc: msg.media_src || '',
            mediaKind: msg.media_kind || '',
            mediaRef: msg.media_ref || '',
            persona: msg.scene?.persona || '',
            setting: msg.scene?.setting || '',
            ambience: msg.scene?.ambience || '',
          })
          setLines(msg.shadow_lines || [])
          // Uzilishdan keyin server suhbat tarixini qaytaradi.
          if (msg.transcript?.length) {
            setTranscript(msg.transcript)
            setTranslations(
              Object.fromEntries(
                msg.transcript
                  .filter((t) => t.text_uz)
                  .map((t) => [t.idx, t.text_uz])
              )
            )
            setPartial(null)
          }
          break
        case 'transcript':
          if (msg.final) {
            setPartial(null)
            setTranscript((list) =>
              // Mavjud navbat qayta kelishi ikki holatda bo'ladi: reconnect
              // (matn o'sha-o'sha) va so'zma-so'z transkript kechikib yetib
              // kelganda (matn o'zgaradi). Ikkalasida ham almashtirish to'g'ri.
              list.some((t) => t.idx === msg.idx)
                ? list.map((t) => (t.idx === msg.idx ? { ...t, text: msg.text } : t))
                : [...list, { idx: msg.idx, speaker: msg.speaker, text: msg.text }]
            )
          } else {
            setPartial((p) =>
              p && p.speaker === msg.speaker
                ? { speaker: p.speaker, text: p.text + msg.text }
                : { speaker: msg.speaker, text: msg.text }
            )
          }
          break
        case 'shadow_score':
          setShadowScores((map) => ({ ...map, [msg.idx]: msg }))
          break
        case 'translation':
          setTranslations((map) => ({ ...map, [msg.idx]: msg.text_uz }))
          break
        case 'options':
          // Qotib qolganda ekranda paydo bo'ladi; gapira boshlasa yo'qoladi.
          setOptions(msg.items || [])
          break
        case 'ai_audio':
          playerRef.current?.enqueue(msg.data)
          break
        case 'ai_audio_interrupt':
          playerRef.current?.interrupt()
          break
        case 'state':
          setMicState(msg.value)
          break
        case 'hint':
          // Podkaska ovozda ham keladi; ekranda ko'rish esa tokensiz va
          // eslab qolish uchun eng foydali qism.
          setHint({
            rung: msg.rung,
            kind: msg.kind,
            labelUz: msg.label_uz,
            text: msg.text,
          })
          break
        case 'correction':
          // Xatosiz javob ham keladi (errors bo'sh) — "toza" belgisi uchun.
          setCorrections((map) => ({
            ...map,
            [msg.turn_idx]: {
              errors: msg.errors || [],
              verdict: msg.verdict,
            },
          }))
          break
        case 'progress':
          setProgress({
            asked: msg.asked,
            total: msg.total,
            correct: msg.correct,
          })
          break
        case 'session_end':
          closedRef.current = true
          setStatus('ended')
          onEndedRef.current?.(msg.reason)
          break
        case 'error':
          setError(msg.code)
          if (msg.code === 'gemini_lost' || msg.code === 'gemini_unavailable') {
            setStatus('error')
          }
          break
        default:
          break
      }
    }

    socket.onclose = () => {
      if (closedRef.current) return
      if (attemptRef.current >= MAX_RECONNECTS) {
        setStatus('error')
        setError('connection_lost')
        return
      }
      const delay = BACKOFF_MS[attemptRef.current] || 7000
      attemptRef.current += 1
      setStatus('reconnecting')
      setTimeout(connect, delay)
    }

    socket.onerror = () => {
      // onclose baribir chaqiriladi — u yerda qayta ulanamiz.
    }
  }, [wsPath])

  // Audio odatda "Gapirishni boshlash" tap'ida tayyorlangan bo'ladi (iOS talabi).
  // Tayyor bo'lmasa — shu yerda ochamiz (desktop/dev holati).
  const start = useCallback(async () => {
    closedRef.current = false
    const prepared = takeAudio()

    const player = prepared?.player || new PCMPlayer()
    player.onStateChange = (speaking) =>
      setMicState(speaking ? 'ai_speaking' : 'listening')
    playerRef.current = player
    if (!prepared) await player.unlock()

    const recorder = prepared?.recorder || new MicRecorder()
    micStatsRef.current = { sent: 0, total: 0 }
    voicedRef.current = 0
    recorder.onChunk = handleChunk
    recorder.onLevel = handleLevel
    recorderRef.current = recorder
    if (!prepared) await recorder.start()

    connect()
  }, [connect, handleChunk, handleLevel])

  const stop = useCallback(
    async (notifyServer = true) => {
      closedRef.current = true
      if (notifyServer) send({ type: 'end_session' })
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
      await recorderRef.current?.stop()
      await playerRef.current?.close()
      recorderRef.current = null
      playerRef.current = null
      // Umumiy AudioContext oxirida yopiladi (capture + playback bir grafda).
      await closeAudioContext()
      socketRef.current?.close()
      socketRef.current = null
    },
    [send]
  )

  // Taymer + mikrofon darvozasi statistikasi (qancha audio tejalgani).
  useEffect(() => {
    const timer = setInterval(() => {
      const { sent, total } = micStatsRef.current
      if (total > 0) setMicDuty(Math.round((sent / total) * 100))
      if (!startedAtRef.current) return
      setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000))
    }, 500)
    return () => clearInterval(timer)
  }, [])

  // Komponent yo'qolganda hamma narsani yopamiz.
  useEffect(() => {
    return () => {
      closedRef.current = true
      recorderRef.current?.stop()
      playerRef.current?.close()
      closeAudioContext()
      socketRef.current?.close()
    }
  }, [])

  /** Etalon eshittirilganda chaqiriladi: qaysi gap va necha ms davom etgani. */
  const markShadowLine = useCallback(
    (idx, referenceMs) => send({ type: 'shadow_line', idx, reference_ms: Math.round(referenceMs) }),
    [send]
  )

  /** Etalon o'ynayotganda mikrofonni butunlay yopadi. */
  const muteMic = useCallback((muted) => {
    mutedRef.current = Boolean(muted)
    if (muted) {
      speakingRef.current = false
      voicedRef.current = 0
      turnVoicedRef.current = 0
      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current)
        silenceTimerRef.current = null
      }
    }
  }, [])

  return {
    status,
    micState,
    level,
    elapsed,
    remaining: Math.max(0, timeLimit - elapsed),
    progress,
    transcript,
    partial,
    translations,
    corrections,
    error,
    micDuty,
    hint,
    options,
    start,
    stop,
    sessionId,
    scene,
    lines,
    shadowScores,
    markShadowLine,
    muteMic,
  }
}
