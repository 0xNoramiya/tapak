# Kalibrasi bobot geser kata pada bukti gambar

[Studi kalibrasi pola latar](../kalibrasi/README.md) menyisakan satu masalah: bit kelompok kata (kanal geser, skema v2) tetap terlalu yakin pada foto, foto ISP ponsel, foto monitor, foto cetakan, tangkapan simulator, dan tangkapan 28 sampai 48 dpi. Pada set ujinya, bobot di atas 0,999 salah 80 dari 2.781 pada foto dasar dan 92 dari 3.558 pada foto cetakan, padahal bobotnya hanya menjanjikan sekitar 0,2 salah. Karena itu batas deteksi dengan laju (1 - w)/2 ([batasan 12](../../docs/keamanan.md#batasan-12)) tidak berlaku untuk foto dan cetakan. Studi ini mencari penyebabnya, memilih model kelompok kata yang buta kode pada bukti pengembangan, lalu menjalankan bukti uji baru sekali.

Tidak ada ambang tuduhan, eps, aturan pembagian eps, atau aturan putusan yang berubah, dan tidak ada dekoder yang melihat kode penerima. Kode penerima hanya dipakai di sini untuk menghitung bit yang salah. Batas tuduhan salah tidak bergantung pada kalibrasi. Semua dokumen dan penerima fiktif; semua tangkapan, foto, dan cetakan sintetis.

## Penyebab (bukti pengembangan)

Bukti pengembangan adalah semua bukti gambar studi kalibrasi, kedua split-nya (keduanya sudah diukur dan dilaporkan di sana, jadi tidak ada yang ditahan di sini). Registrasi tersimpan setiap bukti dipakai lagi: halaman yang sama diukur ulang, dan dekoder sebelum studi ini mengulang setiap keluaran geser yang tersimpan (1.331 bukti gambar, 0 berbeda). Untuk salinan tunggal, tanda fisik setiap kelompok diketahui, jadi residu baris sebenarnya (setelah gangguan baris diproyeksikan keluar) dapat dibakukan dengan sigma yang ditaksir dekoder.

* **Ekor tebal pada foto dan cetakan.** Residu baku kelompok kata bervarians 1,7 sampai 1,8 dengan kurtosis 7 sampai 9 (Gauss: 3) pada foto dan foto cetakan, dan 4 % kelompok lebih dari 3 sigma (Gauss: 0,3 %). Pada foto tegak lurus (sudut 0) variansnya sekitar 1; makin miring, makin besar (sampai 5 pada satu foto 20 derajat). Kelompok yang bergeser lebih dari delta ke arah lain terbaca sebagai tanda yang yakin dan salah.
* **Kecocokan templat yang buruk.** Di dalam satu bukti, kelompok dengan korelasi puncak templat terendah (1 - puncak relatif terhadap median bukti, seperlima teratas) bervarians 2,6 kali dan 7 % di atas 3 sigma, seperlima terbaik 1,2 kali dan 2 %. Residu tidak berkorelasi antartetangga sebaris.
* **Tanda yang mengecil di resolusi rendah.** Dengan tanda yang benar, geseran terukur hanya 0,53 (20 sampai 30 dpi efektif), 0,65 (30 sampai 36), dan 0,69 (36 sampai 44) kali tanda yang diterbitkan, lalu sekitar 0,95 mulai 44 dpi. Dekoder memakai tanda penuh, jadi bobotnya terlalu besar di semua kelompok bobot rendah dan menengah.
* **Penguatan per bukti tidak dapat ditaksir.** Model yang menaksir penguatan tanda per bukti (EM atas tanda yang tersembunyi) justru lebih buruk (46 sel terlalu yakin, sebelumnya 34): dengan tanda tersembunyi, penguatan dan derau saling menggantikan.

## Kandidat dan pemilihan

Semua kandidat (`ch_shift.WORD_MODELS`) hanya mengubah LLR kelompok kata bukti gambar. Baris, medan halaman, kelompok yang dibuang, sigma, dan kekuatan (pemeriksaan pola penghapusan) tetap dari dekoder Gauss, dan PDF yang diteruskan didekode persis seperti sebelumnya. Model t: kemungkinan baris Student t dengan nu derajat kebebasan; offset dan kemiringan baris dicocokkan per pola tanda dengan kuadrat terkecil berbobot ulang; 2^g pola tetap dihitung semua; skala t ditaksir dengan EM atas semua baris. `redam`: di bawah 44 dpi efektif tanda dianggap 0,6 kali ukurannya. `puncak`: skala tiap kelompok sebanding dengan (1 - korelasi puncak) relatif terhadap median bukti, dibatasi 1/4 sampai 4, dipangkatkan 1 atau 0,5.

Prototipe di luar repositori menilai kalibrasi kelompok kata saja pada putaran 1 sampai 3 (penguatan per bukti; nu 2, 3, 4, dan pilihan nu per bukti; `redam`; `puncak`). Aturan pemilihan `kandidat.py` (`ATURAN`) ditulis setelah itu, sebelum putusan, peringatan, atau kalibrasi gabungan kandidat mana pun dihitung, dan dicatat di git sebelum bukti uji dibuat: (1) tidak ada tuduhan salah; (2) tidak ada salinan atau anggota koalisi yang disebut dekoder sebelumnya lalu hilang; (3) tidak ada pelacakan jujur yang mendapat peringatan baru; (4) sel terlalu yakin (kelas medium x kelompok bobot, P(Poisson(E) >= k) < 10^-4) dihitung untuk kelompok kata dan bacaan gabungan; (5) di antara kandidat yang lolos 1 sampai 3 dan punya lebih sedikit sel kata terlalu yakin daripada dekoder sebelumnya, sel kata ditambah sel gabungan paling sedikit.

| Kandidat | Sel kata | Sel gabungan | Putusan benar | Bertambah / hilang |
|---|---|---|---|---|
| `gauss` (dekoder sebelumnya) | 42 | 38 | 1.408 | |
| `t3_redam` | **10** | **22** | 1.409 | 1 / 0 |
| `t3_redam_puncak` | 13 | 24 | 1.409 | 1 / 0 |
| `t3_redam_puncak05` | 11 | 25 | 1.409 | 1 / 0 |
| `t4_redam_puncak` | 15 | 28 | 1.409 | 1 / 0 |
| `t2_redam_puncak` | 13 | 21 | 1.409 | 1 / 1 (gagal aturan 2) |

1.650 bukti pengembangan, setiap kandidat lewat kode produksi (`decode_displacements(..., word_model=...)`); dekoder sebelumnya mengulang setiap keluaran geser yang tersimpan (1.650 bukti, 0 berbeda). Tidak ada kandidat yang menuduh salah atau menambah peringatan pada bukti jujur. Pilihan: **`t3_redam`** (`hasil/pilihan.json`), kini `ch_shift.IMAGE_WORD_MODEL`. Skala per kelompok dari kecocokan templat (`puncak`) menaikkan kemungkinan model per bukti, tetapi tidak memperbaiki kalibrasi di luar `t3_redam`, jadi tidak dipakai.

## Hasil (set uji)

Dijalankan sekali dengan kode komit pilihan (`5f258a5`, hash sumber dekoder di `hasil/uji_dekoder.json`) pada empat terbitan baru (G1 sampai G4, benih 13401 sampai 13419): 520 pelacakan, termasuk 36 induk tanpa tanda. Setiap registrasi juga didekode dengan dekoder sebelumnya, jadi sebelum dan sesudah berpasangan. Jalannya berhenti sekali setelah 5 pelacakan PDF, karena skrip studi memuat `kandidat.py` studi kalibrasi (nama modul yang sama) di proses pekerja; skrip diperbaiki tanpa mengubah dekoder, dan jalannya dilanjutkan. Kelima pelacakan yang tercatat adalah hasil kode yang sama.

**Kelompok kata, bobot di atas 0,99** (salah / posisi; laju, terkalibrasi E / n):

| Medium | Sebelum | Sesudah |
|---|---|---|
| PDF yang diteruskan | 0 / 4.871 | 0 / 4.871 (tidak berubah) |
| Tangkapan simulator | 17 / 6.266 (0,27 %; 0,04 %) | 1 / 958 (0,10 %; 0,42 %) |
| Foto dasar | 145 / 3.925 (3,69 %; 0,07 %) | 3 / 526 (0,57 %; 0,41 %) |
| Foto dengan ISP ponsel | 30 / 5.884 (0,51 %; 0,06 %) | 2 / 745 (0,27 %; 0,39 %) |
| Foto monitor | 13 / 3.376 (0,39 %; 0,08 %) | 1 / 89 (1,1 %; 0,43 %) |
| Foto cetakan | 183 / 5.762 (3,18 %; 0,05 %) | 15 / 3.198 (0,47 %; 0,24 %) |

* **Sel terlalu yakin** (P(Poisson(E) >= k) < 10^-4, 15 kelas medium kali 7 kelompok bobot): kelompok kata 26 menjadi 8, **bacaan gabungan 3 menjadi 0**. Setiap sel kata tangkapan 28 sampai 48 dpi (12 sebelumnya) kini lolos.
* **Bacaan gabungan, bobot di atas 0,99**: foto dasar 76 / 53.454 (terkalibrasi 0,04 %) menjadi 16 / 52.049 (0,03 % terhadap 0,04 %), foto cetakan 80 / 118.008 menjadi 22 / 117.241 (0,02 % terhadap 0,03 %), tangkapan simulator 6 menjadi 0.
* **Putusan.** 1 bertambah (foto dasar 39 menjadi 40 dari 40), 0 hilang; skor median praktis sama (rasio 0,9997 sampai 1,002). Tidak ada peringatan dari ketiga pemeriksaan pada pelacakan jujur, sebelum maupun sesudah.
* **Tuduhan salah:** 0 dari 520, termasuk 36 induk tanpa tanda lewat setiap medium; skor tak bersalah tertinggi 0,61 kali ambang (sebelumnya juga 0,61).
* **Benchmark README** (128 pelacakan `make bench-check` dari awal dengan kode gabungan, `docs/results/bench_photos.json` dibuat ulang): foto cetakan satu halaman 9 menjadi 10 dari 16 (halaman 2 salinan 13 pada 30 derajat kini disebut), putusan lain sama (foto layar 40 dari 40, cetakan dua halaman 8 dari 8, ISP ponsel 32 dari 32, monitor 32 dari 32), 0 tuduhan salah. Batas peluang tuduhan salah bergeser sedikit; yang terburuk per set: cetakan satu halaman 5,3 x 10^-7 menjadi 2,9 x 10^-7, dua halaman 2,2 x 10^-11 menjadi 8,9 x 10^-12, foto layar 10^-6,0 menjadi 10^-6,7 (foto jenuh), monitor 10^-7,1 menjadi 10^-6,5.
* **Batas deteksi terhadap laju lolos tahap 1.** Di setiap kelas, laju lolos terukur tidak melampaui rata-rata batas per bacaan (misalnya salinan foto cetakan 10 dari 80, batas rata-rata 0,125; koalisi 3 salinan lewat foto 1 dari 6, batas 0,28).

## Yang tersisa

* **Foto dan foto cetakan pada bobot menengah.** Kelompok kata pada foto dasar dan foto cetakan masih terlalu yakin di kelompok bobot 0,5 sampai 0,99 (8 sel; pada 0,95 sampai 0,99 salah 114 dari 3.613 dan 147 dari 3.518, harapan 46 dan 44). Penyebabnya derau per bukti: pada foto miring derau kelompok kata 1,5 sampai 5 kali yang ditaksir, dan dengan tanda tersembunyi penaksiran derau ikut menyesuaikan diri. Bacaan gabungan kedua medium tidak lagi terlalu yakin secara bermakna, jadi batas deteksi dengan laju (1 - w)/2 kini berlaku kira-kira untuk bacaan gabungannya, tetapi tidak untuk kanal geser sendirian.
* **Baris geser** yang tidak lolos gerbang kisi `research/layar` tidak diubah dan tetap terlalu yakin (5 sel, sama sebelum dan sesudah).
* **Bit kelompok kata berkurang.** Model t membagi bobot lebih rata: bit kata berbobot di atas 0,99 pada foto dasar turun dari 3.925 menjadi 526, karena yang dulu tampak hampir pasti kini tercatat 0,9 sampai 0,99. Putusan dan skor median tidak berubah, karena pola latar menentukan putusan foto dan tangkapan.
* **Medium simulasi, bukan bukti.** Seperti studi kalibrasi: foto, cetakan, dan tangkapan sintetis.

## Menjalankan

Dari akar repositori, dengan folder kerja studi kalibrasi (`$TAPAK_KALIBRASI_KERJA`, berisi terbitan, bukti, dan pengamatannya) dan folder kerja studi ini (`$TAPAK_GESER_KERJA`, bawaan `out/riset_geser`; besar, tidak di-commit; paling banyak 3 proses):

```bash
export PYTHONPATH=. TAPAK_KALIBRASI_KERJA=out/riset_kalibrasi TAPAK_GESER_KERJA=out/riset_geser
G=".venv/bin/python research/geser"
$G/kandidat.py nilai          # setiap kandidat pada setiap bukti pengembangan
$G/kandidat.py pilih          # aturan: hasil/pilihan.json
$G/ukur.py terbit && $G/ukur.py lacak     # set uji, sekali, dengan model pilihan
$G/ringkas.py --json          # hasil/ringkas_uji.json
```

`bench.py` melacak keempat set foto benchmark README dengan kedua model kata dan mencatat hitungan kalibrasinya (perintah di docstring-nya); angka benchmark di atas berasal dari `make bench-check`, karena jalannya terlalu lama di mesin yang dipakai bersama dan dihentikan.

`ukur.py lacak` menolak berjalan bila model kata bawaan dekoder (`ch_shift.IMAGE_WORD_MODEL`) bukan pilihan di `hasil/pilihan.json`, mencatat hash sumber dekoder di `hasil/uji_dekoder.json` sebelum pelacakan pertama, dan melewati bukti yang sudah tercatat bila diulang setelah terputus.
