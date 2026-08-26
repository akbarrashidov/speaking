import { useI18n } from '../i18n'

/**
 * Bitta navbat uchun grammatik tuzatishlar: aytilgani ustidan chizilgan,
 * to'g'risi qalin. Tuzatish gap aytilganidan bir necha soniya keyin keladi,
 * shuning uchun animatsiyasiz qo'shiladi — o'qiyotgan odamning ko'zi sakramasin.
 */
function Fixes({ data }) {
  const { t } = useI18n()
  if (!data) return null

  if (!data.errors?.length) {
    return (
      <p className="fixes fixes--clean">
        <span aria-hidden="true">✓</span> {t('session.clean')}
      </p>
    )
  }

  return (
    <ul className="fixes" style={{ listStyle: 'none', margin: '7px 0 0', padding: '9px 14px' }}>
      {data.errors.map((err, i) => (
        <li className="fix" key={`${err.span}-${i}`}>
          <del className="fix__from">{err.span}</del>
          <span aria-hidden="true" className="muted">
            →
          </span>
          <ins className="fix__to" style={{ textDecoration: 'none' }}>
            {err.fix}
          </ins>
        </li>
      ))}
    </ul>
  )
}

/** AI navbati: inglizcha gap, ostida o'quvchi tilidagi tarjimasi. */
function AiMessage({ text, translation, partial = false }) {
  const { t } = useI18n()
  return (
    <div className={`msg msg--ai${partial ? ' msg--partial' : ''}`}>
      <div className="msg__who">{t('session.partner')}</div>
      <p className="msg__text">{text}</p>
      {translation && <p className="msg__tr">{translation}</p>}
    </div>
  )
}

/**
 * O'quvchi navbati: SO'ZMA-SO'Z aytgani, ostida tuzatish.
 *
 * Tarjima bu yerda yo'q — o'quvchi o'z gapining ma'nosini biladi; ekranda
 * kerak bo'lgani AI nima deganini tushunish.
 */
function LearnerMessage({ text, correction, partial = false }) {
  const { t } = useI18n()
  return (
    <div className={`msg msg--learner${partial ? ' msg--partial' : ''}`}>
      <div className="msg__who">{t('session.you')}</div>
      <p className="msg__text">{text}</p>
      <Fixes data={correction} />
    </div>
  )
}

export default function Transcript({ items, partial = null, corrections = {}, translations = {} }) {
  return (
    <>
      {items.map((turn) =>
        turn.speaker === 'learner' ? (
          <LearnerMessage key={turn.idx} text={turn.text} correction={corrections[turn.idx]} />
        ) : (
          <AiMessage
            key={turn.idx}
            text={turn.text}
            translation={translations[turn.idx] || turn.text_uz || ''}
          />
        )
      )}
      {partial &&
        (partial.speaker === 'learner' ? (
          <LearnerMessage text={partial.text} partial />
        ) : (
          <AiMessage text={partial.text} partial />
        ))}
    </>
  )
}
