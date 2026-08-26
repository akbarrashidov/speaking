/**
 * Kichik History API router — brauzerning orqaga/oldinga tugmalari ishlashi va
 * har ekranning o'z manzili bo'lishi uchun. Tashqi kutubxona qo'shilmaydi (§8).
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'

const RouterContext = createContext(null)

const ROUTES = [
  ['home', /^\/$/],
  ['auth', /^\/kirish$/],
  ['onboarding', /^\/tanishuv$/],
  ['placement', /^\/daraja$/],
  ['topics', /^\/mavzular$/],
  ['material', /^\/mavzular\/(\d+)$/, ['topicId']],
  ['phrases', /^\/iboralar$/],
  ['shadowing', /^\/shadowing$/],
  ['roleplay', /^\/rol-suhbat$/],
  ['session', /^\/sessiya\/([\w-]+)$/, ['sessionId']],
  ['feedback', /^\/natija\/([\w-]+)$/, ['sessionId']],
  ['progress', /^\/progress$/],
]

export const paths = {
  home: () => '/',
  auth: () => '/kirish',
  onboarding: () => '/tanishuv',
  placement: () => '/daraja',
  topics: () => '/mavzular',
  material: (topicId) => `/mavzular/${topicId}`,
  phrases: () => '/iboralar',
  shadowing: () => '/shadowing',
  roleplay: () => '/rol-suhbat',
  session: (sessionId) => `/sessiya/${sessionId}`,
  feedback: (sessionId) => `/natija/${sessionId}`,
  progress: () => '/progress',
}

export function matchRoute(pathname) {
  for (const [name, pattern, keys = []] of ROUTES) {
    const found = pattern.exec(pathname)
    if (!found) continue
    const params = {}
    keys.forEach((key, i) => {
      params[key] = found[i + 1]
    })
    return { name, params }
  }
  return { name: 'notfound', params: {} }
}

function currentLocation() {
  return {
    path: window.location.pathname,
    state: window.history.state?.appState ?? null,
  }
}

export function RouterProvider({ children }) {
  const [location, setLocation] = useState(currentLocation)

  useEffect(() => {
    const onPop = () => setLocation(currentLocation())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const navigate = useCallback((to, { replace = false, state = null } = {}) => {
    window.history[replace ? 'replaceState' : 'pushState']({ appState: state }, '', to)
    setLocation({ path: to, state })
    window.scrollTo(0, 0)
  }, [])

  const back = useCallback(() => window.history.back(), [])

  const value = useMemo(
    () => ({ ...location, route: matchRoute(location.path), navigate, back }),
    [location, navigate, back]
  )

  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>
}

export function useRouter() {
  const value = useContext(RouterContext)
  if (!value) throw new Error('useRouter faqat RouterProvider ichida ishlaydi')
  return value
}

/** Oddiy havola — Cmd/Ctrl+klik brauzerning odatdagi xatti-harakatini saqlaydi. */
export function Link({ to, state, children, ...rest }) {
  const { navigate } = useRouter()
  return (
    <a
      href={to}
      onClick={(event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return
        event.preventDefault()
        navigate(to, { state })
      }}
      {...rest}
    >
      {children}
    </a>
  )
}
