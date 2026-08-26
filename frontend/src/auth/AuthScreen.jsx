import { useState } from 'react'

import { EqualizerMark } from '../components/Art'
import Banner from '../components/Banner'
import Icon from '../components/Icon'
import Logo from '../components/Logo'
import Steps from '../components/Steps'
import { useI18n } from '../i18n'
import { useAuth } from './AuthContext'

export default function AuthScreen() {
  const { signIn, signUp } = useAuth()
  const { t, lang, setLang, languages } = useI18n()
  const [mode, setMode] = useState('login') // login | register
  const [values, setValues] = useState({ email: '', password: '', first_name: '' })
  const [fieldErrors, setFieldErrors] = useState({})
  const [formError, setFormError] = useState('')
  const [busy, setBusy] = useState(false)

  const isRegister = mode === 'register'
  // Ro'yxatdan o'tish ikki qadam. Birinchisi shu forma, ikkinchisi profil
  // savollari (§screens/Onboarding.jsx) — o'quvchi oldinda nima borligini
  // bilib turishi kerak, aks holda ikkinchi ekran kutilmagan to'siq bo'lib
  // ko'rinadi va tashlab ketiladi.

  const update = (key) => (event) => {
    setValues((v) => ({ ...v, [key]: event.target.value }))
    setFieldErrors((e) => ({ ...e, [key]: null }))
    setFormError('')
  }

  const switchMode = (next) => {
    setMode(next)
    setFieldErrors({})
    setFormError('')
  }

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setFormError('')
    setFieldErrors({})
    try {
      const payload = { email: values.email.trim(), password: values.password, language: lang }
      if (isRegister) await signUp({ ...payload, first_name: values.first_name.trim() })
      else await signIn(payload)
    } catch (err) {
      if (err.fields) setFieldErrors(err.fields)
      if (err.code === 'invalid_credentials') setFormError(t('auth.error.credentials'))
      else if (err.status === 429) setFormError(t('auth.error.throttled'))
      else if (err.code === 'network_error') setFormError(t('error.network'))
      else if (!err.fields) setFormError(err.message || t('auth.error.generic'))
      setBusy(false)
    }
  }

  const fieldError = (key) => {
    const value = fieldErrors[key]
    if (!value) return null
    return Array.isArray(value) ? value[0] : value
  }

  return (
    <div className="auth">
      <section className="auth__poster">
        <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
          {/* Ilgari bu yerda oq shaffof nishon turardi — brend sirti OCH
              bo'lgach u och pastel fonda deyarli ko'rinmay qolgan edi. */}
          <Logo size={36} />
          <span style={{ fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: 22 }}>
            {t('app.name')}
          </span>
        </div>

        <div>
          <h1>{t('auth.tagline')}</h1>
          <p className="auth__lede">{t('auth.lede')}</p>

          <div className="auth__points">
            <div className="auth__point">
              <span>
                <Icon name="mic" size={17} />
              </span>
              {t('auth.point.speak')}
            </div>
            <div className="auth__point">
              <span>
                <Icon name="check" size={17} />
              </span>
              {t('auth.point.fix')}
            </div>
            <div className="auth__point">
              <span>
                <Icon name="progress" size={17} />
              </span>
              {t('auth.point.track')}
            </div>
          </div>
        </div>

        <EqualizerMark className="auth__eq" />
      </section>

      <section className="auth__form">
        <div className="langswitch" style={{ alignSelf: 'flex-end', marginBottom: 24 }}>
          {languages.map((item) => (
            <button
              key={item.code}
              type="button"
              aria-pressed={lang === item.code}
              onClick={() => setLang(item.code)}
            >
              {item.short}
            </button>
          ))}
        </div>

        <div className="segmented" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={!isRegister}
            onClick={() => switchMode('login')}
          >
            {t('auth.login')}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={isRegister}
            onClick={() => switchMode('register')}
          >
            {t('auth.register')}
          </button>
        </div>

        <form onSubmit={submit} noValidate>
          {isRegister && <Steps total={2} current={1} />}
          {isRegister && (
            <div className="field">
              <label htmlFor="first_name">{t('auth.name')}</label>
              <input
                id="first_name"
                name="first_name"
                autoComplete="given-name"
                value={values.first_name}
                onChange={update('first_name')}
              />
              {fieldError('first_name') && (
                <span className="field__error">
                  {fieldError('first_name')}
                </span>
              )}
            </div>
          )}

          <div className="field">
            <label htmlFor="email">{t('auth.email')}</label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={values.email}
              onChange={update('email')}
            />
            {fieldError('email') && (
              <span className="field__error">
                {fieldError('email')}
              </span>
            )}
          </div>

          <div className="field">
            <label htmlFor="password">{t('auth.password')}</label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete={isRegister ? 'new-password' : 'current-password'}
              required
              value={values.password}
              onChange={update('password')}
            />
            <span className="muted" style={{ fontSize: 12.5 }}>
              {isRegister ? t('auth.password.hint') : ''}
            </span>
            {fieldError('password') && (
              <span className="field__error">
                {fieldError('password')}
              </span>
            )}
          </div>

          {formError && <Banner tone="error">{formError}</Banner>}

          <button
            type="submit"
            className="btn btn--primary btn--lg"
            disabled={busy}
            style={{ width: '100%', marginTop: 18 }}
          >
            {busy ? t('auth.busy') : isRegister ? t('auth.submit.register') : t('auth.submit.login')}
          </button>
        </form>
      </section>
    </div>
  )
}
