<h1 align="center">🌈 YuukaDiscordBot - v3.0 "Echoes of Mind 💖" </h1>
<p align="center">"เสียงสะท้อนแห่งความคิด"</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/github/v/tag/ATOMIC09/YuukaDiscordBot?label=version&color=blue" />
  <a href="https://github.com/ATOMIC09/YuukaDiscordBot/actions/workflows/docker-build.yml">
    <img alt="Build" src="https://img.shields.io/github/actions/workflow/status/ATOMIC09/YuukaDiscordBot/docker-build.yml?label=build" />
  </a>
  <a>
    <img alt="License" src="https://img.shields.io/github/license/ATOMIC09/YuukaDiscordBot">
  </a>
</p>

## 🚀 รายการคำสั่งที่สามารถใช้งานได้

### 🛠️ คำสั่งทั่วไป
- `/help` ดูวิธีใช้งานคำสั่งทั้งหมดของบอท
- `/status` ดูสถานะและข้อมูลระบบของบอท
- `/server` ดูข้อมูลของเซิร์ฟเวอร์
- `/user` ดูข้อมูลบัญชีของผู้ใช้
- `/feedback` ส่งข้อความหลังไมค์ไปหาผู้สร้าง

### 🤖 คำสั่ง AI
- `/ai chat` เปิดใช้งานโหมดแชทบอท AI
- `/ai voice_chat` เปิดโหมดสนทนาด้วยเสียงกับ AI *(Beta)*

### 🔊 คำสั่งจัดการห้องเสียง
- `/attendance` บันทึกการเข้าประชุม (เช็คชื่อคนในห้องเสียง)
- `/absent` หาผู้ขาดการประชุม (ไม่ได้อยู่ในห้องเสียง)
- `/countdis` นับถอยหลังและเตะทุกคนออกจากแชทเสียง
- `/kick` เตะสมาชิกออกจากห้องเสียง
- `/record` บันทึกเสียงในห้องพูดคุย
- `/transcribe` แปลงเสียงพูดในห้องเป็นข้อความแบบเรียลไทม์ (STT) *(Beta)*

### 🎵 คำสั่งเครื่องเล่นเพลง (Music Player)
- `/music play` เปิดเพลงจาก YouTube หรือ YouTube Music (รองรับ Playlist)
- `/music local` เล่นเพลงจากไฟล์แนบ หรือจากประวัติแชท
- `/music pause` และ `/music resume` หยุดและเล่นเพลงต่อ
- `/music stop` หยุดเพลงและล้างคิวทั้งหมด
- `/music skip` ข้ามเพลงปัจจุบัน หรือกระโดดข้ามไปยังคิวที่ระบุได้
- `/music loop` ตั้งค่าวนลูป (เพลงเดียว, ทั้งคิว, ปิด)
- `/music queue` ดูคิวเพลงทั้งหมด (มีปุ่มเลื่อนหน้า และปุ่มอัปเดตคิว)
- `/music restore <code>` ดึงคิวที่บันทึกมาเล่น
- `/music restore list` แสดงรายการเพลย์ลิสต์ของเซิร์ฟเวอร์นี้ พร้อมรหัส ผู้สร้าง วันสร้าง และวันหมดอายุ
- รหัสเพลย์ลิสต์ใช้ได้เฉพาะในเซิร์ฟเวอร์ที่บันทึกไว้ แต่ทุกคนในเซิร์ฟเวอร์นั้นสามารถใช้ได้
- การบันทึกเพลย์ลิสต์จะเก็บตำแหน่งของเพลงที่กำลังเล่นไว้ด้วย เพื่อให้เพลงแรกเล่นต่อจากเวลาเดิมเมื่อกู้คืน
- ระบบจะเก็บระยะเวลาของแต่ละเพลงไว้ด้วย เพื่อให้คิวที่กู้คืนแสดงเวลาของเพลงได้ทันที
- `/music volume` ปรับระดับเสียงเพลง (0-100)
- `/music nowplaying` เรียกแผงควบคุมเพลงล่าสุด
- `/music leave` สั่งบอทออกจากห้องเสียง (หรือบอทจะออกเองเมื่อไม่มีเพลงเล่นเกิน 3 นาที)

### 🖼️ คำสั่งรูปภาพและมัลติมีเดีย (Image)
- `/pet` สร้างภาพลูบหัว (Petpet)
- `/qr` สร้าง QR Code จากข้อความ
- `/resize` และ `/scale` ปรับขนาด/สัดส่วนรูปภาพ
- `/imgaudio` สร้างคลิปจากภาพและเสียงล่าสุดในช่อง

*และฟีเจอร์อื่นๆ ที่กำลังจะตามมา!*

## 📄 รายการคำสั่ง Context Command (คลิกขวาที่ข้อความ -> Apps -> ...)
- `Deepfry` ทอดกรอบภาพร้อนๆ
- `Grayscale` เปลี่ยนเป็นสีขาวดำ
- `Image Info` ดูคุณสมบัติและข้อมูลเชิงลึกของรูปภาพ
- `Wide` ยืดภาพให้กว้างงงง

## 👦🏻 ช่องทางการติดต่อกับผู้สร้าง
* Discord : [@ATOMIC09](https://discords.com/bio/p/atomic09)

## © เครดิต
- ภาพโปรไฟล์ของบอท [👀](https://www.pixiv.net/en/artworks/121894766)
- ภาพปกของบอท [🖼](https://x.com/morphling_2/status/1655501344164433922)

## 📜 License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPLv3)**, with the **[Commons Clause](COMMONS-CLAUSE.md)** condition applied.

- ✅ You may clone, edit, fork, self-host, and submit pull requests freely.
- ✅ If you distribute or run a modified version as a network service, you must make that source code available.
- ❌ You may **not** sell this software or use it to provide a commercial product/service.

See [LICENSE](LICENSE) and [COMMONS-CLAUSE.md](COMMONS-CLAUSE.md) for full terms.
