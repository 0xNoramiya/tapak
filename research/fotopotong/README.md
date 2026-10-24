# Foto sebagian halaman beresolusi rendah, dan penolakan yang lebih cepat

[Studi registrasi](../registrasi/README.md) hampir tidak membantu foto ponsel sebagian halaman (3 bertambah dari 208). Penyebabnya ternyata bukan registrasi: foto di sana diambil 4000 piksel lalu dipotong, jadi tahap fitur (SIFT) sudah menemukan hampir semuanya, dan yang tetap gagal hampir semuanya potongan kaki halaman 2 tanpa teks induk. Studi ini menguji kasus yang lebih sulit: pembocor memotret seluruh halaman lalu memotong satu bagiannya, sehingga pikselnya jauh lebih sedikit. Studi ini juga mengukur waktu bukti yang ditolak, yang sejak tahap penyelamat dapat memakan hampir satu menit.

## Foto yang dipotong pembocor

Pada potongan foto utuh 1600 piksel (foto studi kalibrasi), setiap potongan atas, tengah, bawah, dan satu paragraf ditemukan dengan pose benar (192 dari 192). Bila gambar itu diperkecil menjadi sepertiganya, bagian tengah 40 % halaman tinggal sekitar 300 x 200 piksel (35 sampai 45 dpi efektif), dan 6 dari 48 potongan tidak ditemukan. Pada keenamnya SIFT menemukan pose awal yang benar sampai 0,3 sampai 0,9 piksel, tetapi penyempurnaan ECC melenceng darinya:

* jalur awal menyempurnakan pada 100 dpi terhadap bukti yang jauh lebih buram, dan korelasinya berhenti di bawah 0,75;
* tahap penyelamat menganggap kelima gambar itu tangkapan layar, karena kertas pada foto yang diperkecil serata kertas tangkapan layar (`is_screen_capture`), lalu memakai peta afin, yang tidak dapat mengikuti perspektif foto miring;
* ECC homografi terhadap seluruh halaman juga melenceng 20 sampai 60 piksel, sedangkan ECC terhadap induk yang dipotong ke jejak foto pada pose awal konvergen (korelasi 0,96 sampai 0,98).

**Perubahan** (`rectify.rescue_register`). Pose awal yang miring (`_tilted`: berputar lebih dari 1 derajat, atau skala lokalnya berbeda lebih dari 2 % di bagian halaman yang terlihat, yaitu perspektif foto) juga disempurnakan dengan homografi terhadap induk yang dipotong ke jejaknya, diperluas 15 % (`RESCUE_FOOTPRINT`, asal pose `<asal>:jejak`). Pose itu lalu melewati verifikasi yang sama (kewajaran skala, kecocokan dengan induk 0,65, uji ambigu). Pose jejak yang membuat resolusi di tengah halaman lebih dari 4 kali berbeda dari pose awal dianggap tidak wajar. Pose lain dihitung persis seperti sebelumnya.

**Galat yang ditemukan di jalan.** Pada potongan miring beresolusi rendah, sebuah pose dapat menaruh tengah halaman pada sepersekian resolusinya sendiri, dan verifikasi lalu meminta kabur Gaussian yang tidak muat di memori (`cv2.error: std::bad_alloc`). Pelacakan bukti seperti itu gagal dengan galat server. `pose_agreement` kini menolak pose dengan rasio lebih dari 16 piksel induk per piksel bukti di tengah halaman (`RESCUE_MAX_BLUR`).

**Set pengembangan** (foto K1 dan K2: 900 potongan, termasuk potongan terhadap dokumen lain). Ditemukan 691 menjadi 702, pose salah 0 menjadi 0, potongan diterima pada dokumen lain 0 menjadi 0. Percobaan jejak dijalankan pada 191 potongan.

**Set uji** (foto U1 dan U2, protokol dan kode dicatat di git sebelum dijalankan, sekali; 1.500 potongan; setiap potongan yang diregistrasi dilacak):

| Potongan | Skala | Sebelum: ditemukan (benar / kasar / salah) | Sesudah |
|---|---|---|---|
| halaman utuh | 1,0 | 80 dari 80 (80 / 0 / 0) | 80 (80 / 0 / 0) |
| halaman utuh | 0,5 | 80 dari 80 (80 / 0 / 0) | 80 (80 / 0 / 0) |
| halaman utuh | 0,35 | 80 dari 80 (80 / 0 / 0) | 80 (80 / 0 / 0) |
| atas 30 % | 1,0 | 80 dari 80 (80 / 0 / 0) | 80 (80 / 0 / 0) |
| atas 30 % | 0,5 | 78 dari 80 (75 / 3 / 0) | 78 (75 / 3 / 0) |
| atas 30 % | 0,35 | 75 dari 80 (69 / 5 / 1) | 75 (69 / 5 / 1) |
| tengah 40 % | 1,0 | 80 dari 80 (80 / 0 / 0) | 80 (80 / 0 / 0) |
| tengah 40 % | 0,5 | 79 dari 80 (79 / 0 / 0) | 79 (79 / 0 / 0) |
| tengah 40 % | 0,35 | 78 dari 80 (78 / 0 / 0) | 79 (79 / 0 / 0) |
| bawah 40 % | 1,0 | 80 dari 80 (80 / 0 / 0) | 80 (80 / 0 / 0) |
| bawah 40 % | 0,5 | 80 dari 80 (80 / 0 / 0) | 80 (80 / 0 / 0) |
| bawah 40 % | 0,35 | 80 dari 80 (80 / 0 / 0) | 80 (80 / 0 / 0) |
| satu paragraf | 1,0 | 78 dari 80 (78 / 0 / 0) | 78 (78 / 0 / 0) |
| satu paragraf | 0,5 | 74 dari 80 (73 / 0 / 1) | 76 (76 / 0 / 0) |
| satu paragraf | 0,35 | 63 dari 80 (60 / 0 / 3) | 67 (66 / 0 / 1) |

