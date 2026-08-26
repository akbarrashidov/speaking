/**
 * Mavzu (light/dark). Boshlang'ich qiymat index.html dagi kichik skript orqali
 * React yuklanishidan oldin qo'yiladi — shuning uchun sahifa "oq chaqnamaydi".
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

const KEY = 'speaking.theme'
const ThemeContext = createContext(null)

function stored() {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

function resolve() {
  const saved = stored()
  if (saved === 'light' || saved === 'dark') return saved
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(resolve)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  // Foydalanuvchi qo'lda tanlamagan bo'lsa — tizim sozlamasini kuzatamiz.
  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!media) return undefined
    const onChange = () => {
      if (!stored()) setTheme(media.matches ? 'dark' : 'light')
    }
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next = current === 'dark' ? 'light' : 'dark'
      try {
        localStorage.setItem(KEY, next)
      } catch {
        // saqlanmasa ham joriy sessiyada ishlaydi
      }
      return next
    })
  }, [])

  const value = useMemo(() => ({ theme, toggle }), [theme, toggle])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const value = useContext(ThemeContext)
  if (!value) throw new Error('useTheme faqat ThemeProvider ichida ishlaydi')
  return value
}
