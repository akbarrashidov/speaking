/**
 * Qobiq: chapda doimiy panel, o'ngda sahifa.
 *
 * Chap panel — mashq rejimlari ro'yxati. Hozircha faqat grammatika ochiq,
 * qolgan uchtasi ko'rinib turadi va nima bo'lishini aytadi: yopiq eshik emas,
 * e'lon. Shuning uchun ular o'chirilgan tugma emas, oddiy qatorlar.
 */
import { useEffect, useRef, useState } from 'react'

import { useAuth } from '../auth/AuthContext'
import { useI18n } from '../i18n'
import { Link, paths, useRouter } from '../router'
import { useTheme } from '../theme'
import Backdrop from './Backdrop'
import Icon from './Icon'
import Logo from './Logo'

export const MODES = [
  { id: 'grammar', icon: 'grammar', ready: true, to: paths.topics },
  { id: 'phrases', icon: 'phrases', ready: true, to: paths.phrases },
  { id: 'shadowing', icon: 'shadowing', ready: true, to: paths.shadowing },
  { id: 'roleplay', icon: 'roleplay', ready: true, to: paths.roleplay },
]

function LanguageSwitch() {
  const { lang, languages } = useI18n()
  // Almashtirish AuthContext'da: interfeys, profil va serverdan keladigan
  // matnlar bitta bosishda birga o'zgarishi kerak.
  const { setLanguage } = useAuth()
  return (
    <div className="langswitch" role="group" aria-label="Til / Язык">
      {languages.map((item) => (
        <button
          key={item.code}
          type="button"
          aria-pressed={lang === item.code}
          onClick={() => setLanguage(item.code)}
        >
          {item.short}
        </button>
      ))}
    </div>
  )
}

/**
 * Orqaga qaytish — matn havolasi emas, boshqaruv.
 *
 * Yorliq qayerga qaytishni AYTADI ("Mavzular"), "Orqaga" emas: foydalanuvchi
 * bosishdan oldin qayerga tushishini bilishi kerak. Ikonka o'z kvadratida
 * turadi — shu bois nishon telefonda ham barmoq bilan uriladigan o'lchamda
 * (34px) va sahifa sarlavhasidan aniq ajralib turadi.
 */
/**
 * Profil menyusi — til, mavzu va chiqish shu yerda.
 *
 * Ilgari uchalasi yon panelning ostida alohida qator bo'lib turardi: ular
 * kunda bir marta ham bosilmaydi, lekin doimiy ravishda joy egallab, mashq
 * yo'nalishlari bilan bir xil vaznda ko'rinardi. Endi ular profil ostida —
 * bu sozlama, mashq emas.
 */
function UserMenu() {
  const { user, signOut } = useAuth()
  const { theme, toggle } = useTheme()
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const root = useRef(null)
  const trigger = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onDown = (event) => {
      if (!root.current?.contains(event.target)) setOpen(false)
    }
    const onKey = (event) => {
      if (event.key !== 'Escape') return
      setOpen(false)
      // Fokus tugmaga qaytadi — aks holda klaviatura bilan yurgan
      // foydalanuvchi sahifaning boshiga tashlab yuboriladi.
      trigger.current?.focus()
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (!user) return null
  const initial = (user.display_name || user.email || '?').charAt(0).toUpperCase()

  return (
    <div className={`usermenu ${open ? 'usermenu--open' : ''}`} ref={root}>
      <button
        type="button"
        ref={trigger}
        className="navitem usermenu__trigger"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="avatar">{initial}</span>
        <span className="navitem__label">{user.display_name || user.email}</span>
        <Icon name="chevronUpDown" size={15} className="usermenu__caret" />
      </button>

      {open && (
        <div className="usermenu__panel" role="menu">
          <div className="usermenu__who">
            <span className="usermenu__name">{user.display_name || t('nav.signout')}</span>
            <span className="usermenu__mail">{user.email}</span>
          </div>

          <div className="usermenu__group">
            <LanguageSwitch />
          </div>

          <button type="button" className="navitem" onClick={toggle} role="menuitem">
            <span className="navitem__icon">
              <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={18} />
            </span>
            <span className="usermenu__label">
              {theme === 'dark' ? t('nav.theme.light') : t('nav.theme.dark')}
            </span>
          </button>

          <button type="button" className="navitem" onClick={signOut} role="menuitem">
            <span className="navitem__icon">
              <Icon name="logout" size={18} />
            </span>
            <span className="usermenu__label">{t('nav.signout')}</span>
          </button>
        </div>
      )}
    </div>
  )
}

export function BackLink({ to, children }) {
  return (
    <Link to={to} className="backlink">
      <span className="backlink__icon">
        <Icon name="arrowBack" size={16} />
      </span>
      <span className="backlink__label">{children}</span>
    </Link>
  )
}

export default function Shell({ children, bare = false }) {
  const { t } = useI18n()
  const { route } = useRouter()

  if (bare) {
    return (
      <>
        <Backdrop />
        <div className="app app--bare">{children}</div>
      </>
    )
  }

  // Qaysi yo'nalish yonib turishi: material sahifasi ikkalasiga ham tegishli,
  // shuning uchun u yerda hech biri majburan yonmaydi.
  const current = {
    grammar: ['topics'],
    phrases: ['phrases'],
    shadowing: ['shadowing'],
    roleplay: ['roleplay'],
  }

  return (
    <>
      <Backdrop />
      <div className="app">
      <nav className="rail">
        <Link to={paths.home()} className="rail__mark">
          <Logo size={30} />
          <span className="rail__wordmark">{t('app.name')}</span>
        </Link>

        {/* Bitta ro'yxat: "Mashq" / "Siz" kabi guruh sarlavhalari yo'q edi —
            to'rt qator ustidagi yorliq ular haqida hech narsa qo'shmasdi, faqat
            panelni ikkiga bo'lardi. */}
        <div className="rail__nav">
          {MODES.map((mode) =>
            mode.ready ? (
              <Link
                key={mode.id}
                to={mode.to()}
                className="navitem"
                aria-current={
                  (current[mode.id] || []).includes(route.name) ? 'page' : undefined
                }
              >
                <span className="navitem__icon">
                  <Icon name={mode.icon} size={18} />
                </span>
                <span className="navitem__label">{t(`mode.${mode.id}`)}</span>
              </Link>
            ) : (
              <div key={mode.id} className="navitem navitem--soon">
                <span className="navitem__icon">
                  <Icon name={mode.icon} size={18} />
                </span>
                <span className="navitem__label">{t(`mode.${mode.id}`)}</span>
                <span className="soon">{t('mode.soon')}</span>
              </div>
            )
          )}

          <Link
            to={paths.progress()}
            className="navitem"
            aria-current={route.name === 'progress' ? 'page' : undefined}
          >
            <span className="navitem__icon">
              <Icon name="progress" size={18} />
            </span>
            <span className="navitem__label">{t('nav.progress')}</span>
          </Link>
        </div>

        <div className="rail__foot">
          <UserMenu />
        </div>
      </nav>

      <main className="page">{children}</main>
      </div>
    </>
  )
}
