// Brauzerlar (ayniqsa iOS Safari) mikrofon ruxsati va audio playback'ni FAQAT
// foydalanuvchi imo-ishorasi ichida ochadi (§8.4). Shuning uchun audio
// "Gapirishni boshlash" bosilishining o'zida tayyorlanadi, sessiya ekrani esa
// tayyor obyektlarni oladi.

import { closeAudioContext } from './context'
import { PCMPlayer } from './player'
import { MicRecorder } from './recorder'

let pending = null

/** Tap ichida chaqiriladi: playback yo'lini ochadi va mikrofon ruxsatini so'raydi. */
export async function prepareAudio() {
  releaseAudio()
  const player = new PCMPlayer()
  await player.unlock()

  const recorder = new MicRecorder()
  await recorder.start()

  pending = { player, recorder }
  return pending
}

/** Sessiya ekrani tayyor audio obyektlarini oladi (bir marta). */
export function takeAudio() {
  const value = pending
  pending = null
  return value
}

/** Sessiya boshlanmay qolsa resurslarni bo'shatadi. */
export function releaseAudio() {
  if (!pending) return
  pending.recorder?.stop()
  pending.player?.close()
  pending = null
  closeAudioContext()
}
