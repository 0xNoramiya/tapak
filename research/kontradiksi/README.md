# Bacaan jelas tanpa nama, dan pemeriksaan pola penghapusan pada cetakan

Riset untuk dua perubahan dekoder:

1. **Pemeriksaan bacaan jelas tanpa nama** (`tapak/decoder/contradiction.py`). Bila tidak ada salinan yang disebut, TAPAK menghitung dari bobot bacaan gabungan batas terbukti peluang koalisi paling banyak c penerima lolos (`tapak.tardos.detection.read_miss_ceiling`, pada ambang tahap 1 yang dipakai). Bila batas itu paling besar 10^-3, bacaan sejelas itu seharusnya menyebut anggota koalisi, jadi TAPAK memberi peringatan. Peringatan tidak menyebut siapa pun dan tidak mengubah putusan, ambang, atau skor.
2. **Pola penghapusan pada cetakan** (`tapak/decoder/erasure.py`). Kekuatan baca pola latar hanya dihitung dari halaman yang pola latarnya ditemukan dekoder. Pada cetakan, pola latar bawaan tidak sampai ke kertas, dan ribuan kekuatan baca yang hanya berisi derau sebelumnya menenggelamkan unit geser.

Semua dokumen dan penerima fiktif. Semua foto dan cetakan sintetis.

## Protokol

Protokol, benih, media, aturan keputusan, dan analisis ditulis di docstring `ukur.py` dan dicatat di git sebelum pengukuran (komit `1c2a2b6`, perbaikan uji coba kering `5425649`). Benih pengembangan (9101 sampai 9115) dipakai untuk dua pilihan; benih uji (9201 sampai 9229) dijalankan sekali, setelah kedua pilihan ditulis di kode dan dicatat (komit `279f1fb`).

* **Pilihan 1, faktor peredam tau.** Plafon laju salah 1 / (1 + exp(tau |L|)) dari LLR gabungan. Aturan: tau terbesar pada kisi 1,0; 0,9; ...; 0,1 yang plafonnya menutupi laju salah terukur di setiap medium dan setiap kelompok |L| (uji Poisson satu sisi, 1 %). Hasil: **tau = 0,3** (`hasil/pilihan_dev.json`).
* **Pilihan 2, bacaan "pola ditemukan".** Dua kandidat: keputusan dekoder sendiri (`pola`) atau salah satu uji kehadiran lolos (`uji`). Keduanya menandai 24 dari 48 bukti hapus pengembangan tanpa alarm jujur, jadi seri dimenangkan **`pola`**. Protokol tidak membandingkan keduanya dengan perilaku lama (`semua`, setiap kekuatan baca latar dihitung), yang pada benih pengembangan yang sama menandai 35 dari 48 (PDF 12, tangkapan layar 12, foto 11, cetakan 0; `pola`: 9, 6, 5, 4).

## Pelaksanaan

* **Penyimpangan.** Dua koalisi U8 di bagian `jujur` (induk hasil pindai) tidak dapat dipalsukan dengan kode riset: `tapak.collusion` membaca pola dari gambar latar salinan teks, sedangkan salinan hasil pindai membawanya di piksel halaman. Keduanya dikeluarkan (6 pelacakan), dicatat di `jujur_jobs`. Tidak ada pilihan lain yang berubah.
* **Dilanjutkan setelah mesin dinyalakan ulang.** Bagian `besar` terputus setelah 18 dari 60 koalisi. Pelari melewati tugas yang sudah tertulis dan setiap tugas memakai benihnya sendiri, jadi 42 sisanya dijalankan dengan benih dan kode yang sama, dan hasilnya sama dengan satu jalan tanpa putus. Bagian lain selesai lengkap (`jujur` 678 baris, `sadar` 846, `lawan` 720, `besar` 180).
* **Di luar protokol.** `tambahan.py` ditambahkan setelah bagian `lawan` dijalankan: salinan jujur pembanding di bagian itu masih membawa kanal teks, yang dibuang setiap pemalsuan. Diagnostik ini menggambar ulang anggota pertama tanpa kanal teks lewat tingkat derau yang sama (`hasil/tambahan.jsonl`, 96 pelacakan). Tidak ada aturan atau faktor yang diubah karenanya.

## Hasil (benih uji)

Tidak ada tuduhan salah di 2.520 pelacakan benih uji (termasuk `tambahan`).

**Bacaan jelas tanpa nama, bukti jujur** (`jujur`). 0 peringatan dari 678 pelacakan. Peringatan hanya mungkin bila tidak ada nama; batas terkecil di antara 177 bukti tanpa nama adalah 1 (juga tanpa peredam).

| Medium | Tanpa nama / bukti | Peringatan |
|---|---|---|
| PDF | 0 / 100 | 0 |
| Tangkapan layar | 0 / 90 | 0 |
| Foto dasar | 7 / 93 | 0 |
| Foto ISP ponsel | 1 / 90 | 0 |
| Foto monitor | 7 / 90 | 0 |
| Cetakan 1 halaman | 75 / 97 | 0 |
| Cetakan 2 halaman | 69 / 100 | 0 |
| Induk tanpa tanda (PDF, layar, foto) | 18 / 18 | 0 |

Per penerbitan (peringatan / tanpa nama / bukti): U1 0/20/108, U2 0/30/108, U3 0/30/108, U4 0/27/108, U5 0/36/108, U6 0/34/108, U7 0/0/21, U8 0/0/9. Median batas penuh pada salinan jujur: PDF 10^-21,5, tangkapan layar 10^-4,7, foto dasar 10^-0,7, lainnya 1.

