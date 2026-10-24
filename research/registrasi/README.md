# Registrasi bukti potongan dan beresolusi rendah

Studi tangkapan layar ([`research/layar`](../layar/README.md)) menemukan bahwa registrasi, bukan dekoder, yang menentukan batas bawah: setiap halaman utuh yang gagal adalah halaman yang tidak ditemukan (28 sampai 32 dpi; Splash tanpa anti-aliasing sampai 48 dpi), jendela penampil yang hanya memperlihatkan bagian tengah halaman tidak ditemukan pada 60 dari 120 tangkapan, dan setiap halaman yang ditemukan disebut. Pembocor juga sering mengirim potongan satu paragraf atau foto ponsel sebagian halaman. Studi ini mengukur bukti mana yang gagal diregistrasi dan tahap mana yang menyerah, lalu mengukur tahap penyelamat yang dipilih pada set pengembangan (`tapak/decoder/rectify.py`, `rescue_register`) pada set uji yang ditahan, sebelum dan sesudah.

## Protokol

Protokol, benih, dan aturan pemilihan ditetapkan di `ukur.py` (`PROTOCOL`) dan `pilih.py` (`ATURAN`) dan masuk riwayat repositori sebelum set uji dibuat. Berkas `pilih.py` dengan aturan itu ditulis sebelum pengumpulan pertama pada set pengembangan dan tidak diubah sesudahnya, tetapi baru masuk riwayat git bersama protokol, tepat sebelum set uji; urutan itu tercatat di log kerja, bukan di git.

* **Penerbitan.** Nota dinas dan surat telegram contoh (fiktif) lewat `tapak issue --benih-riset BENIH --no-registry` untuk N = 20 penerima (c = 3, eps = 10^-6, skema geser v2, profil latar bawaan). Benih baru yang belum dipakai studi lain: set `dev` 9601 dan 9602 (benih bukti 9611, induk tanpa tanda 9699), set `uji` 9701 dan 9702 (9711, 9799). Bukti diambil dari halaman 1 dan halaman 2.
* **Jenis bukti** (`PROTOCOL["grids"]`):
  * `potong`: tangkapan layar yang digambar penggambar sungguhan dari `research/layar` (MuPDF, Poppler Splash, Poppler Cairo), bagian atas, tengah, atau bawah halaman setinggi 25, 40, 55, 70, 85, atau 100 % (100 % hanya dari atas), selebar halaman, dengan dan tanpa jendela penampil (bergantian), pada 48, 64, 84, 120, dan 150 dpi, disimpan sebagai PNG atau dikirim lewat aplikasi pesan (`pesan`: sisi panjang paling besar 1600 px, JPEG mutu 68 sampai 72 lalu 58 sampai 62);
  * `paragraf`: potongan satu paragraf (barisnya ditambah tepi 3 sampai 12 pt, tanpa jendela), resolusi dan format seperti `potong`;
  * `rendah`: halaman utuh pada 24, 28, 32, 40, dan 48 dpi, keempat penggambar (termasuk Splash tanpa anti-aliasing), PNG, `pesan`, dan `kecil` (digambar 1,5 kali lebih rapat lalu diperkecil aplikasi pesan), halaman saja atau di jendela penampil;
  * `foto`: foto ponsel halaman utuh dari `tapak.photos.photo_jpeg` (0 sampai 30 derajat, sensor 4000 px, JPEG kamera mutu 90 sampai 95, separuhnya lewat ISP ponsel), dipotong pengguna menjadi bagian atas, tengah, atau bawah setinggi 25 sampai 70 % atau satu paragraf, lalu dikirim lewat aplikasi pesan;
  * `induk`: dokumen induk tanpa tanda lewat keempat jenis di atas, dilacak terhadap penerbitan dokumennya: tidak boleh ada yang dituduh;
  * `silang`: satu dari setiap delapan bukti salinan bertanda, dilacak terhadap penerbitan dokumen yang lain. Setiap registrasi di sini salah dokumen dan setiap tuduhan salah. Kedua dokumen memakai font, tepi, kop, dan kaki halaman yang sama, jadi ini uji terberat bagi verifikasi pose.
