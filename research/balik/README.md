# Pola tanda terbalik, pola penghapusan dua statistik, dan aturan skor dua sisi

Riset untuk tiga perubahan:

1. **Pemeriksaan pola tanda terbalik** (`tapak/decoder/reversal.py`). Dua statistik tanpa kode penerima: z pilot, jumlah pilot dekoder latar dari semua halaman gambar sebagai satu jumlah Rademacher, dan z tanda, A / akar(B) atas bacaan gabungan dengan A = jumlah w (2p - 1)(2y - 1) dan B = jumlah w^2 (2p - 1)^2. Peringatan bila salah satunya paling besar -3,90 (laju 10^-3 dibagi dua, batas sub-Gauss exp(-t^2 / 2)).
2. **Pola penghapusan dengan dua statistik** (`tapak/decoder/erasure.py`). Z dengan aturan latar "pola" dan Z dengan "semua", masing-masing dengan ambang -3,29 (laju 10^-3 dibagi dua).
3. **Aturan skor dua sisi** (riset saja, tidak dipasang). Jatah eps tahap 1 dibagi ke kedua ekor: salinan disebut bila skornya paling sedikit Z(eps1 / 2) atau paling besar -Z(eps1 / 2).

Ketiga peringatan digabung menjadi satu blok di bawah putusan (`tapak/decoder/manipulation.py`): satu kalimat utama, kemungkinan penyebab, laju, dan bahwa tidak ada nama yang disebut. Peringatan tidak mengubah putusan, ambang, atau skor. Semua dokumen dan penerima fiktif; semua foto dan cetakan sintetis.

## Protokol

Protokol, benih, media, laju, aturan rekomendasi, dan analisis ditulis di docstring `ukur.py` dan dicatat di git sebelum benih uji dijalankan (komit `63bbc95`). Benih pengembangan (9401 sampai 9415) hanya dipakai untuk uji coba kering (`hasil/dev.jsonl`); tidak ada laju, ambang, atau aturan yang dipilih darinya. Benih uji (9601 sampai 9640) baru: tidak dipakai `research/sepakat`, `research/kontradiksi`, atau protokol lain.

## Pelaksanaan

