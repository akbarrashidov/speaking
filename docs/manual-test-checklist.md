# Qo'lda test checklist'i (§11)

Avtomatik testlar qamrab ololmaydigan narsalar: haqiqiy mikrofon, haqiqiy brauzer,
haqiqiy tarmoq. Har relizdan oldin shu ro'yxat bo'yicha o'tiladi.

**Eng xavfli nishon — iOS Safari.** Uni birinchi tekshiring: mikrofon ruxsati va
audio playback faqat foydalanuvchi bosishi ichida ochiladi.

---

## 0. Tayyorgarlik

- [ ] `.env` to'ldirilgan: `JWT_SECRET`, `GEMINI_API_KEY`, `ANALYSIS_API_KEY`
- [ ] Domen HTTPS bilan ishlayapti (mikrofon xavfsiz kontekst talab qiladi)
- [ ] `seed_content` yuklangan, admin'da 25 mavzu `published` holatida
- [ ] Test foydalanuvchisi `free` tarifda, bugungi kvota sarflanmagan

---

## 0.1 Kirish (auth)

| # | Qadam | Kutilgan natija |
|---|---|---|
| 0.1.1 | Ro'yxatdan o'ting (yangi email) | Akkaunt yaratiladi, darhol bosh sahifaga o'tadi |
| 0.1.2 | Xuddi shu email bilan yana ro'yxatdan o'ting | "Bu email allaqachon ro'yxatdan o'tgan" |
| 0.1.3 | 7 belgili parol kiriting | Parol qisqaligi haqida maydon xatosi |
| 0.1.4 | Noto'g'ri parol bilan kiring | "Email yoki parol noto'g'ri" |
| 0.1.5 | Mavjud bo'lmagan email bilan kiring | **Xuddi shu** xabar (email borligi oshkor bo'lmasin) |
| 0.1.6 | Ketma-ket 12 marta noto'g'ri kiring | Chegara ishlaydi, keyinroq urinish so'raladi |
| 0.1.7 | Kirgach sahifani yangilang | Sessiya saqlanadi, qayta kirish so'ralmaydi |
| 0.1.8 | "Chiqish" ni bosing | Kirish sahifasiga qaytadi, orqaga tugmasi ichkariga kiritmaydi |

## 1. iOS Safari — mikrofon va playback (KRITIK)

| # | Qadam | Kutilgan natija |
|---|---|---|
| 1.1 | Ilovani HTTPS manzilda oching | Bosh sahifa ochiladi, daraja va kvota ko'rinadi |
| 1.2 | Mavzu → Material ekrani | Matn o'qish ≤ 60 soniya, bitta CTA ko'rinadi |
| 1.3 | "Gapirishni boshlash" ni bosing | Brauzer mikrofon ruxsatini **shu bosishda** so'raydi |
| 1.4 | Ruxsat bering | Sessiya ekrani ochiladi, AI birinchi savolni **ovoz bilan** beradi |
| 1.5 | Ruxsatni rad eting (alohida urinish) | Tushunarli o'zbekcha xato xabari, ilova qotib qolmaydi |
| 1.6 | Javob bering | To'lqin ovoz kuchiga qarab jonli harakatlanadi |
| 1.7 | AI gapirayotganda uning ustidan gapiring | AI ovozi **darhol** to'xtaydi (barge-in) |

> Agar 1.4 da ovoz chiqmasa — bu autoplay siyosati muammosi. Audio konteksti
> `prepareAudio()` da, aynan tap ichida ochilishi shart (`frontend/src/audio/bootstrap.js`).

## 2. Drill sikli (A1)

| # | Qadam | Kutilgan natija |
|---|---|---|
| 2.1 | Savolga to'g'ri javob bering | Qisqa tasdiq, keyin yangi savol |
| 2.2 | Ataylab xato javob bering | Qisqa rag'batlantirish, **xuddi shu savol** qayta beriladi |
| 2.3 | Yana xato javob bering | AI to'g'ri gapni aytadi, "Repeat after me" deydi |
| 2.4 | Takrorlang | AI xuddi shu savolni yana beradi |
| 2.5 | Uchinchi marta xato | Keyingi savolga o'tadi (3+ urinish BO'LMASLIGI shart) |
| 2.6 | Tushunarsiz gapiring (shovqin) | "Sorry, could you say that again?" |
| 2.7 | Butun sessiya davomida | AI grammatikani TUSHUNTIRMAYDI, ma'ruza qilmaydi |
| 2.8 | Gapirish nisbati | Sessiya vaqtining asosiy qismida siz gapirasiz |

## 3. Guided conversation (B1)

