import { useI18n } from '../i18n'
import { paths, useRouter } from '../router'

export default function NotFound() {
  const { t } = useI18n()
  const { navigate } = useRouter()
  return (
    <div className="center">
      <h1>{t('error.notfound')}</h1>
      <button type="button" className="btn btn--primary" onClick={() => navigate(paths.home())}>
        {t('nav.home')}
      </button>
    </div>
  )
}
