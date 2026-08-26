/**
 * Sahifa orqasidagi rangli "gullar" — Gemini Live'dagi kabi.
 *
 * Ular sekin suzadi va kuchli xiralashgan, shuning uchun oq fon tirik
 * ko'rinadi, lekin matnni o'qishga xalaqit bermaydi. Butun ilovada bitta
 * nusxa bo'ladi (§Shell), ya'ni sahifa almashganda qayta chizilmaydi.
 */
export default function Backdrop() {
  return (
    <div className="backdrop" aria-hidden="true">
      <span className="backdrop__blob backdrop__blob--1" />
      <span className="backdrop__blob backdrop__blob--2" />
      <span className="backdrop__blob backdrop__blob--3" />
      <span className="backdrop__blob backdrop__blob--4" />
    </div>
  )
}
