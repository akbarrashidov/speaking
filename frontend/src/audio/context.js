// Butun sessiya uchun BITTA AudioContext.
//
// Nega bitta: mikrofon capture va AI playback bir xil audio grafda bo'lsa,
// brauzerning akustik echo canceller'i (AEC) chiqish signalini "reference"
// sifatida ko'radi va dinamikdan mikrofonga qaytgan AI ovozini o'chiradi.
// Ilgari player o'zining `sampleRate: 24000` contextini ochardi — qurilmaning
// tabiiy tezligidan (odatda 48 kHz) farq qilgani uchun brauzer alohida chiqish
// oqimi + resampler ochib, AEC referensini yo'qotardi. Natija: AI o'z ovozini
// eshitib, o'zini bo'lib turardi.

let context = null

/** Umumiy AudioContext (yopilgan bo'lsa qaytadan ochiladi). */
export function getAudioContext() {
  if (!context || context.state === 'closed') {
    const Ctx = window.AudioContext || window.webkitAudioContext
    // sampleRate BERILMAYDI — qurilmaning tabiiy tezligi AEC uchun shart.
    context = new Ctx({ latencyHint: 'interactive' })
  }
  return context
}

/** iOS/Safari: foydalanuvchi tap'i ichida chaqirilishi kerak. */
export async function resumeAudioContext() {
  const ctx = getAudioContext()
  if (ctx.state === 'suspended') await ctx.resume()
  return ctx
}

export async function closeAudioContext() {
  if (context && context.state !== 'closed') {
    try {
      await context.close()
    } catch (err) {
      console.warn('AudioContext yopishda xato:', err)
    }
  }
  context = null
}