* **Pelacakan** seperti `make bench`: tanpa registri, seluruh eps, satu tahap, lewat jalur produksi (`collect_from_gray`). Bila tahap penyelamat berjalan, gambar yang sama dilacak sekali lagi dengan tahap itu dimatikan (`register(..., rescue=False)`, jalur sebelum studi ini), sehingga sebelum dan sesudah berpasangan.
* **Kebenaran pose.** Setiap gambar membawa homografi sebenarnya dari titik halaman ke piksel gambar. Galat pose diukur di gambar pada titik berjarak 14 pt di bagian halaman yang terlihat, dan pada titik tengah kata induk yang terlihat. Pose **benar** bila persentil ke-95 seluruhnya paling besar 1,5 piksel gambar; **salah** bila halaman atau dokumennya salah, tidak ada kata induk yang terlihat, atau persentil ke-95 pada kata lebih dari 5 piksel; selebihnya **kasar** (teks pas, bagian kosong meleset, misalnya potongan yang hanya memuat kaki halaman).
* **Ukuran per pelacakan.** Ditemukan atau tidak, kelas pose, tahap yang menyerah (`ringkas.py`, `stage`), putusan semua kanal, skor salinan yang bocor dan skor tak bersalah tertinggi sebagai kelipatan ambang, batas peluang tuduhan salah, peringatan pola penghapusan, peringatan bacaan jelas tanpa nama, dan detik per pelacakan.

## Tahap yang menyerah (set dev, jalur sebelum studi ini)

Set dev dilacak lebih dulu dengan jalur lama (`hasil/dev_sebelum.jsonl`, 1.132 gambar, sebelum tahap penyelamat ada). Dari 1.084 gambar salinan bertanda, 304 tidak ditemukan: potongan layar 182 dari 640, paragraf 53 dari 120, halaman 24 sampai 48 dpi 58 dari 220, foto sebagian halaman 11 dari 104. Tahap yang menyerah (`ringkas.stage`, dari catatan setiap tahap registrasi pada `hasil/dev_periksa.jsonl`):

| Tahap | Potongan layar | Paragraf | Halaman 24 sampai 48 dpi | Foto sebagian |
|---|---|---|---|---|
| tidak ada kata induk yang terlihat (bagian kosong halaman 2) | 40 | 0 | 0 | 7 |
| tidak ada pose awal | 6 | 1 | 2 | 0 |
| ada pose awal, tidak satu pun dekat halaman yang benar | 52 | 36 | 23 | 4 |
| pose awal benar, ECC menyimpang darinya | 54 | 6 | 1 | 0 |
| ECC benar, korelasinya di bawah 0,75 | 30 | 10 | 32 | 0 |

* **Jendela penampil** adalah penyebab terbesar pada potongan layar: 122 dari 142 kegagalan yang memuat teks berada di jendela penampil (dari 319 potongan berjendela, 141 tidak ditemukan; tanpa jendela 41 dari 321). Gambar bukti diratakan terangnya sebelum ECC, dan bilah alat gelap serta tepi halaman menjadi "tinta" yang menarik ECC menjauh, bahkan dari pose awal SIFT yang tepat (galat 0,4 piksel, sesudah ECC 53 piksel).
* **Paragraf** kecil (2 sampai 10 baris, 100 sampai 1.000 piksel lebarnya) memberi terlalu sedikit fitur SIFT dan kata Tesseract.
* **Halaman 24 sampai 28 dpi** biasanya diregistrasi dengan benar, tetapi ECC pada 100 dpi membandingkan induk yang tajam dengan bukti yang buram dan korelasinya berhenti di 0,54 sampai 0,70, di bawah ambang 0,75. Halaman yang memenuhi gambar (tanpa jendela) tidak punya garis tepi, dan SIFT tidak menemukan fitur pada 24 dpi.
* **Pose yang ditemukan jalur lama tidak selalu tepat**: pada potongan halaman 2 surat telegram yang hampir kosong, homografi yang dicocokkan pada beberapa baris di bagian atas meleset sampai puluhan piksel di bagian kosong, tetapi salinan tetap disebut (pola latar di dekat teks terbaca, sel yang meleset menjadi derau).

