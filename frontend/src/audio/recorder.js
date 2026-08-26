// Mikrofon capture: AudioWorklet, mavjud bo'lmasa ScriptProcessor fallback (§5.1).
// Chiqish: 16 kHz, 16-bit, mono PCM chunklar (base64).
//
// Capture playback bilan bitta AudioContext'da turadi (context.js) — brauzer
// AEC'i AI ovozini mikrofondan o'chira olishi uchun.

import { resumeAudioContext } from './context'

const TARGET_RATE = 16000
const CHUNK_MS = 100

// Worklet Blob orqali yuklanadi — bundler sozlamalariga bog'liq emas.
const WORKLET_SOURCE = `
class PCMDownsampler extends AudioWorkletProcessor {
  constructor(options) {
    super()
    this.targetRate = options.processorOptions.targetRate
    this.ratio = sampleRate / this.targetRate
    this.buffer = []
    this.offset = 0
    this.samplesPerChunk = Math.round(this.targetRate * ${CHUNK_MS} / 1000)
    this.out = new Float32Array(this.samplesPerChunk)
    this.outIndex = 0
  }

  process(inputs) {
    const input = inputs[0]
    if (!input || !input[0]) return true
    const channel = input[0]

    // Chiziqli interpolyatsiya bilan pastga diskretlash.
    while (this.offset < channel.length) {
      const index = Math.floor(this.offset)
      const frac = this.offset - index
      const a = channel[index]
      const b = index + 1 < channel.length ? channel[index + 1] : a
      this.out[this.outIndex++] = a + (b - a) * frac

      if (this.outIndex >= this.samplesPerChunk) {
        const pcm = new Int16Array(this.samplesPerChunk)
        let peak = 0
        for (let i = 0; i < this.samplesPerChunk; i++) {
          const s = Math.max(-1, Math.min(1, this.out[i]))
          pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff
          const abs = Math.abs(s)
          if (abs > peak) peak = abs
        }
        this.port.postMessage({ pcm: pcm.buffer, peak }, [pcm.buffer])
        this.outIndex = 0
      }
      this.offset += this.ratio
    }
    this.offset -= channel.length
    return true
  }
}
registerProcessor('pcm-downsampler', PCMDownsampler)
`

function floatToPCM16(input, ratio, targetLength) {
  const out = new Int16Array(targetLength)
  let peak = 0
  for (let i = 0; i < targetLength; i++) {
    const idx = Math.floor(i * ratio)
    const s = Math.max(-1, Math.min(1, input[idx] || 0))
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff
    const abs = Math.abs(s)
    if (abs > peak) peak = abs
  }
  return { pcm: out, peak }
}

export function pcmToBase64(buffer) {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  const step = 0x8000
  for (let i = 0; i < bytes.length; i += step) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + step))
  }
  return btoa(binary)
}

export class MicRecorder {
  constructor({ onChunk, onLevel } = {}) {
    this.onChunk = onChunk || (() => {})
    this.onLevel = onLevel || (() => {})
    this.context = null
    this.stream = null
    this.node = null
    this.source = null
    this.running = false
    this.mode = null
  }

  async start() {
    if (this.running) return
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        // Chrome/Edge: dasturiy AEC ba'zi qurilmalarda o'chib qoladi —
        // eski nomdagi bayroqlar uni majburan yoqadi. Qo'llab-quvvatlamagan
        // brauzer bu maydonlarni e'tiborsiz qoldiradi.
        googEchoCancellation: true,
        googAutoGainControl: true,
        googNoiseSuppression: true,
      },
    })

    // iOS: foydalanuvchi tap'idan keyin resume shart.
    this.context = await resumeAudioContext()
    this.source = this.context.createMediaStreamSource(this.stream)

    if (this.context.audioWorklet) {
      try {
        await this._startWorklet()
        this.mode = 'worklet'
      } catch (err) {
        console.warn('AudioWorklet ishlamadi, fallback:', err)
        this._startScriptProcessor()
        this.mode = 'script-processor'
      }
    } else {
      this._startScriptProcessor()
      this.mode = 'script-processor'
    }

    this.running = true
  }

  async _startWorklet() {
    const blob = new Blob([WORKLET_SOURCE], { type: 'application/javascript' })
    const url = URL.createObjectURL(blob)
    try {
      await this.context.audioWorklet.addModule(url)
    } finally {
      URL.revokeObjectURL(url)
    }
    this.node = new AudioWorkletNode(this.context, 'pcm-downsampler', {
      numberOfInputs: 1,
      numberOfOutputs: 0,
      processorOptions: { targetRate: TARGET_RATE },
    })
    this.node.port.onmessage = (event) => {
      const { pcm, peak } = event.data
      this.onLevel(peak)
      this.onChunk(pcmToBase64(pcm))
    }
    this.source.connect(this.node)
  }

  _startScriptProcessor() {
    const bufferSize = 4096
    this.node = this.context.createScriptProcessor(bufferSize, 1, 1)
    const ratio = this.context.sampleRate / TARGET_RATE
    this.node.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0)
      const targetLength = Math.floor(input.length / ratio)
      if (targetLength <= 0) return
      const { pcm, peak } = floatToPCM16(input, ratio, targetLength)
      this.onLevel(peak)
      this.onChunk(pcmToBase64(pcm.buffer))
    }
    this.source.connect(this.node)
    // ScriptProcessor ishlashi uchun chiqishga ulanishi shart (ovozsiz).
    const silent = this.context.createGain()
    silent.gain.value = 0
    this.node.connect(silent)
    silent.connect(this.context.destination)
  }

  async stop() {
    this.running = false
    try {
      if (this.node) {
        this.node.disconnect()
        if (this.node.port) this.node.port.onmessage = null
        this.node.onaudioprocess = null
      }
      if (this.source) this.source.disconnect()
      if (this.stream) this.stream.getTracks().forEach((t) => t.stop())
      // Context umumiy — uni sessiya yopadi (closeAudioContext), recorder emas.
    } catch (err) {
      console.warn('Recorder to\'xtatishda xato:', err)
    }
    this.node = null
    this.source = null
    this.stream = null
    this.context = null
  }
}
