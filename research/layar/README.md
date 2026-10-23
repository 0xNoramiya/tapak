# Tangkapan layar dari penampil PDF sungguhan

Batasan 5 di [keamanan](../../docs/keamanan.md#batasan) dulu hanya berupa klaim: geser baris rentan pada tangkapan layar beresolusi rendah karena penampil membulatkan garis dasar ke piksel. Studi ini mengukurnya. Halaman digambar oleh pustaka yang dipakai penampil PDF, bukan oleh simulator tangkapan layar `tapak/photos.py` (yang mengecilkan render 200 dpi dengan rata-rata luas).

| Penggambar | Dipakai oleh | Cara menggambar di studi ini |
|---|---|---|
| `mupdf` | SumatraPDF, mupdf, zathura-mupdf | pymupdf `get_pixmap`, anti-aliasing bawaan |
| `poppler` | Okular, qpdfview (pengaturan bawaan) | `pdftoppm -aa yes -aaVector yes` (Splash, tanpa hinting) |
| `poppler_tanpa_aa` | penampil Poppler dengan anti-aliasing dimatikan | `pdftoppm -aa no -aaVector no` |
| `cairo` | Evince, GNOME Papers, Atril, Xreader | `pdftocairo` |

`pdftoppm` 24.02 tidak punya pilihan hinting, jadi pengaturan "text hinting" Okular (mati secara bawaan) tidak tercakup. Peramban (PDF.js, PDFium) dan Adobe Reader tidak tersedia di mesin uji dan tidak diukur.

## Di mana penampil meletakkan glif

`kuantisasi.py` menggambar sepuluh glif yang digeser sepersekian piksel dan mengikuti titik berat tintanya (`hasil/kuantisasi.json`, 11 pt, 28 sampai 225 dpi):

* **Vertikal**: MuPDF dan Splash (dengan dan tanpa anti-aliasing) meletakkan garis dasar setiap baris pada piksel utuh. Cairo memakai seperempat piksel. Di bawah 56 dpi (glif 11 pt di bawah sekitar 8 piksel per em) MuPDF memakai setengah piksel yang tidak rata: langkahnya 0,47 sampai 0,55 piksel pada 28 sampai 48 dpi (diukur saat pemilihan dekoder).
* **Horizontal**: setiap glif diletakkan pada seperempat piksel (Splash tanpa anti-aliasing: piksel utuh). Glif satu kelompok kata jatuh pada fase yang berbeda, jadi geser kelompok tetap tersisa sebagian sebagai rata-rata pembulatan glifnya. Pada kerapatan tinggi subpiksel ditinggalkan: Splash meletakkan glif 11 pt pada piksel utuh pada 225 dpi, MuPDF pada setengah piksel mulai 180 dpi (diukur setelah set uji, saat menjelaskan hasil format `kecil`).

Geser baris 0,05 mm adalah 0,08 sampai 0,3 piksel pada 40 sampai 150 dpi. Pada MuPDF dan Splash geser itu hilang dibulatkan, atau memindahkan baris satu piksel penuh. Geser kelompok kata v2 (0,025 mm) adalah 0,04 sampai 0,15 piksel.

## Protokol

Protokol dan semua benih ditetapkan di `ukur.py` (`PROTOCOL`) dan masuk riwayat repositori sebelum pengukuran pertama (commit "Screenshot study protocol").

* **Penerbitan.** Nota dinas dan surat telegram contoh (fiktif) lewat `tapak issue --benih-riset BENIH --no-registry` untuk N = 20 penerima (c = 3, eps = 10^-6, profil latar bawaan), sekali dengan skema geser v2 (bawaan) dan sekali dengan v1, dengan benih yang sama: kode dan id salinan sama, jadi gambar v1 dan v2 satu pekerjaan hanya berbeda pada salinannya. Bukti adalah halaman 1.
* **Dua set benih.** `dev` (benih riset 7501 dan 7502, benih bukti 7511) untuk setiap pilihan dekoder. `uji` (7601 dan 7602, benih bukti 7611, induk tanpa tanda 7699) dibuat dan dilacak sekali di akhir.
* **Resolusi efektif** 28, 32, 40, 48, 56, 64, 72, 84, 96, 120, dan 150 dpi: penampil laptop pas halaman (sekitar 60 sampai 85 dpi), pada 100 % (72 atau 96 dpi) dan diperbesar, ponsel pas lebar (sekitar 90 sampai 130 dpi), tampilan dua halaman atau gambar mini (di bawah 50 dpi).
* **Format tangkapan.** `png` (tanpa kompresi, seperti tangkapan Android, iOS, Windows, dan GNOME); `pesan` (sisi panjang paling besar 1600 px, JPEG mutu 68 sampai 72 lalu diteruskan sekali lagi pada 58 sampai 62); `kecil` (halaman digambar pada 1,5 kali resolusi oleh layar berkerapatan tinggi, lalu tangkapannya diperkecil aplikasi pesan ke resolusi efektif dan dikompresi seperti `pesan`).
* **Bingkai.** `utuh` (halaman saja) dan `bingkai` (halaman di jendela penampil: latar, bilah alat, tepi dan bayangan halaman, tema terang atau gelap) bergantian per salinan. Grid `potong` memperlihatkan 55 % tinggi halaman (dari atas atau dari 25 %) di jendela penampil, seperti tampilan yang diperbesar, pada 64 sampai 150 dpi.
* **Grid.** `utama`: tiga penggambar utama x 11 resolusi x 3 format, halaman utuh. `tanpa_aa`: Splash tanpa anti-aliasing, png dan pesan. `potong`: jendela sebagian. `induk`: tangkapan induk tanpa tanda, dilacak terhadap kedua penerbitan set yang sama; tidak boleh ada yang dituduh. Set dev memakai salinan 1, 8, dan 15 (v2) dan 1 dan 8 (v1); set uji salinan 2, 5, 9, 12, 16, dan 19 (v2) dan 2, 9, dan 16 (v1).
* **Pelacakan** seperti `make bench`: tanpa registri, seluruh eps, satu tahap, lewat jalur produksi (`collect_from_gray`). Pengamatan yang sama dituduh tiga kali: semua kanal, kanal geser saja, dan kanal latar saja. Putusan: benar (tepat salinan yang bocor), tidak cukup bukti, atau salah (siapa pun selain itu; siapa pun untuk induk tanpa tanda).
* **Ukuran per gambar.** Posisi terbaca dan bit salah di antara yang terbaca (tanda LLR terhadap kode salinan yang bocor) untuk baris, kelompok kata, dan latar; bit salah yang yakin (abs LLR paling sedikit 2 dan 4); skor salinan yang benar dan skor tak bersalah tertinggi sebagai kelipatan ambang; batas peluang tuduhan salah; peringatan penghapusan; dan kelompok bobot w = tanh(abs(L)/2) seperti `research/deteksi/llr_foto.py`.
* **Batas bawah resolusi** (aturan ditetapkan sebelum dijalankan): per penggambar, format, dan kumpulan kanal, resolusi grid terendah yang mulai dari sana setiap gambar halaman utuh pada resolusi itu dan semua resolusi di atasnya menyebut salinan yang bocor.

## Pemilihan dekoder (set dev)

Semua gambar dev dilacak sekali dengan dekoder sebelum studi ini; registrasi, perpindahan kata, dan pengamatan latarnya disimpan. `kandidat.py` mendekode ulang kanal geser dari perpindahan yang sama untuk setiap kandidat, lalu menuduh dengan aturan tetap. Aturan pemilihan ditulis di `kandidat.py` (`ATURAN`) dan masuk riwayat sebelum kandidat dinilai pada seluruh set dev: (1) tidak ada tuduhan salah, (2) tidak ada penggambar dan format yang kehilangan putusan benar (semua kanal maupun geser saja), (3) bit baris yang salah dengan yakin (abs LLR paling sedikit 4) turun paling sedikit separuh, dan (4) baris yang didekode dengan model kandidat terkalibrasi: di setiap kelompok bobot dengan paling sedikit 50 bit, laju salahnya paling besar 1,5 kali (1 - w)/2 ditambah 1 poin persentase. Aturan itu tidak diubah selama tiga putaran penilaian (`hasil/dev_kandidat_putaran*_ringkas.json`, keputusan di `hasil/pilihan.json`).

Dengan dekoder lama, bit baris (semua penggambar) salah 31 % pada bobot 0,5 sampai 0,8 (terkalibrasi 17 %) dan 4,5 % pada bobot di atas 0,95 (terkalibrasi 0,5 %); pada MuPDF dan Splash 10 sampai 14 % di atas 0,95. Ada 204 bit baris salah dengan yakin di set dev. Penyebabnya terlihat pada satu salinan pengembangan: dengan jarak baris yang bukan kelipatan piksel, pembulatan baris tetangga bergeser pelan lalu melompat satu piksel, sehingga baris data di antara tetangga yang melompat dan yang tidak berada setengah piksel dari tempatnya, apa pun tandanya. Dekoder lama membaca setengah piksel itu sebagai tanda, dan membuang baris yang benar-benar pindah satu piksel sebagai pencilan (lebih dari 3 kali geser).

| Kandidat | Baris salah yakin (lama 204) | Putusan geser saja benar (lama 238) | Aturan |
|---|---|---|---|
| `kuantum_baris`: galat pembulatan seragam dan saling bebas | 112 | 242 | gagal (3) |
| `kisi_baris`: kisi piksel utuh | 112 | 245 | gagal (3) |
| `kisi_baris2`: kisi 1, 1/2, dan 1/4 piksel | 96 | 247 | gagal (4): baris setengah piksel |
| `kisi_baris3`: kisi 1 dan 1/4 piksel | 101 | 247 | lolos, dipilih |

`kisi_baris3` (sekarang di `tapak/decoder/ch_shift.py`, `rounded_rows`):

* **Gerbang.** Posisi baris kontrol (tanpa tanda, jadi tanpa kode penerima) dipetakan ke gambar lewat homografi registrasi. Bila paling sedikit 8 baris kontrol terukur dan posisinya modulo satu piksel, atau modulo seperempat piksel, berkumpul dengan panjang resultan rata-rata paling sedikit 0,7, halaman itu tangkapan yang tidak diskalakan ulang dan barisnya dibaca dengan model kisi. Sebelum penilaian: tangkapan MuPDF dan Splash yang tidak diskalakan 0,9 sampai 0,98 dari 56 dpi ke atas, foto, foto monitor, dan tangkapan dari simulator `tapak/photos.py` paling besar 0,43. Dua puluh baris tanpa hubungan dengan kisi mencapai 0,7 dengan peluang sekitar 10^-4. Tangkapan yang diperkecil (`kecil`), MuPDF di bawah 56 dpi (langkah setengah pikselnya tidak rata, 0,47 sampai 0,55 piksel), foto, dan pindaian tetap memakai model Gaussian.
* **Model.** Penggambar menaruh baris j pada piksel round(k y_j + phi). Setiap baris kontrol membatasi (k, phi) pada satu pita; dengan prior rata pada irisan pita-pita itu, LLR tanda sebuah baris data adalah log perbandingan luas bagian irisan tempat garis dasarnya plus dan minus geser jatuh pada piksel yang terukur. Geser yang hilang dibulatkan memberi LLR 0; geser yang memindahkan baris satu piksel terbaca. Peluang 1 % untuk piksel yang tidak diramalkan membatasi abs LLR pada 4,6.
* **Kalibrasi pada set dev.** Baris yang dibaca model kisi: bobot di atas 0,95 4.752 bit, 0 salah; 0,8 sampai 0,9 132 bit, 7,6 % salah (terkalibrasi 7,2 %). Kisi seperempat piksel (Cairo) 2.525 bit di atas 0,95 tanpa salah.

## Hasil (set uji)

Dilacak sekali dengan `kisi_baris3` (commit dan hash sumber dekoder di `hasil/uji_dekoder.json`): 2.250 gambar, 2.346 pelacakan (`hasil/uji.jsonl`, tabel lengkap `ringkas.py --split uji`, angka di `hasil/ringkas_uji.json`). Perpindahan yang sama didekode ulang dengan dekoder lama untuk perbandingan berpasangan (`hasil/uji_kandidat.jsonl.gz`, `hasil/ringkas_uji_banding.json`).

**Batas bawah satu halaman utuh**, skema v2 (dpi terendah yang mulai dari sana setiap tangkapan menyebut salinan; 28 berarti sampai resolusi terendah yang diuji):

| Penggambar | Semua kanal: PNG / pesan / kecil | Geser saja: PNG / pesan / kecil | Latar saja |
|---|---|---|---|
| MuPDF | 28 / 32 / 32 | 120 / 120 / 84 | sama dengan semua kanal |
| Poppler Splash | 32 / 32 / 40 | 96 / 96 / tidak pernah | sama |
| Poppler Cairo | 28 / 32 / 40 | 96 / 96 / 72 | sama |
| Splash tanpa anti-aliasing | 48 / 56 (PNG / pesan) | tidak pernah | sama |

* Setiap kegagalan halaman utuh adalah registrasi yang gagal (28 sampai 32 dpi; tanpa anti-aliasing sampai 48 dpi). Setiap halaman yang ditemukan disebut; skor paling kecil 1,9 kali ambang, batas peluang tuduhan salah paling besar 10^-19,5. Skema v1: batas semua kanal 28 sampai 32 dpi, kanal geser tidak pernah cukup sendirian (skor paling besar 0,76 ambang).
* Bit kata salah (PNG): sekitar 35 % pada 28 sampai 48 dpi, 14 % pada 56 sampai 84 dpi, 2 sampai 3 % dari 96 dpi; Splash tanpa anti-aliasing 25 sampai 44 %. Galat bit latar pada format pesan: 15 sampai 17 %, 4 %, dan 1 %; pada PNG paling besar 1 % (Splash tanpa anti-aliasing 2 % di bawah 56 dpi).
* Tangkapan Poppler yang digambar 1,5 kali lebih rapat (180 dan 225 dpi) lalu diperkecil ke 120 dan 150 dpi: bit kata salah 16 sampai 17 %, geser saja menyebut 4 dari 24, karena Splash meletakkan glif besar pada piksel utuh (`kuantisasi.py`).
* Jendela sebagian: dari atas halaman 120 dari 120 ditemukan dan disebut; dari tengah halaman 60 dari 120 ditemukan, semua yang ditemukan disebut.
* Tidak ada tuduhan salah (192 pelacakan induk tanpa tanda, skor tertinggi 0,35 ambang; skor tak bersalah tertinggi 0,64 ambang). Peringatan pola penghapusan pada 3 dari 2.154 pelacakan salinan jujur.

**Sebelum dan sesudah** (pengukuran yang sama):

| | Dekoder lama | `kisi_baris3` |
|---|---|---|
| Bit baris salah yakin (abs LLR paling sedikit 4) | 470 | 243 |
| Splash dengan dan tanpa anti-aliasing | 149 | 0 |
| MuPDF PNG dan pesan | 103 | 56 |
| Cairo PNG dan pesan | 109 | 78 |
| Tangkapan yang diperkecil (tidak berubah) | 109 | 109 |
| Bit baris berbobot di atas 0,95: salah | 5,4 % (terkalibrasi 0,5 %) | 2,1 % (0,8 %) |
| Baris model kisi berbobot di atas 0,95 | | 8.458, 2 salah |
| Putusan geser saja benar | 516 | 542 (27 bertambah, 1 hilang) |
| Putusan semua kanal benar | 2.041 | 2.041 |
| Tuduhan salah | 0 | 0 |
| Skema v1: bit baris salah yakin; putusan | 135; 582 benar | 79; 582 benar |

Bit kata di bawah 56 dpi tetap terlalu yakin (bobot di atas 0,95 salah 4,4 %, terkalibrasi 0,9 %), dan baris yang tidak lolos gerbang (tangkapan yang diskalakan ulang, juga pesan 150 dpi yang dibatasi 1600 px; MuPDF di bawah 56 dpi; Cairo di bawah 64 dpi, tempat gerbang tidak pernah terbuka pada 28 sampai 40 dpi dan jarang pada 56 dpi, PNG maupun JPEG) tetap memakai model Gaussian: pada 28 sampai 48 dpi bit baris dengan abs LLR paling sedikit 2 salah 24 sampai 27 % (MuPDF) dan 14 sampai 18 % (Cairo). Bobot pola latar setelah JPEG terlalu yakin di kelompok tertinggi: bobot di atas 0,95 salah 1,8 % pada 28 sampai 48 dpi (terkalibrasi 0,7 %), 0,9 % pada 56 sampai 84 dpi (0,2 %), dan 0,5 % dari 96 dpi (0,1 %); PNG 0,1 % (`calibration_bands` di `hasil/ringkas_uji.json`, ditambahkan saat peninjauan). Batas deteksi dengan laju (1 - w)/2 karena itu tidak berlaku untuk tangkapan layar.

Batasan: penggambarannya sungguhan, tetapi bingkai, potongan, dan kompresi disimulasikan; dua dokumen contoh, halaman 1, satu rahasia kode per dokumen dan set, jadi tangkapan dalam satu sel tidak saling bebas sepenuhnya. PDF.js, PDFium, Adobe Reader, hinting, layar ponsel dan aplikasi pesan sungguhan belum diuji.

## Pengulangan dengan benih baru (peninjauan)

Ditambahkan saat peninjauan, setelah set uji; tidak ada pilihan dekoder yang dibuat di sini. `ulang.py` memakai fungsi `ukur.py` tanpa perubahan dengan benih riset yang belum pernah dipakai (nota dinas 7901, surat telegram 7902, benih bukti 7911, induk tanpa tanda 7999): skema v2, salinan 4 dan 13, keempat penggambar, semua resolusi dan format grid `utama` dan `tanpa_aa` (4 gambar per sel; set uji 12), dan induk tanpa tanda pada 32, 56, 96, dan 150 dpi. 532 gambar (`hasil/ulang.jsonl.gz`, angka di `hasil/ringkas_ulang.json`).

| Penggambar | Semua kanal: PNG / pesan / kecil | Geser saja: PNG / pesan / kecil |
|---|---|---|
| MuPDF | 28 / 32 / 32 | 96 / 96 / tidak pernah |
| Poppler Splash | 28 / 32 / 28 | 120 / 120 / tidak pernah |
| Poppler Cairo | 28 / 28 / 28 | 96 / 96 / 84 |
| Splash tanpa anti-aliasing | 48 / 56 (PNG / pesan) | tidak pernah |

* Batas semua kanal sama dengan set uji atau lebih rendah (sel yang lebih kecil lebih jarang memuat gambar yang gagal), dan kanal latar saja memberi batas yang sama di setiap sel. Setiap kegagalan adalah registrasi yang gagal (28 dpi; Splash tanpa anti-aliasing sampai 48 dpi); setiap halaman yang ditemukan disebut, skor paling kecil 1,8 kali ambang, batas peluang tuduhan salah paling besar 10^-18,4. Tidak ada tuduhan salah dalam 532 pelacakan, termasuk 48 induk tanpa tanda (skor tertinggi 0,38 ambang).
* Batas geser saja bergeser antarbenih, karena skornya dekat ambang: pada 84 sampai 150 dpi median 1,2 kali ambang di set uji, dan pada surat telegram benih baru (210 kelompok kata) hanya 1,05. Gambar yang sedikit di bawah ambang (0,95 sampai 0,99) memindahkan batas Splash dari 96 ke 120 dpi dan batas MuPDF yang diperkecil dari 84 dpi ke tidak pernah.
* Sebelum dan sesudah (`hasil/ulang_kandidat.jsonl.gz`): bit baris salah yakin 100 menjadi 48 (Splash dengan dan tanpa anti-aliasing 43 menjadi 0, tangkapan yang diperkecil tetap 25), baris model kisi berbobot di atas 0,95 1.889 bit tanpa salah (0,8 sampai 0,9: 6,7 %, terkalibrasi 7,4 %), putusan geser saja benar 164 menjadi 165 (1 bertambah, 0 hilang), putusan semua kanal sama (468).

## Menjalankan

```bash
export TAPAK_LAYAR_KERJA=/jalur/kerja       # bawaan: out/riset_layar (besar, tidak di-commit)
python research/layar/ukur.py terbit         # penerbitan kedua set dan kedua skema
python research/layar/ukur.py lacak --split dev
python research/layar/kandidat.py nilai sekarang,kuantum_baris,kisi_baris   # putaran 1, set dev saja
python research/layar/kandidat.py nilai sekarang,kisi_baris,kisi_baris2     # putaran 2
python research/layar/kandidat.py nilai sekarang,kisi_baris3                # putaran 3
python research/layar/kandidat.py pilih      # aturan atas semua putaran: hasil/pilihan.json
python research/layar/ukur.py lacak --split uji   # sekali, di akhir
python research/layar/kandidat.py nilai sekarang,kisi_baris3 --split uji --acuan kisi_baris3
python research/layar/ringkas.py --split uji --json
python research/layar/ringkas.py --split uji --banding --json
python research/layar/kuantisasi.py --dpi 28,32,40,48,56,72,96,150,180,225   # letak glif per penggambar
python research/layar/ulang.py terbit       # peninjauan: benih baru (set rev), lalu:
python research/layar/ulang.py lacak && python research/layar/ulang.py banding && python research/layar/ulang.py ringkas
```

Setiap putaran `kandidat.py` menulis `hasil/dev_kandidat.jsonl.gz` dan `hasil/dev_kandidat_ringkas.json`; di repositori keduanya disimpan sebagai `dev_kandidat_putaranN...`.

Kolam proses dibatasi 3, BLAS dan OpenCV satu utas. Gambar bukti, pengamatan, dan registrasi ada di `$TAPAK_LAYAR_KERJA`; baris JSON yang dikutip dokumentasi ada di `hasil/`.
