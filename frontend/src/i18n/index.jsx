/**
 * Til qatlami.
 *
 * Til uch joyda saqlanadi va ular bir-birini quvvatlaydi:
 *   1. `localStorage` — sahifa yangilanganda darhol to'g'ri til bilan ochiladi;
 *   2. foydalanuvchi profili (backend) — boshqa qurilmada ham o'sha til;
 *   3. `<html lang>` — brauzer va ekran o'quvchilari uchun.
 *
 * Til faqat interfeys emas: mavzu nomi, qoida va tarjimalar serverdan profil
 * tiliga qarab keladi. Shuning uchun bu yerda `contentVersion` ham bor —
 * til almashganda ekranlar shunga qarab ma'lumotni qayta tortadi va sahifani
 * yangilash kerak bo'lmaydi.
 *
 * Backend uchun ham muhim: o'quvchi tili sessiyaga uzatiladi, chunki AI
 * gapining tarjimasi va sessiya yakunidagi tahlil o'sha tilda yoziladi.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import { DEFAULT_LANGUAGE, LANGUAGES, MESSAGES } from './messages'

const KEY = 'speaking.lang'
const I18nContext = createContext(null)

export const LANGUAGE_CODES = LANGUAGES.map((l) => l.code)

function stored() {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

function resolve() {
  const saved = stored()
  if (LANGUAGE_CODES.includes(saved)) return saved
  const browser = (navigator.language || '').slice(0, 2).toLowerCase()
  if (browser === 'ru') return 'ru'
  return DEFAULT_LANGUAGE
}

/** `{name}` shaklidagi o'rinlarni to'ldiradi. */
function fill(template, vars) {
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (whole, key) =>
    vars[key] === undefined || vars[key] === null ? whole : String(vars[key])
  )
}

export function I18nProvider({ children }) {
  const [lang, setLang] = useState(resolve)
  const [contentVersion, setContentVersion] = useState(0)

  // Serverdagi til yangilangach chaqiriladi — ekranlar uchun "qayta torting"
  // signali. Raqam o'sadi, ya'ni useEffect bog'lanishi oddiy qoladi.
  const refetchContent = useCallback(() => setContentVersion((v) => v + 1), [])

  useEffect(() => {
    document.documentElement.lang = lang
    try {
      localStorage.setItem(KEY, lang)
    } catch {
      // Maxfiylik rejimi — xotiradagi qiymat bilan ishlayveramiz.
    }
  }, [lang])

  const t = useCallback(
    (key, vars) => {
      const table = MESSAGES[lang] || MESSAGES[DEFAULT_LANGUAGE]
      const value = table[key] ?? MESSAGES[DEFAULT_LANGUAGE][key]
      // Kalit topilmasa kalitning o'zi ko'rinadi — bu tarjima yetishmayotganini
      // yashirmaydi, ya'ni sinovda darrov ko'zga tashlanadi.
      return value === undefined ? key : fill(value, vars)
    },
    [lang]
  )

  const value = useMemo(
    () => ({ lang, setLang, t, languages: LANGUAGES, contentVersion, refetchContent }),
    [lang, t, contentVersion, refetchContent]
  )
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n() {
  const value = useContext(I18nContext)
  if (!value) throw new Error('useI18n faqat I18nProvider ichida ishlaydi')
  return value
}

/** Qisqa yo'l: faqat tarjima funksiyasi kerak bo'lganda. */
export function useT() {
  return useI18n().t
}
