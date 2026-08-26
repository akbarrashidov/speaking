import { useEffect, useRef, useState } from 'react'

import VoiceOrb from '../components/VoiceOrb'
import Icon from '../components/Icon'
import { startAmbience } from '../audio/ambience'
import { getAudioContext } from '../audio/context'
import { useI18n } from '../i18n'

/**
 * Rol suhbat sahnasi: siz mashq qilmayapsiz, siz KAFEDASIZ.
 *
 * Uch narsa shu hissni beradi va uchalasi ham yengil:
 *   • fon shovqini — brauzerda yasaladi, fayl yuklanmaydi (§audio/ambience);
 *   • sahna foni — CSS gradient + siluetlar, rasm emas;
 *   • qahramon kartasi — kim bilan gaplashayotganingiz doim ko'rinib turadi.
 *
 * Fon AI gapirganda pasayadi: muhit suhbatni bosib qo'ymasligi kerak.
 */
export default function SceneStage({ scene, micState, level, timer, children }) {
  const { t } = useI18n()
  const ambienceRef = useRef(null)
  const [muted, setMuted] = useState(false)

  useEffect(() => {
    if (!scene?.ambience || scene.ambience === 'none') return undefined
    let stopped = false
    try {
      const ambience = startAmbience(getAudioContext(), scene.ambience)
      if (stopped) ambience?.stop()
      else ambienceRef.current = ambience
    } catch (err) {
      console.warn('Fon muhiti yoqilmadi:', err)
    }
    return () => {
      stopped = true
      ambienceRef.current?.stop()
      ambienceRef.current = null
    }
  }, [scene?.ambience])

  // AI gapirganda fon pasayadi, o'quvchi navbatida qaytadi.
  useEffect(() => {
    ambienceRef.current?.duck(micState === 'ai_speaking')
  }, [micState])

  useEffect(() => {
    ambienceRef.current?.setEnabled(!muted)
  }, [muted])

  const persona = scene?.persona || ''
  const name = persona.split(',')[0]
  const role = persona.includes(',') ? persona.slice(persona.indexOf(',') + 1).trim() : ''

  return (
    <aside className={`stage stage--scene scene--${scene?.ambience || 'none'}`}>
      <div className="scene__art" aria-hidden="true">
        <span className="scene__glow" />
        <span className="scene__figures" />
      </div>

      <div className="scene__who">
        <span className="scene__avatar">{(name || '?').trim().charAt(0)}</span>
        <div>
          <div className="scene__name">{name || t('roleplay.back')}</div>
          {role && <div className="scene__role">{role}</div>}
        </div>
        <button
          type="button"
          className="scene__mute"
          onClick={() => setMuted((m) => !m)}
          aria-pressed={muted}
          title={t(muted ? 'scene.sound.on' : 'scene.sound.off')}
        >
          <Icon name={muted ? 'soundOff' : 'sound'} size={15} />
        </button>
      </div>

      {scene?.setting && <p className="scene__setting">{scene.setting}</p>}

      <VoiceOrb level={micState === 'listening' ? level : 0.08} state={micState} />
      {timer}
      {children}
    </aside>
  )
}
