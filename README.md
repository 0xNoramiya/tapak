<p align="center">
  <img src="docs/img/banner.webp" alt="TAPAK: Tanda Atribusi Penerima Anti-Kolusi" width="100%">
</p>

<p align="center">
  <a href="#cara-kerja">Cara kerja</a> ·
  <a href="#hasil">Hasil</a> ·
  <a href="#mulai-cepat">Mulai cepat</a> ·
  <a href="docs/cara-kerja.md">Dokumentasi</a>
</p>

Setiap penerima dokumen rahasia mendapat salinan yang tampak sama, tetapi masing-masing membawa sidiknya sendiri. Bila salah satu salinan bocor sebagai foto, tangkapan layar, PDF yang diteruskan, atau teks yang disalin, TAPAK menunjuk salinan sumbernya dan penerima yang tercatat untuk salinan itu, beserta batas atas peluang tuduhan salahnya. Bila buktinya kurang, TAPAK menjawab "tidak cukup bukti" dan tidak menyebut nama.

Sidiknya memakai kode Tardos. Dalam simulasi tingkat kode, gabungan kode tiga penerima yang bersekongkol tetap menunjuk ketiganya tanpa menyeret orang lain. Semua pemrosesan berjalan di komputer sendiri, tanpa layanan awan. Dokumen dan nama di repositori ini fiktif.

## Cara kerja

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/alur-dark.svg">
  <img alt="Alur TAPAK: dokumen induk diterbitkan menjadi 20 salinan unik, foto sintetis salinan #13 bocor, lalu dilacak sampai berita acara" src="docs/img/alur-light.svg" width="100%">
</picture>

1. **Terbitkan.** TAPAK menggambar ulang PDF untuk setiap penerima, menanam kode uniknya di empat kanal, dan menambahkan token kanari.
2. **Lacak.** Dekoder membaca apa pun yang tersisa di bukti, menggabungkan semua kanal, lalu membandingkan skor setiap salinan dengan ambang. Ambang itu ditetapkan sebelum skor dihitung.
3. **Laporkan.** Putusan yang menyebut nama selalu disertai skor, ambang, dan batas peluang tuduhan salah, lalu ditulis sebagai berita acara PDF.

### Lima kanal

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/kanal-dark.png">
  <img alt="Tiga dari lima kanal pada salinan sungguhan: geser kata, pola latar, dan karakter tak terlihat" src="docs/img/kanal-light.png" width="100%">
</picture>

- **Geser kata dan baris** bertahan pada cetakan, foto, dan tangkapan layar.
- **Pola latar** bertahan pada foto layar dan tangkapan layar, tetapi hilang saat dicetak. Profil latar cetak (opsional) bertahan di kertas dalam uji printer simulasi, dengan harga halaman tampak abu-abu muda.
- **Karakter tak terlihat** ikut terbawa saat teks disalin atau PDF diteruskan.
- **Varian semantik**, parafrasa kalimat pembuka dan penutup yang dibuat LLM lokal lalu disetujui manusia, bertahan saat dokumen diketik ulang, tetapi hanya membawa beberapa bit.
- **Kanari DNS**, subdomain unik per salinan, berbunyi bila berkas dibuka di luar jaringan satuan. Kanari tidak ikut dalam skor.

Dekoder menggabungkan bukti yang tersisa tanpa pernah melihat kode penerima, jadi batas peluang tuduhan salah berlaku untuk bukti apa pun, selama rahasia kode aman.

## Hasil

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/skor-dark.svg">
  <img alt="Simulasi kolusi: skor penerima tak bersalah paling tinggi 72 persen dari ambang, skor anggota koalisi paling rendah 136 persen" src="docs/img/skor-light.svg" width="100%">
</picture>

