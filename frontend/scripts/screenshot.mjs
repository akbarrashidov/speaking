/**
 * Ilovani haqiqiy brauzerda ochib, ekran rasmlarini oladi.
 *
 * Nega kerak: CSS ni o'qib turib dizaynni baholab bo'lmaydi. Qorong'i
 * mavzudagi oqarib ketgan fon, siqilib qolgan karta, matn ustiga tushgan
 * marker — bularning hammasi faqat RENDER qilingan sahifada ko'rinadi.
 *
 * Ishlatish:
 *   node scripts/screenshot.mjs <JWT> <chiqish papkasi>
 *   SHOT_THEME=dark node scripts/screenshot.mjs ...
 *
 * Token olish:
 *   docker compose exec web python -c "..."  (README §sinov)
 *
 * Chrome tizimda o'rnatilgan bo'lishi kerak — `puppeteer-core` brauzer
 * yuklab olmaydi, mavjudini ishlatadi.
 */
import puppeteer from 'puppeteer-core'

const [, , TOKEN, OUT, FEEDBACK] = process.argv
const BASE = process.env.SHOT_BASE || 'http://localhost:9100'
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-device-scale-factor=1'],
  defaultViewport: { width: 1440, height: 900 },
})

const page = await browser.newPage()
page.on('console', (m) => {
  if (m.type() === 'error') console.log('  BRAUZER XATO:', m.text().slice(0, 200))
})
page.on('pageerror', (e) => console.log('  SAHIFA XATO:', String(e).slice(0, 200)))

// Avval kirish ekranini suratga olamiz — yangi foydalanuvchi shuni ko'radi.
await page.goto(`${BASE}/`, { waitUntil: 'networkidle2', timeout: 25000 })
await page.evaluate((theme) => {
  localStorage.clear()
  localStorage.setItem('speaking.theme', theme)
  document.documentElement.dataset.theme = theme
}, process.env.SHOT_THEME || 'light')
await page.reload({ waitUntil: 'networkidle2' })
await new Promise((r) => setTimeout(r, 900))
await page.screenshot({ path: `${OUT}/auth.png` })
console.log('auth      → suratga olindi')

// Endi tokenni qo'yamiz — kirish ekranidan o'tib ketamiz.
await page.evaluate(
  (token, theme) => {
    localStorage.setItem('speaking.jwt', token)
    localStorage.setItem('speaking.jwt_expires_at', String(Date.now() + 3500 * 1000))
    localStorage.setItem('speaking.lang', 'uz')
    localStorage.setItem('speaking.theme', theme)
  },
  TOKEN,
  process.env.SHOT_THEME || 'light'
)

const shots = [
  ['home', '/'],
  ['topics', '/mavzular'],
  ...(process.env.SHOT_MATERIAL
    ? [['material', `/${process.env.SHOT_MATERIAL.replace(/^.*?mavzular\//, 'mavzular/')}`]]
    : []),
  ['progress', '/progress'],
  ...(FEEDBACK ? [['feedback', `/${FEEDBACK.replace(/^.*?(natija|sessiya)\//, '$1/')}`]] : []),
]

for (const [name, path] of shots) {
  await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle2', timeout: 25000 })
  await new Promise((r) => setTimeout(r, 1200))
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false })
  if (name === 'home') await page.screenshot({ path: `${OUT}/home-full.png`, fullPage: true })
  const title = await page.evaluate(() => document.querySelector('h1, .sentence')?.textContent || '(sarlavha yo\u2018q)')
  console.log(`${name.padEnd(9)} → ${title.slice(0, 70)}`)
}

await browser.close()
console.log('TAYYOR')
