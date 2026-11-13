# Kalibrasi bobot pola latar per medium

Batas deteksi `tapak/tardos/detection.py` terbukti dengan dua syarat ([batasan 12](../../docs/keamanan.md#batasan-12)). Syarat kedua meminta laju salah yang benar untuk setiap bobot, dan dengan LLR dekoder sendiri laju itu (1 - w)/2 hanya bila LLR-nya terkalibrasi. `research/layar` menemukan bobot pola latar terlalu yakin di kelompok tertinggi setelah JPEG: pada tangkapan layar lewat aplikasi pesan, bobot di atas 0,95 salah 1,8 % pada 28 sampai 48 dpi (dijanjikan 0,7 %), 0,9 % pada 56 sampai 84 dpi (0,2 %), dan 0,5 % dari 96 dpi (0,1 %). Studi ini mengukur kalibrasi bobot pola latar (dan bobot geser, sebagai pembanding) per medium, memilih perbaikan tanpa kode penerima pada benih pengembangan saja, lalu menjalankan benih uji sekali dengan dekoder pilihan.

Tidak ada ambang tuduhan, eps, aturan pembagian eps, atau aturan putusan yang berubah, dan tidak ada dekoder yang melihat kode penerima. Kode penerima hanya dipakai di sini untuk menghitung bit yang salah. Batas tuduhan salah tidak bergantung pada kalibrasi. Semua dokumen dan penerima fiktif; semua tangkapan, foto, dan cetakan sintetis.

## Protokol

Protokol, benih, media, dan catatan per bukti ditulis di docstring `ukur.py` (`PROTOCOL`, juga `hasil/protokol.json`) dan dicatat di git sebelum pengukuran pertama (komit `ea213b1`). Aturan pemilihan (`kandidat.py`, `ATURAN`) dicatat sebelum kandidat pertama dinilai (`47520d9`) dan tidak berubah antarputaran.

* **Penerbitan.** `tapak issue --benih-riset`, N = 20, c = 3, eps = 10^-6, skema geser v2. Pengembangan: nota dinas (13101) dan surat telegram (13102) dengan profil latar bawaan, keduanya lagi (13103, 13104) dengan profil latar cetak. Uji: 13201 sampai 13204 dengan pembagian yang sama. Benih ini tidak dipakai studi lain.
* **Medium** (halaman 1 kecuali cetakan): PDF yang diteruskan; tangkapan layar dari MuPDF, Poppler Splash, dan Poppler Cairo pada 28 sampai 150 dpi dengan fungsi `research/layar` tanpa perubahan, sebagai PNG, lewat aplikasi pesan (`pesan`), atau digambar 1,5 kali lebih rapat lalu diperkecil aplikasi pesan (`kecil`), halaman saja atau di jendela penampil; tangkapan simulator `tapak/photos.py` (`layar_sim`, tangkapan benchmark README); foto ponsel dasar (`foto`), foto lewat ISP ponsel simulasi (`ponsel`), foto monitor dengan ISP (`monitor`); dan foto cetakan laser profil latar cetak (`cetak`), halaman 1 atau 2.
* **Grid.** Salinan jujur lewat setiap medium penerbitannya; koalisi jujur 2 dan 3 salinan (strategi acak, asumsi penandaan dipatuhi) lewat PDF, tangkapan pesan, dan foto; induk tanpa tanda lewat setiap medium (tidak boleh ada yang disebut). Pengembangan 626 pelacakan, uji 1.024.
* **Pelacakan** lewat jalur produksi sebagai pelacakan tercatat pertama dengan kebijakan tahap bawaan, yang menjalankan ketiga pemeriksaan manipulasi. Registrasi dan pengamatan setiap bukti disimpan, jadi kandidat mendekode ulang kanal latar dari registrasi yang sama, dan set uji dibandingkan dengan dekoder sebelum studi ini pada bukti yang sama (`kandidat.py banding`).
* **Dicatat per bukti:** putusan, ambang tahap 1, skor anggota dan bukan anggota sebagai kelipatan ambang, batas tuduhan salah, ketiga pemeriksaan, uji pola latar, batas deteksi `read_miss_ceiling` dari bobot bacaan (plafon terkalibrasi dan plafon pemeriksaan bacaan jelas tanpa nama, 1 / (1 + exp(0,3 |L|))), dan untuk salinan tunggal hitungan keandalan per kelompok bobot: posisi n, salah k, dan harapan terkalibrasi E = jumlah 1 / (1 + exp |L|), untuk pola latar, baris geser, kelompok kata, dan bacaan gabungan.

## Penyebab (set pengembangan)

Dengan dekoder sebelumnya, residu baku satu sel, (u_c - g s_b) akar(n_c / v), bervarians 2 sampai 3 dalam satu sel dari tinta induk dan 0,3 sampai 0,6 mulai dua sel dari tinta. Setelah JPEG pola itu sendiri juga melemah di dekat teks: rata-rata u_c s_b / g hanya 0,24 sampai 0,5 dalam setengah sel dari tinta pada 40 dan 56 dpi (`kandidat.py diagnosa`). Dekoder sebelumnya memakai satu penguatan dan satu varians derau per strata kejenuhan, sehingga sel di sebelah teks ditimbang terlalu berat, dan salahnya jatuh di kelompok bobot tertinggi. Strata yang tipis menambah masalahnya: taksiran variansnya berderau, dan satu sel dengan varians yang terlalu kecil dapat membuat satu bit sangat yakin sendirian.

## Pemilihan (set pengembangan)

Aturan `ATURAN`: (1) tidak ada tuduhan salah; (2) tidak ada salinan atau anggota koalisi yang disebut dekoder sebelumnya lalu hilang; (3) tidak ada pelacakan jujur yang mendapat peringatan baru; (4) di setiap kelas medium (PDF; PNG, pesan, dan kecil per pita 28 sampai 48, 56 sampai 84, dan 96 sampai 150 dpi; layar_sim; foto; ponsel; monitor; cetak) dan setiap kelompok bobot, P(Poisson(E) >= k) paling sedikit 10^-4; (5) di antara yang lolos, galat kalibrasi terkecil (rata-rata atas kelas medium dari jumlah |k - E| dibagi jumlah bit kelas itu). Bila tidak ada yang lolos, dekoder tidak berubah.

| Putaran | Kandidat | Hasil |
|---|---|---|
| 1 | penguatan dan atau varians per strata dan kelas jarak ke tinta, dari regresi pilot atau dari pasangan sel satu bit, dengan dan tanpa peredam 1,5 | tidak ada yang lolos aturan 4 (6 sampai 24 kelompok terlalu yakin; dekoder sebelumnya 34) |
| 2 | varians A_j B_k (strata j, kelas jarak k) dari pasangan sel satu bit, kuadrat terkecil biasa, dengan dan tanpa penguatan per kelas dan batas per sel | tangkapan layar terkalibrasi, tetapi derau strata foto yang sangat terang jatuh ke batas bawahnya: 1 sampai 4 putusan hilang, sampai 4 peringatan baru |
| 3 | model putaran 2 dengan kuadrat terkecil berbobot ulang, dimulai dari varians per strata, dengan dan tanpa batas per sel; dekoder sebelumnya dengan batas per sel | hanya `pasangan_irls_batas` lolos keempat aturan: galat kalibrasi 0,0014 (sebelumnya 0,0041), 548 putusan benar seperti sebelumnya |

Tanpa batas per sel, kandidat yang sama masih terlalu yakin di 5 kelompok bobot tertinggi tangkapan pesan dan kecil. Rinciannya di `hasil/pilihan.json` (dan `pilihan_putaran1.json`, `pilihan_putaran2.json`), keluaran setiap putaran di `hasil/dev_kandidat_putaranN.jsonl.gz`.

**Model yang dipasang** (`tapak/decoder/ch_background.py`, `ink_pair_noise`, langkah 6 di docstring modul). Setiap sel masuk ke kelas jarak ke tinta induk (batas bawah 0, 0,5, 1, 1,5, 2, dan 3 sel), yang dihitung dari induk saja. Penguatan tetap per strata kejenuhan (regresi pada pilot, seperti sebelumnya). Varians derau sel adalah A_j B_k. Dua sel satu bit membawa tanda yang sama, jadi E[(u_c - u_c')^2 - (g_c - g_c')^2] = V_c / n_c + V_c' / n_c', apa pun bitnya: setiap pasangan sel satu bit mengukur derau tanpa kode penerima dan tanpa vektor bias. A dan B ditaksir dari semua pasangan dengan kuadrat terkecil bergantian yang berbobot ulang (10 putaran), mulai dari varians per strata dekoder sebelumnya. Satu sel paling banyak menyumbang ln 99 ke LLR bitnya. Keputusan ada tidaknya pola, jumlah pilot, kekuatan, dan dekoder halaman PDF tidak berubah. Model sebelumnya tetap tersedia sebagai `"kejenuhan"`. Model terpasang sama persis dengan kandidat riset pada 571 keluaran latar gambar set pengembangan (`kandidat.py periksa --split dev --terpasang`).

## Hasil (set uji)

Dijalankan sekali dari ekspor `git archive` komit pilihan (`754470f`; hash sumber dekoder di `hasil/uji_dekoder.json`). Jalannya terputus sekali pada pelacakan 889 dari 1.024 karena sesi mesin uji berhenti, lalu dilanjutkan dengan kode yang sama (hash sumber dekoder diperiksa ulang sebelum dilanjutkan); pelacakan yang sudah tercatat dilewati, dan setiap bukti memakai benihnya sendiri, jadi hasilnya sama dengan satu jalan tanpa henti. Sebelum dan sesudah dihitung pada registrasi yang sama: pendekodean ulang dengan model terpasang mengulang setiap keluaran latar yang tersimpan (952 bukti gambar), lalu dekoder sebelumnya mendekode registrasi yang sama dan menuduh dengan cara yang sama.

**Pola latar, bobot di atas 0,95** (salah / posisi; laju terukur, terkalibrasi E / n):

| Medium | Sebelum | Sesudah |
|---|---|---|
| PDF yang diteruskan | 0 / 194.200 | 0 / 194.200 (tidak berubah) |
| PNG 28 sampai 48 dpi | 87 / 135.334 (0,064 %; 0,024 %) | 13 / 136.376 (0,010 %; 0,017 %) |
| PNG 56 sampai 150 dpi | 1 / 244.689 | 0 / 244.690 |
| Pesan 28 sampai 48 dpi | 556 / 35.783 (1,55 %; 0,74 %) | 343 / 69.293 (0,50 %; 0,43 %) |
| Pesan 56 sampai 84 dpi | 718 / 116.748 (0,62 %; 0,21 %) | 82 / 132.228 (0,062 %; 0,076 %) |
| Pesan 96 sampai 150 dpi | 211 / 102.392 (0,21 %; 0,03 %) | 9 / 104.079 (0,009 %; 0,013 %) |
| Kecil 28 sampai 48 dpi | 595 / 38.720 (1,54 %; 0,75 %) | 306 / 69.727 (0,44 %; 0,45 %) |
| Kecil 56 sampai 84 dpi | 649 / 118.176 (0,55 %; 0,20 %) | 94 / 131.930 (0,071 %; 0,076 %) |
| Kecil 96 sampai 150 dpi | 212 / 102.254 (0,21 %; 0,03 %) | 17 / 103.903 (0,016 %; 0,016 %) |
| Tangkapan simulator | 167 / 76.236 (0,22 %; 0,025 %) | 12 / 77.278 (0,016 %; 0,011 %) |
| Foto dasar | 144 / 57.217 (0,25 %; 0,20 %) | 120 / 57.718 (0,21 %; 0,20 %) |
| Foto dengan ISP ponsel | 198 / 44.053 (0,45 %; 0,37 %) | 169 / 53.116 (0,32 %; 0,27 %) |
| Foto monitor | 124 / 43.166 (0,29 %; 0,25 %) | 103 / 48.080 (0,21 %; 0,22 %) |
| Foto cetakan | 60 / 111.994 (0,054 %; 0,11 %) | 95 / 111.631 (0,085 %; 0,11 %) |

* **Kelompok bobot terlalu yakin secara bermakna** (P(Poisson(E) >= k) < 10^-4, 15 kelas medium kali 7 kelompok bobot): pola latar 38 sebelum, 0 sesudah. Yang paling dekat sesudahnya: pesan 28 sampai 48 dpi di atas 0,95 (p 0,006) dan ISP ponsel (p 0,02).
* **Lebih banyak bit yang yakin.** Di tangkapan pesan dan kecil 28 sampai 48 dpi, bit berbobot di atas 0,95 hampir dua kali lipat (35.783 menjadi 69.293), dengan laju salah sesuai bobotnya: bobot sel jauh dari teks tidak lagi diturunkan oleh derau sel di dekat teks.
* **Putusan.** Salinan dan koalisi jujur: 1 putusan bertambah, 0 hilang. Skor median salinan naik 16 sampai 17 % pada tangkapan pesan dan kecil 28 sampai 48 dpi, 3 sampai 4 % pada 56 sampai 84 dpi, 3 % pada foto ISP ponsel, dan tetap pada PDF dan PNG. Skor minimum tangkapan pesan 28 sampai 48 dpi 1,8 menjadi 2,3 kali ambang.
* **Peringatan.** Tidak ada peringatan dari ketiga pemeriksaan (pola penghapusan, bacaan jelas tanpa nama, pola tanda terbalik) pada 1.024 pelacakan jujur, sebelum maupun sesudah.
* **Tuduhan salah.** 0 dari 1.024 pelacakan, termasuk 60 induk tanpa tanda lewat setiap medium; skor tak bersalah tertinggi 0,62 kali ambang (sebelumnya 0,58).
* **Batas deteksi terhadap laju lolos tahap 1.** Laju lolos terukur tidak melampaui rata-rata batas per bacaan di kelas mana pun. Batasnya mengecil pada tangkapan pesan, misalnya koalisi 3 salinan lewat pesan 28 sampai 48 dpi rata-rata 0,31 menjadi 0,012 dan 56 sampai 84 dpi 5 x 10^-4 menjadi 4 x 10^-5 (8 koalisi per sel, tidak ada yang lolos). Salinan tunggal yang lolos (cetakan 15 dari 80, foto monitor 4 dari 40, pesan 28 sampai 48 dpi 3 dari 72) semuanya bacaan yang batasnya 1: 22 dari 24 halaman yang tidak ditemukan (15 di antaranya halaman 2 surat telegram yang dicetak), dan 2 foto monitor tanpa pola yang terbaca.
* **Benchmark README** (`bench.py`, 128 pelacakan keempat set foto `make bench-check`, gambar yang tidak dipakai untuk pemilihan, `hasil/bench.json`). Putusan sama dengan kedua model (layar 40 dari 40, cetak 9 dari 16 dengan satu halaman dan 8 dari 8 dengan dua halaman, ISP ponsel 32 dari 32, monitor 32 dari 32, 0 tuduhan salah), dan tidak ada peringatan dari ketiga pemeriksaan. Batas peluang tuduhan salah bergeser pada 102 dari 128 pelacakan (median -0,86 dalam log10, paling besar naik 1,0); yang terburuk di setiap set sama, kecuali foto ISP ponsel, 10^-40,9 menjadi 10^-57,9 (`docs/results/bench_photos.json` dibuat ulang dengan langkah benchmark yang terdokumentasi). Pola latar di atas 0,95 pada 8 tangkapan simulator: 21 salah (harapan terkalibrasi 3,1) menjadi 0 (1,4); pada ISP ponsel 0,54 % (0,48 %) menjadi 0,37 % (0,37 %). Pada 32 foto layar dasar benchmark: 119 salah (harapan 71) menjadi 104 (74), jadi foto itu masih sekitar 1,4 kali terlalu yakin, walaupun foto dasar set uji terkalibrasi (120 terhadap 117).
* **Waktu.** Median detik dekode per bukti praktis sama (tangkapan 7,0 detik, dekoder sebelumnya pada set pengembangan 6,7 sampai 6,8 detik, 3 proses di mesin yang dipakai bersama).

## Yang tersisa

* **Kanal geser tidak diubah dan tetap terlalu yakin di beberapa medium**, jadi bacaan gabungan juga. Pada foto, foto ISP ponsel, foto monitor, foto cetakan, dan tangkapan simulator, kelompok bobot tertinggi bacaan gabungan masih terlalu yakin secara bermakna, karena bit kelompok kata: bobot di atas 0,999 salah 80 dari 2.781 pada foto dasar dan 92 dari 3.558 pada foto cetakan, padahal bobotnya hanya menjanjikan sekitar 0,2 salah di masing-masing. Pada PNG 28 sampai 48 dpi kelompok kata terlalu yakin di bobot menengah. Batas deteksi dengan laju (1 - w)/2 karena itu tetap tidak berlaku untuk foto dan cetakan. Pada tangkapan pesan dan kecil di semua resolusi, dan PNG dari 56 dpi, tidak ada kelompok bobot gabungan yang terlalu yakin secara bermakna di set uji.
* **Baris geser** yang tidak lolos gerbang kisi `research/layar` tetap terlalu yakin (15 kelompok sebelum dan sesudah; dekoder geser tidak berubah).
* **Foto layar dasar benchmark README** masih sekitar 1,4 kali terlalu yakin di kelompok pola latar tertinggi (104 salah, harapan 74; P(Poisson(74) >= 104) sekitar 5 x 10^-4), walaupun foto dasar set uji terkalibrasi. Kedua set memakai simulator foto yang sama dengan adegan acak yang berbeda (benih foto 2026 dan benih set uji), jadi kalibrasi foto dapat bergantung pada adegan.
* **Kalibrasi adalah pengukuran pada medium simulasi, bukan bukti.** JPEG ponsel, aplikasi pesan, dan penampil sungguhan dapat berperilaku lain. Model derau masih mengandaikan derau sel saling bebas di dalam satu bit dan satu kelas; derau yang berkaitan antarsel (blok JPEG yang sama) tidak dimodelkan, dan batas ln 99 per sel menahan sisanya.
* **Syarat pertama batas** tetap hanya kira-kira: penguatan per strata memakai vektor bias sebagai pilot, jadi bobot bergantung pada kode lewat beberapa angka bersama untuk satu halaman. Varians derau baru sendiri berasal dari selisih sel satu bit, tempat bitnya saling meniadakan, dan dari penguatan itu.

## Menjalankan

Dari akar repositori, dengan MuPDF dan Poppler terpasang seperti untuk `research/layar` (folder kerja `$TAPAK_KALIBRASI_KERJA`, bawaan `out/riset_kalibrasi`; besar, tidak di-commit; paling banyak 3 proses):

```bash
export PYTHONPATH=. TAPAK_KALIBRASI_KERJA=out/riset_kalibrasi
K=".venv/bin/python research/kalibrasi"
$K/ukur.py terbit --split dev
$K/ukur.py lacak --split dev                          # 626 pelacakan, dekoder sebelum studi ini
$K/kandidat.py periksa --split dev                    # kandidat kejenuhan mengulang setiap keluaran tersimpan
$K/kandidat.py nilai --split dev --putaran 1 && $K/kandidat.py pilih --sampai 1
$K/kandidat.py nilai --split dev --putaran 2 && $K/kandidat.py pilih --sampai 2
$K/kandidat.py nilai --split dev --putaran 3 && $K/kandidat.py pilih
$K/kandidat.py periksa --split dev --terpasang        # model terpasang sama dengan pilihan
$K/ukur.py terbit --split uji && $K/ukur.py lacak --split uji   # sekali, 1.024 pelacakan
$K/kandidat.py banding --split uji                    # dekoder sebelumnya pada registrasi yang sama
$K/ringkas.py --split uji --json                      # hasil/ringkas_uji.json
$K/kandidat.py diagnosa --split dev                   # varians residu dan penguatan per jarak ke tinta
```

`lacak --split uji` menolak berjalan bila model derau bawaan dekoder bukan pilihan di `hasil/pilihan.json`, mencatat hash sumber dekoder di `hasil/uji_dekoder.json` sebelum pelacakan pertama, dan melewati bukti yang sudah tercatat bila diulang setelah terputus. Set pengembangan memerlukan sekitar 35 menit, satu putaran kandidat 15 sampai 25 menit, dan set uji sekitar 1 jam dengan 3 proses di mesin yang dipakai bersama. `bench.py` membaca keempat set foto benchmark README dengan kedua model derau (perintah di docstring-nya).