| # | Qadam | Kutilgan natija |
|---|---|---|
| 3.1 | B1 mavzusini boshlang | AI savol beradi, javobdan keyin follow-up so'raydi |
| 3.2 | Qisqa javob bering | AI ko'proq gapirishga undaydi ("Why?", "Tell me more") |
| 3.3 | Kichik grammatik xato qiling | Sessiya ichida TUZATILMAYDI (feedbackda chiqadi) |
| 3.4 | Tushunib bo'lmaydigan gap ayting | Bitta qatorli recast, keyin darhol davom etadi |

## 4. Uzilish va reconnect (§5.3)

| # | Qadam | Kutilgan natija |
|---|---|---|
| 4.1 | Sessiya o'rtasida boshqa ilovaga o'ting, 10s kuting, qayting | "Qayta ulanmoqda" → sessiya davom etadi, taymer **nolga qaytmaydi** |
| 4.2 | Ekranni o'chiring, 30s kuting, yoqing | Xuddi shunday tiklanadi |
| 4.3 | Tabni yoping, 90s kuting, qayta oching | Sessiya yopilgan, feedback kartasi tayyor (qisman transkript bilan) |
| 4.4 | Sessiya o'rtasida aviarejimni yoqing | 3 marta avto-retry, keyin tushunarli xato xabari |
| 4.5 | Bir sessiyani ikkita qurilmada oching | Ikkinchisi rad etiladi, birinchisi buzilmaydi |

## 5. Limitlar va kvota (§4.9)

| # | Qadam | Kutilgan natija |
|---|---|---|
| 5.1 | Free sessiyani 5 daqiqagacha davom ettiring | AI xushmuomala yakunlovchi gap aytadi, sessiya yopiladi |
| 5.2 | Xuddi shu kuni yangi sessiya boshlang | Kvota xatosi + qachon ochilishi ko'rsatiladi |
| 5.3 | Bosh sahifa | Qolgan kvota to'g'ri ko'rinadi |
| 5.4 | Admin'da premium qiling | Cheksiz sessiya, 15 daqiqa limit |
| 5.5 | Toshkent vaqti bo'yicha yarim tundan keyin | Kvota tiklanadi |

## 3.5 Podkaska — o'quvchi qotib qolganda (§Faza 4)

| # | Qadam | Kutilgan natija |
|---|---|---|
| 3.5.1 | Savol berilgach **ataylab jim turing** | ~7s (A1) dan keyin AI savolni sekinroq takrorlaydi |
| 3.5.2 | Yana jim turing | AI gap boshini beradi ("Start with: I went to…") va **ekranda ham** chiqadi |
| 3.5.3 | Yana jim turing | To'liq javob + "Repeat after me", ekranda matn bilan |
| 3.5.4 | Zinapoya davomida gapira boshlang | Podkaska **darhol** to'xtaydi, ekrandagi matn yo'qoladi |
| 3.5.5 | Bitta savolda ikki marta to'liq zinapoyadan o'ting | Sessiya osilib qolmaydi — keyingi savolga o'tadi |

## 3.6 Dinamik suhbat va daraja (§Faza 5, 6)

| # | Qadam | Kutilgan natija |
|---|---|---|
| 3.6.1 | B1 mavzusida to'liq javob bering | Follow-up savol aynan siz aytgan narsaga bog'lanadi |
| 3.6.2 | Ketma-ket bir necha marta bir so'z bilan javob bering | Savol strukturani majburlaydigan shaklga o'tadi |
| 3.6.3 | Uzoq, aniq va ravon gapiring (3+ javob) | AI tezroq va hayajonliroq gapiradi, uzunroq javob talab qiladi |
| 3.6.4 | Keyin ataylab qiynaling | AI sekinlashadi, ohangi bosiqroq bo'ladi |
| 3.6.5 | Admin → Savollar → `source=generated, status=draft` | Sessiyada yaratilgan savollar review uchun turibdi |

## 6. Feedback kartasi (§4.10, §Faza 7)

| # | Qadam | Kutilgan natija |
|---|---|---|
| 6.1 | Sessiyani yakunlang | "Tayyorlanmoqda" skeleton, keyin karta |
| 6.2 | Metrikalar | Davomiylik, talk-time %, WPM, aniqlik — real qiymatlar, nol emas |
| 6.3 | Tuzatishlar | Maksimum 5 ta, o'quvchi gapi → tuzatilgan gap |
| 6.4 | **Takrorlangan xatolar** | Naqsh + necha marta + o'zbekcha izoh (grammatik atamasiz) |
| 6.5 | **Keyingi mashqlar** | 3 ta inglizcha gap, aynan qilingan xatoga mos |
| 6.6 | Xulosa | **O'zbekcha**, rag'batlantiruvchi, bitta o'sish nuqtasi |
| 6.7 | CTA | Mavzu holatiga mos ("Keyingi mavzu" yoki "Takrorlash") |
| 6.8 | 2+ sessiyadan keyin `GET /api/progress/report` | Sessiyalararo naqshlar + o'zbekcha xulosa |

