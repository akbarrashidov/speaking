import { useEffect } from 'react'

import AuthScreen from './auth/AuthScreen'
import { AuthProvider, useAuth } from './auth/AuthContext'
import Shell from './components/Shell'
import { I18nProvider, useI18n } from './i18n'
import { RouterProvider, paths, useRouter } from './router'
import Feedback from './screens/Feedback'
import Home from './screens/Home'
import Material from './screens/Material'
import NotFound from './screens/NotFound'
import Onboarding from './screens/Onboarding'
import Placement from './screens/Placement'
import Progress from './screens/Progress'
import SessionScreen from './screens/Session'
import Track from './screens/Track'
import { ThemeProvider } from './theme'

function Splash() {
  const { t } = useI18n()
  return (
    <div className="center">
      <p className="muted">{t('app.loading')}</p>
    </div>
  )
}

/** Profildagi til interfeys tilini belgilaydi — boshqa qurilmada ham o'sha til. */
function LanguageSync() {
  const { user } = useAuth()
  const { lang, setLang } = useI18n()
  useEffect(() => {
    if (user?.language_code && user.language_code !== lang) setLang(user.language_code)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.language_code])
  return null
}

function Routes() {
  const { status, user } = useAuth()
  const { t } = useI18n()
  const { route, path, state, navigate } = useRouter()

  // Manzil holatga mos bo'lsin: mehmon → /kirish, kirgan → /kirish dan chiqish.
  useEffect(() => {
    if (status === 'anon' && path !== paths.auth()) navigate(paths.auth(), { replace: true })
    if (status === 'ok' && path === paths.auth()) navigate(paths.home(), { replace: true })
  }, [status, path, navigate])

  if (status === 'loading') return <Splash />
  if (status === 'anon') return <AuthScreen />

  // Ro'yxatdan o'tish ikki qadam, undan keyin bitta suhbat — va uchalasi
  // KETMA-KET. Shart shu yerda, bitta joyda: har ekran o'zini o'zi
  // tekshirishga urinsa, yarim to'ldirilgan profil bilan ilovaga kirib
  // ketadigan yo'l albatta topiladi.
  //
  // Sessiya va natija ekranlari ISTISNO, va ikkinchisi ayniqsa muhim.
  //
  // Daraja aniqlash suhbatining o'zi sessiya ekranida ketadi. Uning natijasi
  // esa fon vazifasida hisoblanadi (§practice/tasks.py), ya'ni `placement_done`
  // suhbat tugagan zahoti emas, bir necha soniyadan keyin true bo'ladi.
  // Natija ekrani ham to'silsa, o'quvchi suhbatni tugatib, yana boshlash
  // ekraniga qaytib tushardi — va shu aylanadan chiqolmasdi. Natija ekrani
  // hisob tayyor bo'lganda profilni o'zi qayta tortadi (§Feedback.jsx).
  const UNGATED = ['session', 'feedback']
  if (user && !UNGATED.includes(route.name)) {
    if (!user.onboarding_completed) return <Shell bare><Onboarding /></Shell>
    if (!user.placement_done) return <Shell bare><Placement /></Shell>
  }

  // Sessiya ekrani to'liq ekranni egallaydi — qobiqsiz.
  if (route.name === 'session') {
    if (!state?.session) {
      return (
        <Shell>
          <div className="center">
            <h1>{t('session.notfound')}</h1>
            <p className="muted">{t('session.notfound.hint')}</p>
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => navigate(paths.home(), { replace: true })}
            >
              {t('nav.home')}
            </button>
          </div>
        </Shell>
      )
    }
    return (
      <Shell bare>
        <SessionScreen
          session={state.session}
          topicTitle={state.topicTitle}
          targetStructure={state.targetStructure}
        />
      </Shell>
    )
  }

  return (
    <Shell>
      {route.name === 'home' && <Home />}
      {route.name === 'topics' && <Track track="grammar" />}
      {route.name === 'phrases' && <Track track="phrases" />}
      {route.name === 'shadowing' && <Track track="shadowing" />}
      {route.name === 'roleplay' && <Track track="roleplay" />}
      {route.name === 'material' && (
        <Material topicId={route.params.topicId} />
      )}
      {route.name === 'feedback' && <Feedback sessionId={route.params.sessionId} />}
      {route.name === 'progress' && <Progress />}
      {route.name === 'notfound' && <NotFound />}
      {route.name === 'auth' && <Splash />}
      {route.name === 'onboarding' && <Onboarding />}
      {route.name === 'placement' && <Placement />}
    </Shell>
  )
}

export default function App() {
  return (
    <I18nProvider>
      <ThemeProvider>
        <RouterProvider>
          <AuthProvider>
            <LanguageSync />
            <Routes />
          </AuthProvider>
        </RouterProvider>
      </ThemeProvider>
    </I18nProvider>
  )
}