## Tahap penyelamat

Tahap ini hanya berjalan bila tahap sebelumnya tidak menemukan halaman (tidak ada pose awal, atau korelasi ECC di bawah 0,75), jadi bukti yang sudah ditemukan didekode persis seperti sebelumnya. Dekoder dan registrasi tetap buta kode (hanya bukti, PDF induk, dan ukuran halaman). Rancangannya dibuat pada gambar dev yang tidak ditemukan jalur lama:

1. **Masker kertas** (`paper_mask`). Tangkapan layar menampilkan kertas pada satu tingkat abu-abu yang tepat (foto tidak). Baris dan kolom yang memuat kertas membentuk persegi bagian halaman; di luarnya jendela penampil, yang diganti warna kertas sebelum ECC dan tidak ikut didekode. Pada sampel set dev masker menemukan 61 dari 61 persegi berjendela (selisih paling besar 3 piksel) dan tidak memberi masker pada 79 dari 79 tangkapan tanpa jendela.
2. **Pose awal tambahan dari pencocokan templat** (`template_poses`): tinta bukti dicari di tinta setiap halaman induk dengan korelasi silang ternormalisasi atas skala (16 sampai 400 dpi, langkah 5 %) dan geseran, kasar pada 30 dpi lalu halus pada 45 dpi. Jendela induk yang kosong tidak menjadi kandidat (korelasinya tidak terdefinisi).
3. **ECC bermasker**, dengan peta afin untuk tangkapan layar (tanpa perspektif: potongan yang hanya memuat kaki halaman tidak lagi miring, galat 2,4 sampai 7 piksel menjadi 1,1 sampai 1,4) dan pada resolusi bukti sendiri di bawah 100 dpi (halaman 24 dpi: galat 1,1 sampai 2,6 piksel menjadi 0,5 sampai 1,1).
4. **Verifikasi**: pose ditolak bila ECC mengubah skalanya lebih dari 25 % atau skala lokalnya menyebar lebih dari 1,6 kali (`pose_is_sane`), bila korelasi tinta bukti dan induk pada pose itu kurang dari `RESCUE_MIN_AGREEMENT` (`pose_agreement`), atau bila pose lain di halaman lain atau 14 pt jauhnya menyusul dalam `RESCUE_AMBIGUITY`. Korelasinya diukur pada resolusi bukti setelah rata-rata lokal setiap baris (Gaussian 16 pt sepanjang baris) dibuang. Tanpa pembuangan itu, bukti dokumen lain (font, tepi, kop, dan jarak baris sama) mencapai 0,91 pada paragraf dua baris dan 0,6 sampai 0,77 pada potongan dan halaman, sedangkan pose yang benar paling rendah 0,92; dengan pembuangan itu dokumen lain paling besar 0,58 dan pose yang benar paling rendah 0,70.

**Pemilihan** (`pilih.py`). Semua gambar dev yang tidak ditemukan jalur lama, ditambah induk tanpa tanda dan bukti dokumen lain, diregistrasi dengan kode akhir (`hasil/pilih_dev.jsonl`, 450 gambar tempat tahap penyelamat berjalan). Aturan (`ATURAN`, ditetapkan sebelum pengumpulan pertama): di antara pasangan ambang yang tidak menerima satu pun pose salah, pasangan yang menerima pose tidak salah paling banyak, lalu keduanya dinaikkan satu langkah kisi. Hasilnya `RESCUE_MIN_AGREEMENT` 0,65 dan `RESCUE_AMBIGUITY` 0,05 (`hasil/pilihan.json`): pada set dev 259 registrasi diterima, 0 salah, 219 tepat dan 40 kasar. Varian rancangan tanpa tingkat ECC 0,25 menerima 260 (0 salah) pada 314 gambar yang sama; selisihnya tidak berarti, jadi rancangan dipertahankan. Peta afin dipilih dari potongan dev yang hanya memuat kaki halaman (di atas), tanpa pembandingan pada seluruh set.

