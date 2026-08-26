import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import { api, authEvents, clearSession, hasValidToken, setSession, shouldRefresh } from '../api'
import { useI18n } from '../i18n'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [status, setStatus] = useState('loading') // loading | anon | ok
  const [me, setMe] = useState(null)
  const { setLang, refetchContent } = useI18n()
  // Shu tabda tanlangan til. Ekranlar `refreshMe()` ni fon rejimida chaqiradi;
  // bosishdan oldin yo'lga chiqqan javob eski tilni olib kelib, tanlovni
  // bekor qilardi — til bir bosishda almashmasligining sababi shu edi.
  const chosen = useRef(null)

  const refreshMe = useCallback(async () => {
    const data = await api.me()
    const fresh =
      chosen.current && data?.user && data.user.language_code !== chosen.current
        ? { ...data, user: { ...data.user, language_code: chosen.current } }
        : data
    setMe(fresh)
    return fresh
  }, [])

  const adopt = useCallback(
    async (session) => {
      setSession(session)
      const data = await refreshMe()
      setStatus('ok')
      return data
    },
    [refreshMe]
  )

  // Tilni almashtirish — bitta amal, uch qadam:
  //   1. interfeys darhol (kutish yo'q),
  //   2. profil serverda saqlanadi — mavzu nomi, qoida va tarjimalar shu tilda
  //      qaytadi, AI gapining tarjimasi va sessiya tahlili ham,
  //   3. saqlangach ekranlar server matnlarini qayta tortadi.
  const setLanguage = useCallback(
    async (language) => {
      chosen.current = language
      setLang(language)
      setMe((prev) => (prev ? { ...prev, user: { ...prev.user, language_code: language } } : prev))
      try {
        await api.setLanguage(language)
      } catch {
        // Tarmoq yiqilsa interfeys baribir tanlangan tilda qoladi; server
        // matnlari eski tilda ko'rinaveradi — bu yolg'on ko'rsatishdan yaxshi.
      }
      refetchContent()
    },
    [setLang, refetchContent]
  )

  const signOut = useCallback(() => {
    chosen.current = null
    clearSession()
    setMe(null)
    setStatus('anon')
  }, [])

  // Ilova ochilganda: saqlangan token bo'lsa profilni tortamiz.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      if (!hasValidToken()) {
        clearSession()
        if (!cancelled) setStatus('anon')
        return
      }
      try {
        if (shouldRefresh()) setSession(await api.refresh())
        await refreshMe()
        if (!cancelled) setStatus('ok')
      } catch {
        if (!cancelled) {
          clearSession()
          setStatus('anon')
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [refreshMe])

  // Token muddati server tomonda tugasa — darhol chiqaramiz.
  useEffect(() => {
    const onUnauthorized = () => {
      setMe(null)
      setStatus('anon')
    }
    authEvents.addEventListener('unauthorized', onUnauthorized)
    return () => authEvents.removeEventListener('unauthorized', onUnauthorized)
  }, [])

  // Uzoq sessiyalarda tokenni jimgina yangilab turamiz.
  useEffect(() => {
    if (status !== 'ok') return undefined
    const timer = setInterval(
      async () => {
        if (!shouldRefresh()) return
        try {
          setSession(await api.refresh())
        } catch {
          // 401 bo'lsa yuqoridagi kuzatuvchi ishga tushadi
        }
      },
      5 * 60_000
    )
    return () => clearInterval(timer)
  }, [status])

  const value = useMemo(
    () => ({
      status,
      me,
      user: me?.user || null,
      quota: me?.quota || null,
      refreshMe,
      setLanguage,
      signOut,
      signIn: async (payload) => adopt(await api.login(payload)),
      signUp: async (payload) => adopt(await api.register(payload)),
    }),
    [status, me, refreshMe, setLanguage, signOut, adopt]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth faqat AuthProvider ichida ishlaydi')
  return value
}