Ambangnya berasal dari batas Chernoff, bukan dari simulasi ini. Nol tuduhan salah dalam 1.000 percobaan per strategi hanya menunjukkan lajunya di bawah sekitar 3 &times; 10<sup>-3</sup>; batas 10<sup>-6</sup> datang dari perhitungannya.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/benchmark-dark.svg">
  <img alt="Uji sintetis: foto layar 40 dari 40 benar; foto kertas cetak dari printer simulasi 9 dari 16 dengan satu halaman dan 8 dari 8 dengan dua halaman; foto dengan ISP ponsel simulasi 32 dari 32; foto monitor simulasi 32 dari 32; 0 salah" src="docs/img/benchmark-light.svg" width="100%">
</picture>

Baris cetak memotret halaman yang dicetak printer laser simulasi. Pola latar bawaan hilang di kertas, jadi hanya kanal geser yang tersisa. Dengan skema geser v2, bawaan penerbitan baru, halaman 1 menyebut salinan yang benar pada 8 dari 8 foto, halaman 2 yang lebih pendek pada 1 dari 8, dan kedua halaman bersama pada 8 dari 8 (skema v1: 0 dari 16 dan 8 dari 8). Ini simulasi dengan satu rahasia kode; dengan rahasia lain angkanya dapat lebih rendah (lihat [batasan](#batasan)).

Foto layar dengan 95 % kertas jenuh putih kehilangan pola latarnya ([batasan 4](docs/keamanan.md#batasan)) dan kini disebut lewat kanal geser saja, dengan skor tipis di atas ambang. Kami tidak menurunkan ambang mana pun. Untuk 39 jawaban benar lainnya pada foto layar, batas peluang tuduhan salahnya paling besar 4,0 &times; 10<sup>-26</sup>. Adegan foto yang sama lewat ISP ponsel simulasi benar 32 dari 32, dan foto salinan di monitor simulasi juga 32 dari 32.

Uji lainnya:

- Halaman digital gabungan dua salinan (diuji pada 2 pasangan): kedua penerimanya dituduh, tidak ada orang lain.
- Pembukaan salinan yang disimulasikan tercatat di log kanari dalam sekitar 0,1 detik.
- Penerbitan 20 salinan dokumen 2 halaman selesai dalam 4 sampai 5 detik.

Angka lengkap, termasuk kanal berderau dan koalisi 5 orang, ada di [cara kerja](docs/cara-kerja.md#angka-simulasi).

## Antarmuka

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/ui-lacak-dark.png">
  <img alt="Halaman Lacak untuk foto sintetis salinan #13: skor, ambang, batas peluang tuduhan salah, dan bukti per kanal" src="docs/img/ui-lacak-light.png" width="100%">
</picture>

Halaman **Lacak** di atas membaca foto yang sama dengan gambar alur. Putusannya hanya datang dari pola latar, jadi tidak berlaku untuk foto salinan yang dicetak. Halaman **Terbitkan** menerima PDF (berlapis teks atau hasil pindai) dan daftar penerima, menawarkan profil pola latar (layar atau cetak) dan skema geser (v2 atau v1), meminta peninjauan setiap varian dan setiap titik pilihan kata (opsional), lalu menghasilkan ZIP salinan.

## Mulai cepat

Butuh Python 3.11 atau lebih baru dan [uv](https://docs.astral.sh/uv/). Di Ubuntu:

```bash
sudo apt-get install -y \
  tesseract-ocr tesseract-ocr-ind poppler-utils \
  libpango-1.0-0 libharfbuzz-subset0
make setup  # sekali, perlu jaringan
make demo   # skenario lengkap, sekitar 30 detik
make web    # http://127.0.0.1:8000
make test   # seluruh pengujian
```

Docker, semua perintah `tapak`, kunci, dan konfigurasi ada di [panduan menjalankan TAPAK](docs/operasi.md).

## Keamanan

- TAPAK tidak menghubungi layanan luar. Satu-satunya bagian yang menghadap internet adalah pendengar DNS kanari.
- Registri bersifat tambah-saja, dengan rantai SHA-256 dan tanda tangan Ed25519. Registri tidak menyimpan teks dokumen, gambar, atau nama penerima.
- Bila kunci publik terpasang, TAPAK hanya menyebut nama kalau rantai registri utuh dan setiap salinan cocok dengan entrinya. Entri yang belum bertanda tangan ditandai jelas di hasil. Mode lepas `tapak trace --master --manifest` melewati pemeriksaan ini, menyatakannya di keluaran, dan tidak membuat berita acara.
- Di Docker, pendengar kanari berjalan di kontainer dan jaringan terpisah, dan hanya melihat log-nya sendiri serta daftar token yang sah.

Rinciannya, termasuk format registri untuk auditor, ada di [keamanan](docs/keamanan.md).

## Batasan

- Dengan pola latar bawaan, foto salinan cetak hanya membawa kanal geser. Dalam uji printer simulasi, skema geser v2 (bawaan penerbitan baru) menyebut nama dari satu halaman teks penuh pada semua foto 4000 px uji tertahan dan 57 % foto 1600 px, tetapi lebih jarang dengan rahasia kode lain (17 dari 24 foto 4000 px pada benih pengembangan); dokumen lama (skema v1) baru cukup dari dua halaman, kadang-kadang. Tidak ada ketahanan kolusi. Skema v2 juga menggeser tepi kiri dan kanan teks sampai 0,05 mm antarbaris, kira-kira di ambang penglihatan dan belum diuji dengan pengamat. Profil `--latar cetak` membuat satu halaman cukup dalam simulasi, tetapi halamannya tampak abu-abu muda.
- Pengetikan ulang hanya menyisakan varian semantik dan kanal pilihan kata yang opsional. Dokumen 1 sampai 2 halaman tetap "tidak cukup bukti". Dalam simulasi, satu pembocor baru dapat disebut dari sekitar 1.300 kata isi, tanpa ketahanan kolusi. Pilihan kata terlihat di kertas dan dapat ditiru, jadi nama yang hanya didukung pilihan kata selalu diberi peringatan.
- Orang yang memahami TAPAK tetap dapat lolos tanpa nama, dengan dua salinan atau lebih dan sering dengan satu salinan saja. Pembalikan tanda kini hampir selalu diberi peringatan, juga lewat gambar, cetakan, dan derau pada pola latar, dan penghapusan di tempat salinan koalisi sama umumnya juga, kecuali pada cetakan, tetapi tanda yang diacak atau dibalik kurang dari separuh lolos tanpa peringatan, juga oleh satu salinan saja, padahal salinan jujur lewat medium yang sama umumnya disebut namanya. Tidak ada orang lain yang tertuduh karenanya.
- Kanari hanya berbunyi di penampil yang mengambil konten luar, seperti Adobe Reader dan Word. Adobe Reader pun lebih dulu menampilkan peringatan izin, sehingga kanari mudah dikenali.
- Semua foto dan cetakan uji sintetis, dan kamera ponsel, monitor, serta printer sungguhan belum diuji. Varian semantik di demo berasal dari tabel frasa tiruan. Dengan LLM lokal 3 sampai 4B di CPU, varian yang layak disetujui jarang muncul (4 bit dari 24 pembangkitan pada dua dokumen contoh).

Kami memilih menjawab "tidak cukup bukti" daripada menebak. Daftar lengkapnya, dengan angka, ada di [keamanan](docs/keamanan.md#batasan).

---

<sub>Dibuat untuk Kartika Cyber Hackathon 2026, kategori Core Infra. Setiap halaman contoh bertanda "CONTOH SINTETIS - BUKAN DOKUMEN ASLI". Font DejaVu untuk dokumen dan berita acara (lisensi Bitstream Vera, `tapak/assets/fonts/LICENSE-DejaVu.txt`), font IBM Plex untuk antarmuka (SIL OFL 1.1, `tapak/web/static/fonts/LICENSE-IBM-Plex.txt`), dan HTMX 1.9.12 (lisensi BSD, `tapak/web/static/`) disertakan di repositori.</sub>