**Pemeriksaan dekode pada set dev** (`hasil/dev_periksa.jsonl`, `hasil/ringkas_dev.json`: 304 gambar yang tidak ditemukan jalur lama dan 48 induk tanpa tanda; bukti dokumen lain sudah tidak diterima pada tahap registrasi): 259 registrasi baru (219 tepat, 40 kasar, 0 salah), 219 salinan baru disebut (skor paling kecil 1,05 kali ambang, median 4,1), tidak ada yang hilang, tidak ada tuduhan salah, dan tidak ada peringatan pola penghapusan atau bacaan jelas tanpa nama. Batas bawah halaman utuh turun ke 24 dpi untuk setiap penggambar dan format (sebelumnya 28 sampai 48 dpi). Paragraf yang baru ditemukan 52 dari 53, tetapi hanya 20 yang disebut: paragraf dua sampai empat baris membawa terlalu sedikit sel pola latar.

## Hasil (set uji)

Dijalankan sekali dengan kode komit protokol (`7cc56a5`, hash sumber dekoder di `hasil/uji_dekoder.json`). Jalannya berhenti dua kali. Pada gambar 1.553 dari 2.535, SIFT memberi pose awal yang singular dan tahap penyelamat gagal membaliknya (`LinAlgError`; pelacakan produksi gambar itu akan gagal dengan cara yang sama). Perbaikannya (`51bd158`) hanya melewati pose awal yang tidak dapat dibalik, jadi 1.552 baris yang sudah tercatat adalah hasil kode itu juga; jalannya dilanjutkan (`hasil/uji_dekoder_lanjut.json`). Pada gambar 1.589 sesi mesin uji berhenti, dan jalannya dilanjutkan lagi dengan kode yang sama setelah hash sumber dekoder diperiksa. Gambar yang sudah dilacak dilewati, dan setiap gambar memakai benihnya sendiri. Sebelum dan sesudah berpasangan pada gambar yang sama: 2.535 gambar, 3.432 pelacakan.

**Salinan bertanda, sebelum -> sesudah** (ditemukan / pose benar / disebut):

| Bukti | Gambar | Ditemukan | Pose benar | Disebut |
|---|---|---|---|---|
| Potongan layar dari atas halaman (25 sampai 100 %) | 480 | 480 -> 480 | 400 -> 400 | 480 -> 480 |
| Potongan dari tengah halaman (25 sampai 85 %) | 400 | 227 -> 317 | 213 -> 297 | 227 -> 317 |
| Potongan dari bawah halaman (25 sampai 85 %) | 400 | 212 -> 399 | 172 -> 288 | 207 -> 394 |
| Satu paragraf | 240 | 146 -> 237 | 142 -> 231 | 130 -> 161 |
| Halaman utuh 24 sampai 48 dpi | 440 | 314 -> 440 | 277 -> 403 | 314 -> 440 |
| Foto ponsel sebagian halaman | 208 | 180 -> 183 | 150 -> 152 | 168 -> 171 |

