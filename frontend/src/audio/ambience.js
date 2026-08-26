/**
 * Rol suhbat foni — brauzerda YASALADI, fayl yuklanmaydi.
 *
 * Nega shunday: kafe shovqinini mp3 qilib tashish 1–2 MB, olti vaziyat uchun
 * o'n megabaytga yaqin, ustiga litsenziya masalasi. Web Audio esa o'sha
 * hissni bir necha o'nlab qator kod bilan beradi: filtrlangan shovqin (xona
 * gumburi) + vaqti-vaqti bilan chalinadigan tasodifiy tovushlar (piyola,
 * mashina, klaviatura). Cheksiz davom etadi va hech qachon takrorlanmaydi.
 *
 * Ovoz ataylab past: bu fon, mashq emas. AI gapirganda yana pasayadi
 * (`duck`) — muhit suhbatni bosib qo'ymasligi kerak.
 */

const PROFILES = {
  cafe: {
    // Past gumbur + piyola-qoshiq jarangi + uzoqdagi gap-so'z.
    bed: { type: 'lowpass', frequency: 520, gain: 0.055 },
    events: { every: [1.4, 4.2], kind: 'clink' },
  },
  street: {
    bed: { type: 'lowpass', frequency: 320, gain: 0.075 },
    events: { every: [2.5, 7], kind: 'pass' },
  },
  office: {
    bed: { type: 'lowpass', frequency: 260, gain: 0.04 },
    events: { every: [0.6, 2.2], kind: 'key' },
  },
  clinic: {
    bed: { type: 'lowpass', frequency: 240, gain: 0.03 },
    events: { every: [5, 12], kind: 'door' },
  },
  hotel: {
    bed: { type: 'lowpass', frequency: 380, gain: 0.035 },
    events: { every: [3, 9], kind: 'clink' },
  },
  shop: {
    bed: { type: 'lowpass', frequency: 440, gain: 0.05 },
    events: { every: [2, 6], kind: 'beep' },
  },
}

export const AMBIENCE_KINDS = Object.keys(PROFILES)

/** Cheksiz "shitirlash" manbai: 2 soniyalik oq shovqin buferi, halqa bilan. */
function noiseSource(ctx) {
  const frames = ctx.sampleRate * 2
  const buffer = ctx.createBuffer(1, frames, ctx.sampleRate)
  const data = buffer.getChannelData(0)
  let last = 0
  for (let i = 0; i < frames; i += 1) {
    // Jigarrang shovqin: oq shovqinga qaraganda xona gumburiga yaqin.
    const white = Math.random() * 2 - 1
    last = (last + 0.02 * white) / 1.02
    data[i] = last * 3.5
  }
  const source = ctx.createBufferSource()
  source.buffer = buffer
  source.loop = true
  return source
}

/** Bitta qisqa tovush — profil turiga qarab. */
function playEvent(ctx, destination, kind) {
  const now = ctx.currentTime
  const gain = ctx.createGain()
  gain.connect(destination)

  if (kind === 'clink' || kind === 'beep') {
    const osc = ctx.createOscillator()
    osc.type = kind === 'beep' ? 'square' : 'triangle'
    osc.frequency.value = kind === 'beep' ? 900 : 1400 + Math.random() * 900
    gain.gain.setValueAtTime(0.0001, now)
    gain.gain.exponentialRampToValueAtTime(kind === 'beep' ? 0.05 : 0.08, now + 0.005)
    gain.gain.exponentialRampToValueAtTime(0.0001, now + (kind === 'beep' ? 0.12 : 0.35))
    osc.connect(gain)
    osc.start(now)
    osc.stop(now + 0.4)
    return
  }

  if (kind === 'key') {
    const osc = ctx.createOscillator()
    osc.type = 'square'
    osc.frequency.value = 180 + Math.random() * 120
    gain.gain.setValueAtTime(0.03, now)
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.05)
    osc.connect(gain)
    osc.start(now)
    osc.stop(now + 0.06)
    return
  }

  // 'pass' (o'tib ketayotgan mashina) va 'door' — filtrlangan shovqin portlashi.
  const source = noiseSource(ctx)
  const filter = ctx.createBiquadFilter()
  filter.type = 'bandpass'
  filter.frequency.value = kind === 'door' ? 300 : 700
  filter.Q.value = 0.7
  const length = kind === 'door' ? 0.5 : 1.6
  gain.gain.setValueAtTime(0.0001, now)
  gain.gain.linearRampToValueAtTime(kind === 'door' ? 0.05 : 0.07, now + length * 0.35)
  gain.gain.exponentialRampToValueAtTime(0.0001, now + length)
  source.connect(filter)
  filter.connect(gain)
  source.start(now)
  source.stop(now + length + 0.1)
}

/**
 * Fonni yoqadi. Qaytgan obyekt: `stop()`, `duck(on)`, `setEnabled(on)`.
 * Noma'lum yoki bo'sh profil uchun `null` — chaqiruvchi tekshirmasa ham
 * hech narsa bo'lmaydi.
 */
export function startAmbience(ctx, kind) {
  const profile = PROFILES[kind]
  if (!ctx || !profile) return null

  const master = ctx.createGain()
  master.gain.value = 0
  master.connect(ctx.destination)

  const bedGain = ctx.createGain()
  bedGain.gain.value = profile.bed.gain
  const filter = ctx.createBiquadFilter()
  filter.type = profile.bed.type
  filter.frequency.value = profile.bed.frequency

  const bed = noiseSource(ctx)
  bed.connect(filter)
  filter.connect(bedGain)
  bedGain.connect(master)
  bed.start()

  // Yumshoq kirish — muhit "yoqilgandek" emas, "bor edi"dek eshitilsin.
  master.gain.linearRampToValueAtTime(1, ctx.currentTime + 1.2)

  let timer = null
  const [minGap, maxGap] = profile.events.every
  const schedule = () => {
    const delay = (minGap + Math.random() * (maxGap - minGap)) * 1000
    timer = setTimeout(() => {
      try {
        playEvent(ctx, master, profile.events.kind)
      } catch {
        // Kontekst yopilgan — fon shu yerda tugaydi.
      }
      schedule()
    }, delay)
  }
  schedule()

  let enabled = true
  return {
    kind,
    duck(on) {
      if (!enabled) return
      const target = on ? 0.35 : 1
      master.gain.linearRampToValueAtTime(target, ctx.currentTime + 0.25)
    },
    setEnabled(on) {
      enabled = Boolean(on)
      master.gain.linearRampToValueAtTime(enabled ? 1 : 0, ctx.currentTime + 0.2)
    },
    stop() {
      if (timer) clearTimeout(timer)
      try {
        master.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.3)
        bed.stop(ctx.currentTime + 0.4)
      } catch {
        // Allaqachon to'xtagan.
      }
    },
  }
}
