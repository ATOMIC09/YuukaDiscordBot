<h1 align="center">🌈 YuukaDiscordBot - v3.2 "When Words Take Wing 🕊️" </h1>
<p align="center">"เมื่อถ้อยคำมีปีกบิน"</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/github/v/tag/ATOMIC09/YuukaDiscordBot?label=version&color=blue" />
  <a href="https://github.com/ATOMIC09/YuukaDiscordBot/actions/workflows/docker-build.yml">
    <img alt="Build" src="https://img.shields.io/github/actions/workflow/status/ATOMIC09/YuukaDiscordBot/docker-build.yml?label=build" />
  </a>
  <a>
    <img alt="License" src="https://img.shields.io/github/license/ATOMIC09/YuukaDiscordBot">
  </a>
</p>

## 🛠️ คำสั่งทั่วไป
- `/help` ดูวิธีใช้งานคำสั่งทั้งหมดของบอท
- `/status` ดูสถานะและข้อมูลระบบของบอท
- `/server` ดูข้อมูลของเซิร์ฟเวอร์
- `/user` ดูข้อมูลบัญชีของผู้ใช้
- `/feedback` ส่งข้อความหลังไมค์ไปหาผู้สร้าง

## 🤖 คำสั่ง AI
- `/ai chat` เปิดใช้งานโหมดแชทบอท AI (เรียกหนูด้วย `@mention`)
- `/ai voice` เข้าห้องเสียงและคุยกับยูกะด้วยเสียง
- `/ai stop` หยุดการทำงานของ AI ทั้งหมดในเซิร์ฟเวอร์

## 🎙️ คุยกับยูกะด้วยเสียง
1. **เรียกชื่อ "ยูกะ" (Yuuka)** แล้วรอเสียง *ติ๊ง* ที่บอกว่าหนูได้ยินแล้ว (ถ้ามีเพลงเล่นอยู่ หนูจะพิมพ์บอกในแชทแทน)
2. **พูดสิ่งที่ต้องการต่อได้เลย** ไม่ต้องเรียกชื่อซ้ำ หรือจะพูดรวมในประโยคเดียวก็ได้ เช่น *"ยูกะ เปิดเพลง YOASOBI ให้หน่อย"*
3. ถ้างานใช้เวลานาน จะมีแผงสถานะ 🧠 บอกว่าหนูกำลังทำอะไรอยู่ ไม่ต้องสั่งซ้ำน้า

### สิ่งที่สั่งด้วยเสียงได้
- 🎵 ควบคุมเพลงครบ: เปิด ข้าม พัก เล่นต่อ ย้อนกลับ กรอเวลา วนลูป ปรับเสียง ล้างคิว และออกจากห้อง (พูดว่า "หยุด" = พักเพลง ส่วน "ล้างคิว" = หยุดและล้างคิว)
- 📝 เช็คชื่อ (`/attendance`) และหาผู้ขาด (`/absent`) เลือกเฉพาะยศได้
- 🎙️ เริ่ม/หยุดบันทึกเสียง (`/record`) และถอดเสียงสด (`/transcribe`)
- 🦵 เตะออกจากห้อง (`/kick`) และตั้งเวลาตัดการเชื่อมต่อ (`/countdis`) ต้องยืนยันก่อนทุกครั้ง กดปุ่มหรือพูดว่า "ยืนยัน" ก็ได้
- 🔍 ค้นเว็บ อ่านและค้นข้อความในช่อง ดูข้อมูลสมาชิกและเซิร์ฟเวอร์
- ⏰ ตั้งเตือน และแจ้งเมื่อมีคนเข้าห้องเสียง

*และคำสั่งอื่น ๆ*

## 🔊 คำสั่งจัดการห้องเสียง
- `/attendance` บันทึกการเข้าประชุม (เช็คชื่อคนในห้องเสียง พร้อมไฟล์ CSV)
- `/absent` หาผู้ขาดการประชุม (ไม่ได้อยู่ในห้องเสียง) เลือกเฉพาะยศได้
- `/countdis` นับถอยหลังและเตะทุกคนออกจากแชทเสียง
- `/kick` เตะสมาชิกออกจากห้องเสียง
- `/record start` และ `/record stop` บันทึกเสียงในห้องพูดคุย
- `/transcribe start` และ `/transcribe stop` แปลงเสียงพูดในห้องเป็นข้อความแบบเรียลไทม์ (STT)

## 🎵 คำสั่งเครื่องเล่นเพลง (Music Player)
- `/music play` เปิดเพลงจาก YouTube หรือ YouTube Music (รองรับ Playlist)
- `/music local` เล่นเพลงจากไฟล์แนบ หรือจากประวัติแชท (**ไม่**รองรับการสั่งด้วยเสียง)
- `/music pause` และ `/music resume` หยุดและเล่นเพลงต่อ
- `/music stop` หยุดเพลงและล้างคิวทั้งหมด
- `/music skip` ข้ามเพลงปัจจุบัน หรือกระโดดข้ามไปยังคิวที่ระบุได้
- `/music previous` ย้อนกลับไปเพลงก่อนหน้า
- `/music seek` เลื่อนไปยังเวลาที่ต้องการ (เช่น `90`, `1:30`)
- `/music loop` ตั้งค่าวนลูป (เพลงเดียว, ทั้งคิว, ปิด)
- `/music queue` ดูคิวเพลงทั้งหมด (มีปุ่มเลื่อนหน้า และปุ่มอัปเดตคิว)
- `/music volume` ปรับระดับเสียงเพลง (0-100)
- `/music nowplaying` เรียกแผงควบคุมเพลงล่าสุด
- `/music leave` สั่งบอทออกจากห้องเสียง (หรือบอทจะออกเองเมื่อไม่มีเพลงเล่นเกิน 3 นาที)

## 🖼️ คำสั่งรูปภาพและมัลติมีเดีย (Image)
- `/image pet` สร้างภาพลูบหัว (Petpet)
- `/image qr` สร้าง QR Code จากข้อความ
- `/image resize` และ `/image scale` ปรับขนาด/สัดส่วนรูปภาพ
- `/imgaudio` สร้างคลิปจากภาพและเสียงล่าสุดในช่อง

*และฟีเจอร์อื่นๆ ที่กำลังจะตามมา!*

## 📄 รายการคำสั่ง Context Command (คลิกขวาที่ข้อความ -> Apps -> ...)
- `Deepfry` ทอดกรอบภาพร้อนๆ
- `Grayscale` เปลี่ยนเป็นสีขาวดำ
- `Image Info` ดูคุณสมบัติและข้อมูลเชิงลึกของรูปภาพ
- `Wide` ยืดภาพให้กว้างงงง

## © เครดิต
- ภาพโปรไฟล์ของบอท [👀](https://www.pixiv.net/en/artworks/121894766)
- ภาพปกของบอท [🖼](https://x.com/morphling_2/status/1655501344164433922)

## 📜 License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPLv3)**, with the **[Commons Clause](COMMONS-CLAUSE.md)** condition applied.

- ✅ You may clone, edit, fork, self-host, and submit pull requests freely.
- ✅ If you distribute or run a modified version as a network service, you must make that source code available.
- ❌ You may **not** sell this software or use it to provide a commercial product/service.

See [LICENSE](LICENSE) and [COMMONS-CLAUSE.md](COMMONS-CLAUSE.md) for full terms.