* **Jendela penampil.** Potongan berjendela (termasuk dari atas halaman): ditemukan 360 -> 596 dari 639, disebut 357 -> 593. Tanpa jendela 705 -> 837 dari 881.
* **Halaman utuh beresolusi rendah.** Setiap halaman pada 24 sampai 48 dpi ditemukan dan disebut, untuk keempat penggambar dan setiap format (8 dari 8 per sel). Sebelumnya batasnya 28 dpi untuk tangkapan yang diperkecil, 32 dpi untuk PNG dan pesan MuPDF serta PNG Splash dan Cairo, 40 dpi untuk pesan Splash dan Cairo, dan 48 dpi untuk PNG Splash tanpa anti-aliasing; pesan Splash tanpa anti-aliasing tidak pernah 8 dari 8 sampai 48 dpi.
* **Putusan.** 437 salinan baru disebut (skor paling kecil 1,008 kali ambang, median 4,2), tidak ada yang hilang; seluruhnya 1.526 -> 1.963.
* **Tuduhan salah:** 0 dari 3.432 pelacakan, termasuk 96 pelacakan induk tanpa tanda (ditemukan 79 -> 93) dan 271 pelacakan terhadap dokumen yang lain; skor tak bersalah tertinggi 0,61 kali ambang, sebelum dan sesudah.
* **Peringatan pada bukti jujur:** tidak ada peringatan pola penghapusan atau bacaan jelas tanpa nama pada 2.264 pelacakan, sebelum maupun sesudah, juga pada registrasi yang salah.
* **Pose salah.** Tahap penyelamat berjalan pada 897 pelacakan: 520 terdaftar (431 tepat, 80 kasar, 9 salah), 345 ditolak verifikasi, 28 tanpa pose, 4 ambigu. Kesembilan pose salah adalah dokumen yang salah: bagian bawah 40 % halaman 2 surat telegram, yang hanya memuat kaki halaman ("RAHASIA" dan tanda contoh sintetis), dilacak terhadap nota dinas, yang kaki halamannya sama persis. Pose itu pas dengan tinta yang terlihat; tidak ada bit pola latar yang terbaca dan jawabannya "tidak cukup bukti". Pada set pengembangan tidak ada bukti dokumen lain yang diterima. Pada dokumen yang benar, tahap penyelamat tidak memberi satu pun pose salah (yang tersisa 1, dari jalur lama).
* **Waktu per pelacakan** (3 proses di mesin yang dipakai bersama, beban sekitar 8 sampai 12 pada 8 CPU): median 6,6 -> 9,0 detik, persentil ke-95 23 -> 57 detik, paling lama 57 -> 172 detik. Bila tahap penyelamat berjalan: median 14 detik, persentil ke-95 80 detik. Bukti yang ditemukan jalur lama tidak berubah waktunya.

## Yang tersisa

* **Bagian halaman tanpa teks induk** tidak dapat diregistrasi: 80 potongan dari bagian kosong halaman 2 surat telegram (juga foto: 16).
* **Paragraf pendek** kini hampir selalu ditemukan (237 dari 240), tetapi hanya 161 yang disebut: dua sampai empat baris membawa terlalu sedikit sel pola latar.
* **Foto ponsel sebagian halaman** hampir tidak terbantu (3 bertambah): pencocokan templat hanya mencari skala dan geseran, sedangkan foto berperspektif, dan masker kertas hanya untuk tangkapan layar.
* **Kaki halaman yang sama di dokumen lain.** Potongan yang hanya memuat kaki halaman dapat diregistrasi pada dokumen lain dengan kaki halaman yang sama (9 dari 271 pelacakan dokumen lain). Tidak ada yang disebut, karena pola latar berkunci per dokumen, tetapi jawabannya "tidak cukup bukti", bukan "halaman tidak ditemukan". Uji dokumen lain hanya memakai dua dokumen contoh dengan templat yang sama; formulir dengan banyak halaman berpola sama belum diuji.
* **Waktu.** Bukti yang tetap tidak ditemukan kini memerlukan lebih lama (sampai sekitar 3 menit di mesin yang sibuk), karena tahap penyelamat mencoba setiap halaman.

## Menjalankan

```bash
export TAPAK_REGISTRASI_KERJA=/jalur/kerja    # bawaan: out/riset_registrasi (besar, tidak di-commit)
python research/registrasi/ukur.py terbit --split dev
python research/registrasi/ukur.py lacak --split dev --berkas dev_sebelum.jsonl   # jalur sebelum studi (tahap penyelamat belum ada)
python research/registrasi/pilih.py kumpul --hanya-gagal dev_sebelum.jsonl       # registrasi saja, set dev
python research/registrasi/pilih.py pilih                                       # aturan: hasil/pilihan.json
python research/registrasi/ukur.py terbit --split uji
python research/registrasi/ukur.py lacak --split uji                            # sekali, di akhir
python research/registrasi/ringkas.py --split uji --json
```