**Koalisi yang memahami TAPAK** (`sadar`, 36 koalisi 2 dan 3 salinan per sel, v1 dan v2): lolos / peringatan bacaan jelas / peringatan pola penghapusan.

| Serangan | PDF | Tangkapan layar | Foto | Cetakan 2 halaman |
|---|---|---|---|---|
| jujur (anggota pertama) | 0 / 0 / 0 | 0 / 0 / 0 | 1 / 0 / 0 | 16 / 0 / 0 |
| hapus | 36 / 0 / 29 | 36 / 0 / 22 | 36 / 0 / 19 | 36 / 0 / 16 |
| balik | 36 / 36 / 0 | 36 / 0 / 0 | 36 / 0 / 0 | 36 / 0 / 0 |
| acak-sama | 36 / 0 / 13 | 36 / 0 / 3 | 36 / 0 / 0 | |
| adaptif (r 0,40 sampai 0,45) | 36 / 0 / 6 | 35 / 0 / 0 | 36 / 0 / 0 | 36 / 0 / 0 |
| buang | 36 / 0 / 0 | 36 / 0 / 0 | 36 / 0 / 0 | |
| balik1 (satu salinan, 18) | 18 / 18 / 0 | 18 / 0 / 0 | 18 / 0 / 0 | |

Batas pada PDF yang dibalik paling besar 6,3 x 10^-7 (median 4,3 x 10^-9). Pada gambar pola yang dibalik dibaca sebagai "tidak ada pola" (ditemukan 0, 5, dan 1 dari 36), dan sisanya sekitar 220 posisi geser.

**Harga bagi koalisi** (`lawan`, 16 koalisi U1 sampai U4). Tangga `latar`: peringatan pada PDF yang dibalik berhenti pada derau 3 (11 koalisi) atau 4 (5 koalisi) tingkat abu-abu; di sana 2.908 sampai 3.226 posisi terbaca (97 sampai 99 % dari m), jumlah w^2 2.392 sampai 2.849, tidak ada anggota yang disebut, dan salinan jujur dengan derau yang sama disebut 16 dari 16 (tanpa kanal teks, `tambahan`: 16 dari 16 pada derau 3 dan 4, median batas 10^-8,7 dan 10^-4,4, juga bila pola latar dibuang). Tangga `raster`: tidak pernah ada peringatan pada 192 bukti yang dibalik atau dibalik sebagian, dan salinan jujur disebut di setiap tingkat (16 dari 16). Varian adaptif tidak pernah diberi peringatan di kedua tangga (240 bukti); setelah dirender sebagai gambar, 2 dari 16 koalisinya justru disebut pada empat tingkat pertama (8 bukti), karena r dipilih hanya untuk jejak PDF.

**Koalisi lebih dari c** (`besar`, 180 pelacakan): 12 peringatan dari 41 bukti tanpa nama (k = 4: 0 dari 6, k = 5: 3 dari 15, k = 6: 9 dari 20), semuanya tangkapan layar dan foto; PDF selalu menyebut paling sedikit satu anggota.

**Pola penghapusan, aturan `pola`** (bagian 4). Bukti hapus ditandai, `pola` / `semua`: PDF 29 / 36, tangkapan layar 22 / 36, foto 19 / 31, cetakan 2 halaman 16 / 0 (dari 36 masing-masing); jumlahnya 86 / 103 dari 144. Aturan ini membuka cetakan, tetapi menutup sebagian PDF, tangkapan layar, dan foto: di bukti hapus pola latar yang tersisa sering tidak ditemukan, padahal kekuatan bacanya menunjukkan sel yang dihapus. Bukti jujur: 0 alarm dari 638 bukti yang cukup terukur di ketujuh medium (Z terendah -2,32, cetakan 2 halaman), juga 0 dengan `semua`.

**Biaya.** Pemeriksaan sendiri: median 0,28 detik, persentil 95 0,58 detik per bukti (2.424 pelacakan); median 0,25 detik pada 1.408 bukti tanpa nama, satu-satunya saat ia berjalan.

## Menjalankan

Dari akar repositori, paling banyak 3 proses pekerja dengan 1 utas BLAS:

```bash
python research/kontradiksi/ukur.py terbit dev
python research/kontradiksi/ukur.py kalibrasi --out research/kontradiksi/hasil/kalibrasi.jsonl
python research/kontradiksi/ukur.py hapus-dev --out research/kontradiksi/hasil/hapus_dev.jsonl
python research/kontradiksi/ukur.py pilih research/kontradiksi/hasil/kalibrasi.jsonl research/kontradiksi/hasil/hapus_dev.jsonl
python research/kontradiksi/ukur.py terbit uji
python research/kontradiksi/ukur.py sadar --out research/kontradiksi/hasil/sadar.jsonl
python research/kontradiksi/ukur.py jujur --out research/kontradiksi/hasil/jujur.jsonl
python research/kontradiksi/ukur.py lawan --out research/kontradiksi/hasil/lawan.jsonl
python research/kontradiksi/ukur.py besar --out research/kontradiksi/hasil/besar.jsonl
python research/kontradiksi/ukur.py ringkas research/kontradiksi/hasil/*.jsonl
```

Penerbitan riset (`tapak issue --benih-riset`) ditulis ke `out/kontradiksi/` (tidak dicatat di git) dan dapat dibuat ulang byte demi byte dari benihnya. Satu baris JSON per bukti ada di `hasil/`.
