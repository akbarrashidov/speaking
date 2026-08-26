/**
 * favicon.svg dan brauzer uchun rasterlangan nishonlarni yasaydi.
 *
 * Nega kerak: SVG nishonni Safari va eski Edge o'qimaydi, Android esa PWA
 * ro'yxatiga PNG kutadi. Shuning uchun bitta manba (public/favicon.svg) va
 * shundan hosil qilingan PNG/ICO to'plami — qo'lda chizilgan ikkinchi nusxa
 * emas, aks holda logotip o'zgarganda ular ajralib qoladi.
 *
 * Ishlatish:
 *   npm run icons
 *
 * Chrome tizimda o'rnatilgan bo'lishi kerak — `puppeteer-core` brauzer yuklab
 * olmaydi (screenshot.mjs ham shunday ishlaydi).
 */
import { readFile, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import puppeteer from 'puppeteer-core'

const PUBLIC = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'public')
const CHROME =
  process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'

// Har bir PNG nima uchun kerakligi shu yerda yozilgan — keyingi safar
// "bu 180px nimaga?" degan savol tug'ilmasin.
const PNGS = [
  { src: 'favicon.svg', size: 16, out: 'favicon-16.png' }, // yorliq (1x)
  { src: 'favicon.svg', size: 32, out: 'favicon-32.png' }, // yorliq (2x), ICO
  { src: 'favicon.svg', size: 48, out: 'favicon-48.png' }, // Windows yorliq
  { src: 'favicon.svg', size: 180, out: 'apple-touch-icon.png' }, // iOS bosh ekrani
  { src: 'favicon.svg', size: 192, out: 'icon-192.png' }, // PWA ro'yxati
  { src: 'favicon.svg', size: 512, out: 'icon-512.png' }, // PWA ro'yxati / splash
  { src: 'icon-maskable.svg', size: 512, out: 'icon-maskable-512.png' }, // Android mask
]

// ICO ga faqat kichik o'lchamlar kiradi: yorliq va Windows yorlig'i shundan oladi.
const ICO_SIZES = [16, 32, 48]

/** PNG ni ICO konteyneriga o'raydi (PNG-in-ICO — barcha zamonaviy tizimlar o'qiydi). */
function packIco(images) {
  const header = Buffer.alloc(6)
  header.writeUInt16LE(0, 0) // reserved
  header.writeUInt16LE(1, 2) // type: icon
  header.writeUInt16LE(images.length, 4)

  let offset = 6 + images.length * 16
  const entries = images.map(({ size, data }) => {
    const entry = Buffer.alloc(16)
    entry.writeUInt8(size >= 256 ? 0 : size, 0) // 256 = 0 ta'rif bo'yicha
    entry.writeUInt8(size >= 256 ? 0 : size, 1)
    entry.writeUInt8(0, 2) // palitra yo'q
    entry.writeUInt8(0, 3) // reserved
    entry.writeUInt16LE(1, 4) // planes
    entry.writeUInt16LE(32, 6) // bit/piksel
    entry.writeUInt32LE(data.length, 8)
    entry.writeUInt32LE(offset, 12)
    offset += data.length
    return entry
  })

  return Buffer.concat([header, ...entries, ...images.map((i) => i.data)])
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-device-scale-factor=1'],
})
const page = await browser.newPage()

const svgCache = new Map()
async function dataUrl(name) {
  if (!svgCache.has(name)) {
    const svg = await readFile(resolve(PUBLIC, name))
    svgCache.set(name, `data:image/svg+xml;base64,${svg.toString('base64')}`)
  }
  return svgCache.get(name)
}

const rendered = new Map()
for (const { src, size, out } of PNGS) {
  await page.setViewport({ width: size, height: size, deviceScaleFactor: 1 })
  await page.setContent(
    `<style>html,body{margin:0;background:transparent}
     img{display:block;width:${size}px;height:${size}px}</style>
     <img src="${await dataUrl(src)}">`,
    { waitUntil: 'load' }
  )
  // omitBackground — nishon shaffof bo'lishi kerak, oq kvadratda emas.
  const data = await page.screenshot({ type: 'png', omitBackground: true })
  await writeFile(resolve(PUBLIC, out), data)
  rendered.set(size, Buffer.from(data))
  console.log(`  ${out.padEnd(24)} ${size}x${size}  ${data.length} bayt`)
}

await browser.close()

const ico = packIco(ICO_SIZES.map((size) => ({ size, data: rendered.get(size) })))
await writeFile(resolve(PUBLIC, 'favicon.ico'), ico)
console.log(`  favicon.ico              ${ICO_SIZES.join('/')}       ${ico.length} bayt`)
