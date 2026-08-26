// AI audiosini ketma-ket ijro etish (24 kHz PCM) + barge-in uchun darhol to'xtatish.
//
// Playback mikrofon bilan bitta AudioContext'da turadi (context.js). Bundan
// tashqari player o'z chiqish darajasini o'lchaydi: VAD dinamikdan qaytgan
// echo'ni o'quvchining nutqidan shu qiymat orqali ajratadi.

import { resumeAudioContext } from './context'

const DEFAULT_RATE = 24000
// Echo mikrofonga kechikib yetadi (dinamik → xona → mikrofon + bufer).
// Shuning uchun chiqish darajasi tarixining eng balandini olamiz: 4 × 100 ms.
const LEVEL_HISTORY = 4
// Audio tugagach echo yana shuncha vaqt mikrofonga tushib turadi.
const ECHO_TAIL_MS = 300

function base64ToInt16(b64) {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return new Int16Array(bytes.buffer, 0, Math.floor(bytes.length / 2))
}

export class PCMPlayer {
  constructor({ sampleRate = DEFAULT_RATE, onStateChange } = {}) {
    this.sampleRate = sampleRate
    this.onStateChange = onStateChange || (() => {})
    this.context = null
    this.analyser = null
    this.probe = null
    this.levels = []
    this.playHead = 0
    this.sources = new Set()
    this.speaking = false
  }

  // iOS autoplay siyosati: AudioContext foydalanuvchi tap'i ichida ochiladi (§8.4).
  async unlock() {
    this.context = await resumeAudioContext()
    this._ensureGraph()
    // Jimjit buferni ijro etish — iOS'da audio yo'lini "ochadi".
    const buffer = this.context.createBuffer(1, 1, this.context.sampleRate)
    const source = this.context.createBufferSource()
    source.buffer = buffer
    source.connect(this.analyser)
    source.start(0)
  }

  _ensureGraph() {
    if (this.analyser) return
    this.analyser = this.context.createAnalyser()
    this.analyser.fftSize = 512
    this.analyser.connect(this.context.destination)
    this.probe = new Float32Array(this.analyser.fftSize)
  }

  enqueue(b64) {
    if (!this.context) return
    const pcm = base64ToInt16(b64)
    if (!pcm.length) return

    // Bufer 24 kHz da qoladi — context tabiiy tezlikda bo'lsa ham Web Audio
    // uni o'zi resample qiladi.
    const buffer = this.context.createBuffer(1, pcm.length, this.sampleRate)
    const channel = buffer.getChannelData(0)
    for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 0x8000

    const source = this.context.createBufferSource()
    source.buffer = buffer
    source.connect(this.analyser)

    const now = this.context.currentTime
    // Kichik bufer — uzilishlarning oldini oladi.
    if (this.playHead < now + 0.05) this.playHead = now + 0.05
    source.start(this.playHead)
    this.playHead += buffer.duration

    this.sources.add(source)
    source.onended = () => {
      this.sources.delete(source)
      if (this.sources.size === 0) this._setSpeaking(false)
    }
    this._setSpeaking(true)
  }

  /** Hozir dinamikdan chiqayotgan signalning cho'qqisi (yaqin tarix bilan). */
  outputPeak() {
    if (!this.analyser) return 0
    this.analyser.getFloatTimeDomainData(this.probe)
    let peak = 0
    for (let i = 0; i < this.probe.length; i++) {
      const abs = Math.abs(this.probe[i])
      if (abs > peak) peak = abs
    }
    this.levels.push(peak)
    if (this.levels.length > LEVEL_HISTORY) this.levels.shift()
    return Math.max(...this.levels)
  }

  /** Hozir mikrofonga AI ovozi tushayotgan bo'lishi mumkinmi? */
  echoRisk(tailMs = ECHO_TAIL_MS) {
    if (!this.context) return false
    if (this.speaking) return true
    return this.context.currentTime < this.playHead + tailMs / 1000
  }

  // Barge-in: navbatdagi hamma narsa darhol to'xtaydi (§5.1).
  interrupt() {
    this.sources.forEach((source) => {
      try {
        source.onended = null
        source.stop()
      } catch {
        // allaqachon tugagan
      }
    })
    this.sources.clear()
    this.levels = []
    this.playHead = this.context ? this.context.currentTime : 0
    this._setSpeaking(false)
  }

  _setSpeaking(value) {
    if (this.speaking === value) return
    this.speaking = value
    this.onStateChange(value)
  }

  // Context umumiy — uni sessiya yopadi (closeAudioContext), player emas.
  async close() {
    this.interrupt()
    if (this.analyser) {
      try {
        this.analyser.disconnect()
      } catch {
        // context allaqachon yopilgan
      }
    }
    this.analyser = null
    this.probe = null
    this.context = null
  }
}
