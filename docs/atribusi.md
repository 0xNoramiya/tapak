# Atribusi

TAPAK dibuat oleh tim **In Kudaliar We Trust** untuk Kartika Cyber Hackathon 2026. Halaman ini mencatat asal karya, pustaka dan alat pihak ketiga yang dipakai, serta lisensinya.

## Asal karya

Seluruh kode di repositori ini ditulis selama periode program. Riwayat git dimulai pada 21 Oktober 2026 dan memuat setiap langkahnya. Kode Tardos, kelima kanal sidik, dekoder, registri berantai, pendengar kanari, dan antarmuka web ditulis untuk proyek ini di atas pustaka umum di bawah.

Semua dokumen, nama penerima, dan satuan di repositori dan di instans uji coba adalah contoh fiktif. Foto cetakan sungguhan yang dipakai dalam pengujian dibuat oleh tim dan tidak disertakan di repositori; yang disertakan hanya angka hasilnya.

## Pustaka Python

Versi tepatnya ada di `requirements.lock`.

| Pustaka | Dipakai untuk | Lisensi |
|---|---|---|
| PyMuPDF | membaca, merender, dan menulis PDF | AGPL-3.0 atau lisensi komersial Artifex |
| pikepdf | menyisipkan token kanari ke PDF | MPL-2.0 |
| python-docx, lxml | salinan dan bukti DOCX | MIT, BSD-3-Clause |
| NumPy, SciPy | perhitungan kode Tardos dan dekoder | BSD-3-Clause |
| OpenCV (headless) | registrasi dan pembacaan foto, pindaian, tangkapan layar | Apache-2.0 |
| pillow-heif | membaca foto HEIC | BSD-3-Clause; rodanya memuat libheif dan libde265 (LGPL) serta x265 (GPL) |
| pytesseract | dependensi untuk Tesseract OCR lokal (TAPAK memanggil Tesseract langsung dengan pengaturan yang sama) | Apache-2.0 |
| RapidFuzz | mencocokkan teks pada kanal varian kalimat dan pilihan kata | MIT |
| PyNaCl | tanda tangan Ed25519 registri | Apache-2.0 |
| dnslib | pendengar DNS kanari | BSD |
| FastAPI, Uvicorn, Jinja2, python-multipart | aplikasi web | MIT, BSD-3-Clause, BSD-3-Clause, Apache-2.0 |
| WeasyPrint | berita acara PDF | BSD-3-Clause |
| fontTools | memeriksa bahwa huruf kembar sama bentuk dan lebarnya di font dokumen | MIT |
| pytest, httpx | pengujian | MIT, BSD-3-Clause |
| Matplotlib | grafik di dokumentasi | lisensi Matplotlib (berbasis PSF) |

PyMuPDF berlisensi AGPL-3.0. Siapa pun yang menyebarkan TAPAK atau menyediakannya sebagai layanan jaringan perlu memenuhi AGPL atau memegang lisensi komersial Artifex.

## Disertakan di repositori

| Komponen | Letak | Lisensi |
|---|---|---|
| Font DejaVu (dokumen contoh dan berita acara) | `tapak/assets/fonts/` | Bitstream Vera, `LICENSE-DejaVu.txt` |
| Font IBM Plex (antarmuka) | `tapak/web/static/fonts/` | SIL OFL 1.1, `LICENSE-IBM-Plex.txt` |
| HTMX 1.9.12 | `tapak/web/static/` | BSD |

## Di dalam image Docker

Tesseract OCR dengan data bahasa Indonesia (Apache-2.0), poppler-utils (GPL), Pango (LGPL) dan HarfBuzz (MIT) untuk WeasyPrint, di atas image dasar Python.

## Alat bantu

- **Asisten pemrograman AI.** Claude Code (Anthropic) dipakai selama pengembangan. Commit yang dikerjakan bersamanya mencantumkan baris `Co-Authored-By` di pesan commit.
- **LLM lokal (opsional).** Varian kalimat dapat dibangkitkan model lokal lewat llama.cpp. Bawaannya tabel frasa tiruan tanpa model, dan TAPAK tidak pernah memanggil layanan AI di luar perangkat.
- **Video penjelasan.** Narasi dan musik sintetis dibuat dengan ElevenLabs; gambar pembuka dan ruang server dibuat dengan Higgsfield; film disusun dengan HyperFrames dan FFmpeg. Rekaman aplikasi di video adalah rekaman layar instans uji coba, tanpa potongan.
- **Tangkapan layar dan slide.** Dibuat dengan Playwright dan Chromium dari halaman aplikasi sendiri.

## Lisensi kode TAPAK

Repositori ini dibuka agar dapat dinilai Dewan Juri. Berkas lisensi untuk kode TAPAK sendiri belum ditetapkan.