* **Pose.** Ditemukan 1.165 menjadi 1.172. Pose salah pada dokumen yang benar 5 menjadi 2: semuanya dari pose templat yang sudah ada sebelum studi ini (paragraf dan bagian atas pada setengah dan sepertiga ukuran), dan percobaan jejak menggeser sebagiannya ke pose yang benar. Tidak ada pose salah yang menyebut nama.
* **Dokumen lain.** Potongan yang diregistrasi terhadap dokumen lain: 0 menjadi 0.
* **Putusan.** Salinan yang disebut 919 menjadi 919; tuduhan salah 0 dan 0. Potongan yang baru ditemukan hampir semuanya satu paragraf atau bagian tengah pada sepertiga ukuran, yang membawa terlalu sedikit bit: jawabannya tetap "tidak cukup bukti". Registrasi bukan lagi batasnya di sana, kapasitas yang menjadi batas.
* **Waktu per potongan** (satu utas penyelamat per proses, tiga proses): median 3,1 detik, persentil ke-95 74 detik.

## Penolakan yang lebih cepat

Pada bukti yang ditolak (dokumen lain, gambar bukan dokumen), registrasi mencoba setiap halaman dan setiap pose awal. Profil satu penolakan (potongan dokumen tak terkait, 46 detik): 20 detik untuk kabur Gaussian di perataan cahaya (`_prep`), yang dihitung 23 kali untuk gambar yang sama, 17 detik untuk ECC, 2 detik untuk Tesseract (sekali per halaman untuk gambar yang sama), dan 2 detik untuk SIFT (fitur bukti dihitung ulang per halaman).

* **Pekerjaan yang sama dihitung sekali.** Tinta induk (`master_ink`) dan fitur SIFT induk (`master_features`) disimpan per dokumen, halaman, dan resolusi; tinta, fitur, dan kata OCR bukti dihitung sekali per registrasi. Hasilnya sama persis: pada 100 gambar contoh set uji registrasi (termasuk 21 penolakan), setiap homografi, korelasi, metode, dan seluruh catatan registrasi identik dengan kode sebelumnya.
* **Percobaan penyelamat berjalan berdampingan** (`rescue_threads`, paling banyak 4 utas, dan paling banyak `TAPAK_WORKERS`). Hasil setiap percobaan tidak bergantung pada yang lain dan urutannya tetap, jadi putusannya sama.

**Waktu** (`waktu.py`, `hasil/waktu_sebelum.json` dan `hasil/waktu_sesudah.json`; kode sebelum dan sesudah dijalankan berurutan di mesin yang sama, sementara tiga proses studi lain berjalan, tanpa batas `TAPAK_WORKERS`):

| Registrasi | Sebelum | Sesudah |
|---|---|---|
| Penolakan (11 kasus peninjauan registrasi: potongan dokumen tak terkait, pita kosong, tepi, kaki halaman), median | 39,5 detik | 18,3 detik |
| Penolakan, paling lama | 58 detik | 35 detik |
| Penolakan, seluruhnya | 387 detik | 177 detik |
| Bukti biasa (16 gambar set uji registrasi), median | 3,4 detik | 2,8 detik |

Setiap keputusan sama (diterima atau ditolak, dan metodenya). Satu potongan tangkapan layar halaman 2 yang tetap tidak ditemukan tidak menjadi lebih cepat (31 dan 36 detik; diukur ulang sendirian 27 detik, dengan tiga percobaan templat dan tanpa percobaan jejak).

## Menjalankan

```bash
export PYTHONPATH=. TAPAK_KALIBRASI_KERJA=out/riset_kalibrasi TAPAK_FOTOPOTONG_KERJA=out/riset_fotopotong
F=".venv/bin/python research/fotopotong/ukur.py"
$F jalan --split dev && $F ringkas --split dev
$F jalan --split uji && $F ringkas --split uji      # sekali
```

Studi ini memakai bukti dan pengamatan studi kalibrasi (`$TAPAK_KALIBRASI_KERJA`). Setiap proses memakai satu utas penyelamat (`TAPAK_WORKERS=1`), karena tiga proses berbagi mesin.
