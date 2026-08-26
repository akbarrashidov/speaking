import Icon from './Icon'

const ICONS = { info: 'info', warn: 'alert', error: 'error' }

/** Bir xil ko'rinishdagi xabar bloki: ohang → ikonka va rang. */
export default function Banner({ tone = 'info', children, ...rest }) {
  return (
    <div
      className={`banner banner--${tone}`}
      role={tone === 'error' ? 'alert' : undefined}
      {...rest}
    >
      <Icon name={ICONS[tone]} size={18} />
      <div>{children}</div>
    </div>
  )
}