## 7. Progress va routing (§4.7)

| # | Qadam | Kutilgan natija |
|---|---|---|
| 7.1 | Bitta mavzuda 2 ta yaxshi sessiya (≥80%) | Mavzu `mastered`, keyingisi ochiladi |
| 7.2 | 2 ta zaif sessiya (<50%) | Yumshoq taklif: materialni qayta o'qish |
| 7.3 | 3 ta a'lo sessiya (≥85%, tez javob) | Daraja ko'tarish taklifi banneri |
| 7.4 | Taklifni rad eting | Daraja O'ZGARMAYDI (hech qachon avtomatik emas) |

## 8. Platformalar

- [ ] **iOS Safari** — 1–7 bo'limlar to'liq
- [ ] **Android Chrome** — AudioWorklet ishlaydi, ovoz sifati yaxshi
- [ ] **Desktop Chrome/Firefox** — mikrofon, playback va klaviatura bilan navigatsiya
- [ ] **Mobil internet (4G)** — sessiya uzilmasdan o'tadi, latency sezilarli oshmaydi
- [ ] **Dark mode** — barcha ekranlar o'qiladi (mavzu almashtirgich foydalanuvchi menyusida)
- [ ] **Brauzer orqaga tugmasi** — har ekranda kutilganidek ishlaydi
- [ ] **Desktop kenglik** — layout cho'zilib ketmaydi, matn qatori o'qish uchun qulay
- [ ] Barcha UI matnlari o'zbekcha, kesilgan matn yo'q

## 9. Xavfsizlik (§11)

- [ ] Brauzer Network panelida `GEMINI_API_KEY` **ko'rinmaydi**
- [ ] Client loglarida transkript ma'lumotlari yo'q
- [ ] Boshqa foydalanuvchining `session_id` si bilan WS ochib bo'lmaydi (4403)
- [ ] Tokensiz WS ulanishi rad etiladi (4401)
- [ ] Muddati o'tgan JWT bilan API 401 qaytaradi va ilova kirish sahifasiga qaytaradi
- [ ] Xom audio DB'da saqlanmaydi (faqat transkript)
- [ ] Parol javoblarda va loglarda ko'rinmaydi
- [ ] Sayt boshqa domendagi iframe ichida ochilmaydi (X-Frame-Options: DENY)

## 10. Admin (§9)

- [ ] Draft savollar bo'yicha filtr ishlaydi, sifat tekshiruvi ustuni ko'rinadi
- [ ] Approve/reject action'lari ishlaydi
- [ ] Sessiya brauzerida transkript, metrikalar, baholashlar ko'rinadi
- [ ] Tasdiqlangan savoli yo'q mavzuni nashr qilib bo'lmaydi

---

## Narx o'lchash (§Faza 0/8)

Har sessiyaning haqiqiy narxi `session_metrics.cost_usd` da. Optimizatsiya
raqam bilan isbotlanadi — taxmin bilan emas.

```sql
-- Sessiyaning o'rtacha narxi va tarkibi
SELECT round(avg(cost_usd)::numeric, 5) AS avg_usd,
       round(avg((usage_breakdown->>'live_usd')::numeric), 5) AS live,
       round(avg((usage_breakdown->>'llm_usd')::numeric), 5)  AS llm,
       round(avg((usage_breakdown->>'audio_in_tokens')::numeric)/25, 1)  AS audio_in_s,
       round(avg((usage_breakdown->>'audio_out_tokens')::numeric)/25, 1) AS audio_out_s
FROM session_metrics WHERE cost_usd > 0;
```

- [ ] `audio_in_s` sessiya davomiyligidan **sezilarli kam** (mikrofon darvozasi ishlayapti)
- [ ] `audio_out_s` `audio_in_s` dan kichik (o'quvchi ko'proq gapiryapti)
- [ ] `llm` `live` dan ancha kichik (miya arzon, ovoz qimmat)
- [ ] Loglarda `session_cost session_id=… usd=…` qatori bor

Brauzer Network panelida: o'quvchi jim turganda `audio_chunk` xabarlari
**oqmasligi** kerak.

Gemini Live imkoniyatlarini haqiqiy API bilan tekshirish:

```bash
python scripts/live_spike.py            # ~$0.01
```

## Latency o'lchash (§11: median < 2s)

Sessiyadan keyin:

```sql
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY avg_response_latency_ms)
FROM session_metrics WHERE avg_response_latency_ms > 0;
```

2000 ms dan yuqori bo'lsa: audio chunk hajmi (100 ms), tarmoq RTT va Gemini
javob vaqtini `session_id` bo'yicha loglardan tekshiring.