* **Uji coba kering** (benih pengembangan, 158 pelacakan, 0 tuduhan salah). Tidak ada peringatan pada bukti jujur. Pada induk tanpa tanda surat telegram skema v1, z tanda -2,97 dan -3,04 (tangkapan layar dan foto dokumen yang sama): bacaan geser induk sebagian ditentukan tipografinya, jadi satu dokumen tanpa tanda punya pusat z tandanya sendiri, seperti pusat Z pola penghapusan. Laju 10^-3 karena itu berlaku rata-rata atas dokumen; protokol tidak diubah.
* **Dijalankan sekali, dengan kode komit protokol.** Benih uji diterbitkan dari salinan kerja, lalu pelari dihentikan di awal bagian `jujur` (belum ada baris) dan dijalankan ulang dari ekspor `git archive` komit `63bbc95`, supaya penyuntingan teks di salinan kerja selama pengukuran tidak menyentuh kode yang diukur. Setiap tugas memakai benihnya sendiri, jadi hasilnya sama dengan satu jalan tanpa henti. Bagian `bench` memakai gambar benchmark README yang dibuat `make bench-check` di ekspor yang sama; `bench_photos.json` di sana sama byte demi byte dengan `docs/results/bench_photos.json`.
* **Di luar protokol:** hanya [peninjauan](#peninjauan-di-luar-protokol) dengan benih baru, setelah pengukuran ini.

## Hasil (benih uji)

Tidak ada tuduhan salah di 2.201 pelacakan benih uji, dengan aturan bawaan maupun aturan skor dua sisi.

**Bukti jujur, alarm palsu** (`jujur`: salinan 1 sampai 5, koalisi 2 dan 3 salinan dengan lima strategi standar, dan induk tanpa tanda dari 6 penerbitan, lewat 7 medium, ditambah penerbitan profil latar cetak dan induk hasil pindai; `bench`: benchmark README). Setiap sel: pola tanda terbalik / pola penghapusan / bacaan jelas tanpa nama.

| Medium | Bukti | Peringatan | z tanda terendah | z pilot terendah |
|---|---|---|---|---|
| PDF | 100 | 0 / 0 / 0 | 26,6 | 113,0 (hanya PDF induk hasil pindai, yang dibaca sebagai gambar) |
| Tangkapan layar | 90 | 0 / 0 / 0 | 21,5 | 35,7 |
| Foto dasar | 93 | 0 / 0 / 0 | 5,2 | -0,5 |
| Foto ISP ponsel | 90 | 0 / 0 / 0 | 16,1 | 12,8 |
| Foto monitor | 90 | 0 / 0 / 0 | 5,0 | 0,2 |
| Cetakan 1 halaman | 97 | 0 / 0 / 0 | 2,9 | -3,1 |
| Cetakan 2 halaman | 100 | 0 / 0 / 0 | 4,2 | -2,7 |
| Induk tanpa tanda (PDF, layar, foto) | 18 | 0 / 0 / 0 | -1,4 | -1,3 |
| Benchmark README (`bench`: layar, cetakan 1 dan 2 halaman, foto ISP, foto monitor) | 128 | 0 / 0 / 0 | 6,0 | -2,0 |

Pada 672 halaman gambar jujur z pilot per halaman terendah -3,14 (ambang -3,90). Z pola penghapusan terendah -2,67 dengan "pola" dan -3,04 dengan "semua"; pada salinan tunggal simpangan baku Z 0,96 dan 0,99.

**Pola penghapusan** (`sadar`, hapus semua yang sama, 36 koalisi per kanal): bukti ditandai.

| Aturan | PDF | Tangkapan layar | Foto | Cetakan 2 halaman | Jumlah |
|---|---|---|---|---|---|
| dua statistik, -3,29 masing-masing (dipasang) | 36 | 36 | 33 | 10 | 115 / 144 |
| "pola" saja, -3,09 (sebelumnya) | 24 | 18 | 17 | 11 | 70 / 144 |
| "semua" saja, -3,09 (lebih dulu lagi) | 36 | 36 | 30 | 0 | 102 / 144 |

Profil latar cetak (`cetakprofil`): 6 dari 6 di PDF, cetakan satu halaman, dan cetakan dua halaman.

**Koalisi yang memahami TAPAK** (`sadar`: 36 koalisi 2 dan 3 salinan per kanal, skema v1 dan v2, N = 20 dan 100; serangan satu salinan 18 per kanal). Setiap sel: pola tanda terbalik / salah satu peringatan, dari 36 (18). Tidak satu pun anggota disebut aturan bawaan pada serangan mana pun, kecuali salinan jujur pembanding.

| Serangan | PDF | Tangkapan layar | Foto | Cetakan 2 halaman |
|---|---|---|---|---|
| jujur (anggota pertama): disebut | 36 | 36 | 35 | 24 |
| hapus | 0 / 36 | 0 / 36 | 0 / 33 | 0 / 10 |
| balik | 36 / 36 | 36 / 36 | 36 / 36 | 36 / 36 |
| balik, derau 4 pada pola latar | 36 / 36 | | | |
| balik 0,8 | 36 / 36 | 36 / 36 | 36 / 36 | |
| balik 0,6 | 35 / 35 | 36 / 36 | 30 / 30 | |
| adaptif (0,40 sampai 0,45) | 0 / 8 | 0 / 1 | 0 / 0 | 0 / 0 |
| acak-sama | 0 / 12 | 0 / 0 | 0 / 0 | |
| buang (latar dibuang, geser dibalik) | 34 / 34 | 32 / 32 | 29 / 29 | |
| buang-acak (latar dibuang, geser diacak) | 0 / 0 | 0 / 0 | 0 / 0 | |
| balik1 (satu salinan, 18) | 18 / 18 | 18 / 18 | 18 / 18 | |
| balik1-buang (satu salinan, 18) | 17 / 17 | 18 / 18 | 15 / 15 | |

Rinciannya: pada PDF z tanda pembalikan -40 sampai -30, juga dengan derau (bacaan jelas tanpa nama: 36 dari 36 tanpa derau, 0 dengan derau); pada tangkapan layar z pilot -64 sampai -43; pada foto z pilot menandai 34 dan z tanda 28 dari 36; pada cetakan hanya z tanda dari geser (-14 sampai -4,0). `buang` dan `balik1-buang` yang lolos hampir semuanya dokumen skema v1 (sekitar 85 sampai 100 unit geser, z tanda -2,1 sampai -3,8). Profil latar cetak: pembalikan ditandai pada 6 dari 6 PDF dan 12 dari 12 cetakan (z pilot median -48 dan -65), satu salinan 9 dari 9.

**Koalisi lebih dari 3** (`besar`, 72 pelacakan, k = 4, 5, 6, strategi acak, mayoritas, minoritas, PDF dan tangkapan layar): tidak ada peringatan pola tanda terbalik (z tanda terendah 8,7, minoritas k = 6) atau pola penghapusan; bacaan jelas tanpa nama 5.

**Aturan skor dua sisi** (tahap 1; Z2 = Z(eps1 / 2)). Anggota disebut lewat ekor bawah pada bukti yang tidak menyebut siapa pun dengan aturan bawaan:

| Serangan | PDF | Tangkapan layar | Foto | Cetakan 2 halaman |
|---|---|---|---|---|
| balik | 36 / 36 | 0 / 36 | 0 / 36 | 1 / 36 |
| balik, derau 4 | 36 / 36 | | | |
| balik 0,8 / 0,6 | 36 / 12 dari 36 | 0 / 0 | 0 / 0 | |
| buang | 1 / 36 | 1 / 36 | 1 / 36 | |
| balik1 | 18 / 18 | 11 / 18 | 7 / 18 | |
| balik1-buang | 14 / 18 | 11 / 18 | 7 / 18 | |
| adaptif, acak-sama, buang-acak, hapus | 0 | 0 | 0 | 0 |

Profil latar cetak: PDF yang dibalik 6 dari 6, satu salinan lewat cetakan 2 dari 3 dan 2 dari 3. Harganya: Z2 / Z 1,020 sampai 1,027 (median 1,022). Nama tahap 1 yang hilang pada bukti jujur: 10 dari 517 pelacakan `jujur` yang menyebut nama (1,9 %; cetakan satu halaman 4 dari 25, dua halaman 2 dari 40, foto monitor 2 dari 82, foto ISP 2 dari 90, PDF, tangkapan layar, dan foto dasar 0), 11 dari 59 pada `besar` (tangkapan layar 8 dari 24), dan 2 dari 121 pada benchmark README (satu foto layar 30 derajat, satu foto cetakan satu halaman). Tingkat kode (`simetri`, 350.000 skor tak bersalah, eps1 = 0,01): skor di atas Z 0 sampai 2,7 x 10^-4, di bawah -Z 5,3 x 10^-4 sampai 1,1 x 10^-3, keduanya di bawah eps1; ekor bawah sekitar sepuluh kali lebih sering.

**Rekomendasi** (aturan di docstring, ditetapkan sebelum dijalankan). (a) Tidak ada tuduhan salah: terpenuhi. (b) Tidak ada nama benchmark README yang hilang: tidak terpenuhi (2 dari 121 hilang). (c) Nama yang hilang pada `jujur` paling banyak 1 %: tidak terpenuhi (1,9 %). (d) Untuk paling sedikit satu medium, anggota disebut pada paling sedikit separuh bukti yang dibalik penuh tanpa nama: terpenuhi (PDF 105 dari 144). Rekomendasinya: **tidak dipasang**. Manfaatnya hampir hanya pada PDF, tempat pemeriksaan pola tanda terbalik sudah memberi peringatan pada setiap pembalikan, sedangkan harganya jatuh pada bukti yang lemah (cetakan, foto ISP dan monitor, koalisi besar), tempat nama paling sulit didapat. Keputusan tetap pada pengelola.

**Biaya.** Pemeriksaan pola tanda terbalik: median 0,1 ms, persentil 95 0,2 ms per bukti.

## Peninjauan (di luar protokol)

Dijalankan setelah pengukuran di atas, tanpa mengubah aturan, laju, atau ambang apa pun (`tinjau.py`; benih baru 9871: nota dinas, N = 20, skema v2; 9872: surat telegram, N = 20, skema v1; profil latar bawaan).

* **Putusan dan skor tidak berubah** (`hasil/tinjau/jejak_master.jsonl`, `hasil/tinjau/jejak.jsonl`). 44 bukti (salinan, koalisi jujur, pembalikan oleh dua dan tiga salinan, penghapusan, pola latar dibuang dengan geser diacak, pembalikan 0,45, dan induk tanpa tanda, lewat PDF, tangkapan layar, foto, dan cetakan dua halaman) dilacak dengan kode `master` dan kode cabang ini. Putusan, ambang, skor setiap salinan, kanal, tahap, pemeriksaan bacaan jelas tanpa nama, catatan lain, dan Z pola penghapusan dengan aturan "pola" identik pada 44 dari 44 pelacakan. Yang berubah hanya peringatan dan Z kedua pola penghapusan.
* **Tanpa kode penerima.** Setiap bukti dilacak lagi dengan semua kata kode diganti kata kode acak, termasuk saat pengamatan dikumpulkan: pengamatan, pemeriksaan pola tanda terbalik, pola penghapusan, dan ambang identik pada 44 dari 44.
* **Angka dengan benih baru.** Bukti jujur (salinan 3 dan koalisi jujur lewat empat medium, induk tanpa tanda lewat PDF dan tangkapan layar): 0 peringatan dari 20; z tanda terendah 4,9 pada bukti bertanda (cetakan dua halaman) dan -0,28 pada induk; z pilot terendah -0,30. Pembalikan oleh dua dan tiga salinan: ditandai 12 dari 12 (z tanda PDF -38,5 sampai -30,8; z pilot tangkapan layar -62,9 sampai -49,5, foto -11,3 dan -29,9; z tanda cetakan dua halaman -11,2 dan -4,8); kode `master` hanya memberi peringatan pada 4 PDF di antaranya. Penghapusan: 4 dari 4 ditandai (`master` 1 dari 4). Pola latar dibuang dengan geser diacak, dan pembalikan 0,45: 0 dari 8.
* **Lolos dari ketiga pemeriksaan** (`hasil/tinjau/lolos.jsonl`, 30 pelacakan lewat PDF, tangkapan layar, dan foto). Tidak satu pun anggota disebut, dan 29 dari 30 tanpa peringatan: satu salinan yang membuang atau mengacak pola latarnya lalu mengacak setiap unit gesernya (12 dari 12), dua salinan yang membuang pola latar lalu mengacak geser yang sama (6 dari 6) atau menghapusnya (5 dari 6; PDF skema v2 ditandai pola penghapusan, z -6,55 dari unit geser saja), dan dua salinan yang membalik tanda yang sama dengan peluang 0,5 (6 dari 6). Yang tersisa di bukti: semua unit geser terbaca jelas (skema v2 425 sampai 439 posisi pada PDF dan 252 pada gambar, v1 97 dan 90 sampai 91), tetapi z tanda hanya -1,1 sampai +2,3, sedangkan salinan jujur lewat medium yang sama +23 sampai +39; pola latar tidak terbaca sama sekali, juga pada PDF yang diteruskan, yang pada salinan jujur selalu membawanya; skor anggota paling besar 0,39 kali Z. Semua itu terlihat tanpa kode penerima, tetapi uji yang menandai bacaan jelas tanpa arah bias harus menganggap bobot dekoder terkalibrasi, jadi alarm palsunya tidak dapat dibatasi.
* **Tampilan.** Blok peringatan di halaman Lacak diperiksa pada lebar 390 dan 1280 px: kalimat temuan tebal, lalu kemungkinan penyebab, laju (warna redup), dan "Ini hanya peringatan" masing-masing di barisnya sendiri; tanpa gulir mendatar.

## Menjalankan

Dari akar repositori (atau ekspor komitnya), paling banyak 3 proses pekerja dengan 1 utas BLAS:

```bash
python research/balik/ukur.py terbit dev --kerja KERJA
python research/balik/ukur.py dev --kerja KERJA --out research/balik/hasil/dev.jsonl
python research/balik/ukur.py terbit uji --kerja KERJA
python research/balik/ukur.py jujur --kerja KERJA --out research/balik/hasil/jujur.jsonl
python research/balik/ukur.py sadar --kerja KERJA --out research/balik/hasil/sadar.jsonl
python research/balik/ukur.py cetakprofil --kerja KERJA --out research/balik/hasil/cetakprofil.jsonl
python research/balik/ukur.py besar --kerja KERJA --out research/balik/hasil/besar.jsonl
python research/balik/ukur.py simetri --out research/balik/hasil/simetri.jsonl
make bench-check   # gambar benchmark README di out/bench-check
python research/balik/ukur.py bench --bench out/bench-check --kerja KERJA --out research/balik/hasil/bench.jsonl
python research/balik/ukur.py ringkas research/balik/hasil/*.jsonl
```

Kolom `job` baris `bench` menyebut folder set foto relatif terhadap `--bench` (misalnya `photos`), jadi baris yang di-commit tidak memuat jalur mesin pengukur dan pelari yang dilanjutkan mengenali barisnya dengan `--bench` mana pun. Baris itu semula ditulis dengan jalur absolut ekspor; hanya kolom itu yang diganti, dan keluaran `ringkas` tetap sama byte demi byte.

Peninjauan (`hasil/tinjau/`, di luar ringkasan protokol; `EKSPOR_MASTER` adalah ekspor `git archive master`):

```bash
python research/balik/tinjau.py terbit --kerja KERJA
python research/balik/tinjau.py jejak --kerja KERJA --akar EKSPOR_MASTER --out research/balik/hasil/tinjau/jejak_master.jsonl
python research/balik/tinjau.py jejak --kerja KERJA --buta --out research/balik/hasil/tinjau/jejak.jsonl
python research/balik/tinjau.py banding research/balik/hasil/tinjau/jejak_master.jsonl research/balik/hasil/tinjau/jejak.jsonl
python research/balik/tinjau.py lolos --kerja KERJA --out research/balik/hasil/tinjau/lolos.jsonl
```

Penerbitan riset (`tapak issue --benih-riset`) ditulis ke folder kerja `KERJA` (bawaan `out/balik`, tidak dicatat di git) dan dapat dibuat ulang byte demi byte dari benihnya. Satu baris JSON per bukti ada di `hasil/`.
