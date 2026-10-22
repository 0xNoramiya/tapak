# Cara kerja TAPAK

[Kembali ke README](../README.md) · [Operasi](operasi.md) · [Keamanan dan batasan](keamanan.md)

## Lima kanal, ditambah satu kanal pilihan

Kode penerima yang sama ditanam di empat kanal, ditambah token kanari sebagai kanal kelima. Kanal keenam, pilihan kata, hanya dipakai bila penerbit memilihnya dan meninjau setiap titiknya ([rinciannya di bawah](#kanal-pilihan-kata-opsional)). Kanal mana pun boleh rusak; dekoder menggabungkan apa yang tersisa.

| Kanal | Yang ditanam | Kebocoran yang ditangani |
|---|---|---|
| 1. Geser kata dan baris | kelompok kata bergeser horizontal dan baris bergeser vertikal sebesar 0,05 mm. Bit dikodekan relatif terhadap tetangga (kontrol, data, kontrol), sehingga sisa distorsi perspektif saling meniadakan | cetak, foto, tangkapan layar |
| 2. Pola latar | pola acak berfrekuensi rendah +/-2 tingkat abu-abu (sel 2 mm). Setiap posisi kode menempati 8 sel yang tersebar dan didekode secara buta per bit. Profil cetak (opsional): 242 +/- 5 | tangkapan layar, foto layar; dengan profil cetak juga kertas cetak (printer simulasi, [di bawah](#salinan-yang-dicetak)) |
| 3. Karakter tak terlihat | sepasang simbol lebar-nol sebelum dan sesudah kata (2 bit per simbol) serta huruf kembar Kiril pada kata huruf kecil | salin-tempel, berkas diteruskan |
| 4. Varian semantik | parafrasa kalimat pembuka, penutup, dan tembusan oleh LLM lokal, disetujui manusia | pengetikan ulang, tetapi hanya beberapa bit (4 pada contoh), belum cukup untuk menyebut nama |
| 5. Kanari DNS | satu subdomain unik per salinan di bawah domain kanari. Pendengar DNS mencatat kapan nama itu dicari dan resolver mana yang bertanya, bukan siapa pembukanya. Token ini tidak membawa kode Tardos | berkas dibuka di luar jaringan satuan, di Adobe Reader atau Word |
| 6. Pilihan kata (opsional) | bentuk bermakna sama dari tabel leksikon draf, misalnya "terdiri atas" atau "terdiri dari", "dan" atau "serta". Setiap titik disetujui manusia | pengetikan ulang oleh satu pembocor, bila dokumennya cukup panjang (terukur: mulai sekitar 1.300 kata isi; TAPAK menyatakan cukup mulai 64 bit, sekitar 1.800 kata isi); tidak tahan kolusi. Bentuknya terlihat di kertas, jadi dapat ditiru |

## Dokumen induk hasil pindai

Halaman hasil pindai tidak memiliki lapisan teks untuk digambar ulang, jadi tandanya dibuat langsung di piksel gambar halaman (`tapak/marker/raster.py`). Rencana penandaan, posisi kode, kunci, dan kode Tardos sama dengan halaman teks.

* **Deteksi per halaman.** Halaman dianggap hasil pindai bila isi yang terlihat hanya satu gambar yang menutupi hampir seluruh halaman. Teks di atasnya boleh tidak ada atau tak terlihat (lapisan OCR, mode render 3). Halaman lain tetap memakai jalur teks, jadi dokumen campuran ditangani per halaman.
* **Kotak kata.** Tesseract (bahasa `ind`, mesin LSTM, satu utas, resolusi dinyatakan) membaca gambar halaman induk satu kali. Kotak kata dan barisnya menjadi baris, kata, dan kelompok geser seperti pada halaman teks. Catatan penerbitan dan registri hanya menyimpan hash daftar kotak itu dan versi Tesseract, tanpa kotak, kata, atau gambar.
* **Geser.** Tinta kelompok data bergeser 0,05 mm (0,59 piksel pada 300 dpi) dengan interpolasi kubik subpiksel, lalu dicampur lewat masker lunak yang hanya mencakup tinta dan 2 piksel di sekitarnya. Tekstur kertas di sekitar kata tidak ikut diinterpolasi, sehingga tidak ada tepi petak atau lingkaran cahaya. Piksel yang ditinggalkan tinta mengambil kertas di sebelahnya dari gambar induk. Baris data bergeser vertikal dengan cara yang sama.
* **Pola latar.** Pola berkunci +/-2 tingkat abu-abu ditambahkan hanya ke piksel kertas, yaitu piksel yang paling banyak 20 tingkat lebih gelap dari warna kertas halaman itu, pada resolusi gambar halaman. Dekoder memakai batas yang sama untuk menyisihkan tinta.
* **Kanal lain.** Kanari tetap dipasang karena berupa aksi PDF. Karakter tak terlihat, huruf kembar, varian semantik, dan pilihan kata tidak berlaku di halaman pindaian, dan rencana penandaan menyatakannya.
* **Salinan.** Gambar halaman bertanda menggantikan gambar induk sebagai Flate tanpa kehilangan data, dengan ukuran dan letak yang sama. Lapisan OCR tak terlihat dari induk tidak ikut ke salinan, karena berisi kata dokumen induk tanpa tanda.
* **Gerbang.** Salinan tanpa tanda harus identik piksel demi piksel dengan gambar halaman induk, dan halamannya juga dirender sama dengan halaman induk (pada lebih dari separuh resolusi pindai). Setiap salinan bertanda hanya boleh berubah di sekitar tinta yang digeser dan, di kertas, sebesar pola latar (-4 sampai +2 tingkat). Bila tidak, penerbitan berhenti.
* **Pelacakan.** Templat dekoder adalah gambar halaman induk itu sendiri. Kotak kata dibaca ulang dengan panggilan Tesseract yang sama dan hanya dipakai bila hash-nya sama dengan catatan penerbitan. Bila berbeda, misalnya karena versi Tesseract lain, kanal geser halaman pindaian ditolak dengan catatan, dan pola latar tetap dibaca. Slot geser halaman pindaian ditempatkan setelah semua halaman teks, sehingga perubahan kotak kata tidak pernah menggeser posisi kode halaman teks. Ambang dan aturan tuduhan tidak berubah.

Angka terukurnya ada di [batasan 8](keamanan.md#batasan).

## Kode Tardos

Setiap dokumen memiliki vektor bias p (distribusi arcsine dengan batas t = 1/(300c)) dan setiap salinan memiliki kata kode biner x_j. Panjang kode m = K c^2 ln(1/eps1) dengan eps1 = eps/N (batas gabungan untuk N penerima) dan K = 2 pi^2 (bawaan) atau 100 (konservatif). Skor tuduhan memakai skor simetris Skoric dkk.: S_j = jumlah w_i U(y_i, x_ji, p_i).

## Ambang ditetapkan sebelum skor dihitung

Aturan ambang ditetapkan saat penerbitan dan dicatat di registri, bersama ambang Z untuk pembacaan penuh. Untuk setiap bukti, TAPAK menghitung ambang Z setelah dekode, dengan batas Chernoff yang dihitung dari vektor bias dokumen yang sebenarnya dan bobot dekoder. Posisi yang tidak terbaca tidak dihitung, dan setiap posisi memakai bit bocor terburuk. Perhitungan ini tidak melihat kode penerima mana pun. Nilainya dicatat dengan cap waktu di hasil dan berita acara, baru kemudian skor dihitung.

Jaminan tuduhan salah karenanya tidak bergantung pada konstanta K maupun pendekatan Gauss. K hanya memengaruhi deteksi. Untuk pembacaan penuh dengan bit pasti, peluang koalisi lolos juga dibatasi secara matematis ([batas deteksi terbukti](#batas-deteksi-terbukti)); untuk bobot lunak dekoder dan kanal berderau, deteksi hanya diukur dengan simulasi.

Satu kebocoran dapat dilacak berulang kali, misalnya dengan potongan atau gabungan bukti yang berbeda. Karena itu setiap pelacakan dokumen yang tercatat lebih dulu ditulis di registri dengan nomor urut k per dokumen, sebelum bukti dibaca. Pelacakan ke-k memakai eps_k = eps x 6 / (pi^2 k^2) dan eps1 = eps_k / N, untuk ambang gabungan maupun ambang tiap kanal. Jumlah 1/k^2 untuk semua k adalah pi^2/6, jadi jumlah semua eps_k tepat eps: batas tuduhan salah berlaku untuk semua pelacakan dokumen bersama, selama bukti tiap pelacakan tidak dipilih berdasarkan skor pelacakan sebelumnya ([batasan 13](keamanan.md#batasan)). Peluang tuduhan salah per salinan juga dibagi dengan 6 / (pi^2 k^2). Pelacakan yang tidak tercatat (mode lepas, atau dokumen yang diterbitkan tanpa registri) memakai seluruh eps dan hasilnya menyatakannya.

## Fusi bukti

Setiap kanal menghasilkan rasio log-kemungkinan (LLR) per posisi kode tanpa pernah melihat kode penerima. LLR dijumlahkan; keputusan y_i = tanda LLR, bobot w_i = tanh(|LLR|/2). Skor tuduhan dihitung pada hasil fusi dan pada setiap kanal fisik secara terpisah, sehingga laporan menyebut berapa kanal yang sepakat secara independen. Kanal yang saling bertentangan dilaporkan sebagai kemungkinan manipulasi.

## Aturan keluaran

Nama hanya muncul bersama skor, ambang, dan peluang tuduhan salahnya. Bila tidak ada salinan yang melewati ambang, keluarannya "tidak cukup bukti" dan tidak ada nama yang disebut.

## Arsitektur

```
            +---------------- Terbitkan -----------------+          +------------------ Lacak -------------------+
 PDF induk  |  layout   rencana penandaan (kunci)        |  salinan | foto / tangkapan layar / PDF / DOCX / teks |
 + penerima |  model -> geser, latar, teks, semantik,    |--------->|  rectify (kontur, SIFT, Tesseract) + ECC   |
            |           pilihan kata, kanari -> render   |          |  ch_shift  ch_background  ch_zerowidth     |
            |           ulang + gerbang -> 20 salinan    |          |  ch_semantic  ch_lexical  ch_docx          |
            +----------------------+---------------------+          |        -> fuse (LLR) -> accuse (Chernoff)  |
                                   |                                |        -> berita acara (WeasyPrint)        |
                                   v                                +---------------------+----------------------+
           registri SQLite tambah-saja: rantai SHA-256, tanda tangan Ed25519,             |
           akar Merkle harian; hanya hash, id, dan komitmen kode   <----------------------+  verifikasi silang
                                   ^
                                   |  peristiwa kanari (rantai hash sendiri)
                       pendengar DNS otoritatif (dnslib)
```

```
tapak/
  tardos/       params, code (SHAKE-256), accuse (skor simetris, ambang Chernoff), attacks, simulate
  marker/       layout, master (font), plan, pdf_shift, background, pdf_zerowidth, semantic, lexical,
                canary, docx_marker, render (gambar ulang + gerbang visual), raster (halaman pindaian),
                issue (paralel)
  decoder/      rectify, lines (Tesseract), ch_shift, ch_background, ch_zerowidth, ch_semantic, ch_lexical,
                ch_docx, image, fuse, accuse, trace, report (berita acara)
  assets/       font DejaVu, leksikon pilihan kata (leksikon/naskah_dinas_v1.json, draf)
  registry/     chain (rantai hash, trigger tambah-saja), signing (Ed25519), verify, merkle
  canary_dns/   server (dnslib), store (log berantai)
  llm/          provider (antarmuka), mock (deterministik), llamacpp (lokal, loopback saja)
  learned_wm/   kerangka tanda air berbasis model (opsional, belum dilatih)
  web/          FastAPI + HTMX, antarmuka berbahasa Indonesia
  photos.py     simulator foto, tangkapan layar, dan printer
  ponsel.py     ISP ponsel dan monitor simulasi untuk photos.py (opsional)
  ketik.py      simulator pengetikan ulang dan OCR (untuk pengujian dan pengukuran)
  service.py    alur bersama CLI, web, dan demo
  cli.py        tapak issue | trace | simulate | verify | demo | ...
samples/        templat nota dinas dan surat telegram fiktif, PDF contoh, daftar penerima
scripts/        alat ukur dan eksperimen (scripts/cetak: pengukuran salinan cetak)
tests/          pytest (tanpa GPU, tanpa model LLM, tanpa jaringan)
research/ketik/ pengukuran kanal pilihan kata (kapasitas, galat baca, atribusi)
research/pindaian/ pengukuran induk hasil pindai (protokol, hasil, potongan gambar)
research/ponsel/ pengukuran foto ponsel dan foto layar simulasi (protokol, pemilihan dekoder, hasil)
docs/           dokumentasi, gambar README (docs/figures membuatnya ulang), keluaran simulasi dan benchmark
```

## Angka simulasi

Perintah: `tapak simulate --n 100 --c 3 --eps 1e-6 --trials 1000` (m = 3273 bit). Simulasi ini bekerja di tingkat kode: koalisi langsung menyerang bit kode, tanpa dokumen, gambar, atau derau kanal.

| Strategi kolusi | Tuduhan salah | Deteksi (minimal 1 anggota) | Semua anggota tertangkap | Z rata-rata | Skor koalisi tertinggi |
|---|---|---|---|---|---|
| mayoritas | 0 / 1.000 | 100 % | 100 % | 372,5 | 772,6 |
| minoritas | 0 / 1.000 | 100 % | 100 % | 372,5 | 768,1 |
| campuran acak | 0 / 1.000 | 100 % | 100 % | 372,5 | 773,3 |
| lempar koin | 0 / 1.000 | 100 % | 100 % | 372,5 | 769,7 |
| selalu 1 | 0 / 1.000 | 100 % | 100 % | 372,5 | 770,9 |
| selalu 0 | 0 / 1.000 | 100 % | 100 % | 372,5 | 770,6 |
| hapus (rata-rata dua salinan) | 0 / 1.000 | 100 % | 100 % | 306,5 | 722,8 |
| terburuk (rata-rata skor koalisi terendah; untuk c = 3 sama dengan minoritas) | 0 / 1.000 | 100 % | 100 % | 372,5 | 768,1 |

Batas terbukti peluang koalisi ini lolos adalah 1,2 x 10^-25 ([batas deteksi terbukti](#batas-deteksi-terbukti)). Skor tertinggi penerima tak bersalah di seluruh percobaan adalah 72 % dari ambang. Nol tuduhan salah dalam 1.000 percobaan hanya menunjukkan bahwa lajunya kira-kira di bawah 3 x 10^-3, jadi batasnya juga diuji pada tingkat yang dapat diukur. Pada target 10^-2 laju empirisnya 6,6 x 10^-4, dan pada target 10^-3 lajunya 2,8 x 10^-5 (dari 679.000 skor penerima tak bersalah, termasuk skor strategi terburuk yang mengulang skor minoritas). Hasil ini konsisten dengan batas Chernoff yang konservatif. Pada 10^-6 batasnya tidak dapat diuji dengan sampling; jaminannya berasal dari batas matematis.

Uji tambahan (berkas lengkap di [`results/`](results/)):

| Skenario | Tuduhan salah | Deteksi | Semua tertangkap |
|---|---|---|---|
| N=20, c=3 (m=2987) | 0 | 100 % | 100 % |
| N=100, c=3, kanal berderau: 5 % bit salah, 35 % terhapus | 0 | 100 % | 98 sampai 100 % |
| N=100, kode untuk c=3 diserang 5 orang (di luar rancangan), 300 percobaan | 0 | 100 % | 42 sampai 49 % (strategi hapus: 100 %) |

Tabel parameter (eps = 10^-6, `tapak simulate --table`):

| N | c | eps1 | m (K=2 pi^2) | m (K=100) | Z Chernoff | Z Gauss | rata-rata skor kolusi per anggota | batas lolos terbukti (K=2 pi^2) |
|---|---|---|---|---|---|---|---|---|
| 20 | 2 / 3 / 5 | 5e-8 | 1328 / 2987 / 8297 | 6725 / 15131 / 42029 | 233 / 340 / 552 | 194 / 291 / 485 | 423 / 634 / 1056 | 5e-17 / 2e-23 / 2e-38 |
| 50 | 2 / 3 / 5 | 2e-8 | 1400 / 3150 / 8749 | 7092 / 15955 / 44319 | 246 / 359 / 582 | 205 / 308 / 514 | 446 / 668 / 1114 | 7e-18 / 1e-24 / 1e-40 |
| 100 | 2 / 3 / 5 | 1e-8 | 1455 / 3273 / 9091 | 7369 / 16579 / 46052 | 256 / 373 / 605 | 214 / 321 / 535 | 463 / 695 / 1158 | 2e-18 / 1e-25 / 4e-42 |
| 500 | 2 / 3 / 5 | 2e-9 | 1582 / 3559 / 9885 | 8013 / 18028 / 50076 | 278 / 405 / 658 | 234 / 351 / 585 | 504 / 755 / 1259 | 4e-20 / 8e-28 / 1e-45 |

### Batas deteksi terbukti

Simulasi hanya menunjukkan bahwa koalisi selalu tertangkap dalam percobaan yang dijalankan. `tapak/tardos/detection.py` memberi batas atas peluang sebaliknya, yaitu tidak satu pun anggota koalisi mencapai ambang. Batas ini berlaku untuk setiap strategi yang mematuhi asumsi penandaan, tanpa pendekatan asimtotik atau Gauss.

* **Caranya.** Bila tidak ada anggota yang mencapai Z, jumlah skor koalisi di bawah c x Z. Jumlah itu adalah jumlah per posisi yang hanya bergantung pada banyaknya bit 1 di antara anggota, bit yang dibocorkan, dan bias posisi itu. Koalisi tidak tahu biasnya, jadi faktor Chernoff tiap posisi dapat dimaksimalkan atas pilihan bit bocor secara terpisah. Hasilnya berlaku untuk strategi apa pun, termasuk yang acak atau memakai posisi lain. Ambang Z yang ikut berubah dengan vektor bias dibatasi oleh fungsi Chernoff-nya sendiri. Integral atas sebaran bias dihitung dengan kuadratur Gauss-Legendre dan diperiksa dengan kisi dua kali lebih rapat. Turunan lengkapnya ada di docstring modul.
* **Cakupan.** Pembacaan penuh dengan bit pasti, juga penghapusan di posisi tempat salinan koalisi berbeda (strategi hapus) dan penghapusan yang tidak bergantung pada kode (batasnya lalu dihitung dengan jumlah posisi yang terbaca). Bobot lunak, bit salah, dan penghapusan yang menyasar posisi tertentu hanya diukur ([batasan 12](keamanan.md#batasan)).
* **Strategi terburuk.** Strategi `worst-case` (terburuk) membocorkan bit yang membuat rata-rata skor koalisi per posisi paling kecil. Dengan sebaran bias TAPAK, rumus tertutupnya menunjukkan bahwa ini selalu bit minoritas. Faktor Chernoff justru terbesar untuk bit mayoritas pada parameter TAPAK, karena ekor bawah skornya lebih berat. Keduanya ikut dalam simulasi, dan batasnya berlaku untuk keduanya.

| c | batas lolos terbukti, K = 2 pi^2 (N = 20 / 100) | K untuk batas 10^-3 (N = 20 / 100) | K untuk batas 10^-6 (N = 20 / 100) |
|---|---|---|---|
| 2 | 5 x 10^-17 / 2 x 10^-18 | 10,9 / 10,7 | 13,3 / 12,9 |
| 3 | 2 x 10^-23 / 1 x 10^-25 | 9,7 / 9,5 | 11,7 / 11,4 |
| 4 | 5 x 10^-31 / 6 x 10^-34 | 9,0 / 8,8 | 10,6 / 10,4 |
| 5 | 2 x 10^-38 / 4 x 10^-42 | 8,5 / 8,4 | 9,9 / 9,7 |

Batas ini mencakup setiap koalisi berukuran paling banyak c dan memakai ambang pembacaan penuh untuk seluruh eps. Pelacakan yang tercatat memakai jatah eps yang lebih kecil, jadi ambangnya lebih tinggi dan batasnya naik pelan dengan nomor pelacakan: untuk N paling sedikit 20, paling besar 2 x 10^-16 pada pelacakan pertama, 4,3 x 10^-12 pada pelacakan ke-10, dan 1,4 x 10^-8 pada pelacakan ke-100. Untuk N di bawah 20 batasnya juga sedikit lebih besar (4,5 x 10^-14 untuk c = 2 dan N = 1, seluruh eps). Jadi konstanta bawaan cukup dengan margin lebar.

Perbandingan dengan simulasi (`research/deteksi/ukur.py`; grid ditetapkan sebelum simulasi dijalankan, angka mentah di `research/deteksi/hasil/`): c = 2 sampai 5, N = 20 dan 100, 8 strategi, 1.000 percobaan per strategi. Pada panjang bawaan tidak ada koalisi yang lolos. Pada kode pendek yang sengaja dibuat lemah:

| Batas terbukti | 0,9 | 0,5 | 0,1 | 0,01 |
|---|---|---|---|---|
| Panjang kode (c = 3, N = 20) | 973 | 1070 | 1212 | 1353 |
| Laju lolos terukur tertinggi (semua c, N, dan strategi) | 14 % | 4,4 % | 0,6 % | 0,1 % |

Tidak ada laju terukur yang melampaui batasnya, dan tidak ada tuduhan salah. Batasnya longgar: laju terukur tertinggi 6 sampai 17 kali lebih kecil.

Strategi terburuk hanya terburuk untuk rata-rata skor per posisi, dan kedelapan strategi itu memilih bit dari satu posisi saja. Pemeriksaan ulang (`research/deteksi/penyeimbang.py`, c = 2 sampai 4, N = 20, 2.000 percobaan per sel) memakai koalisi yang melihat semua posisi dan memilih bit agar perkiraan skor anggotanya tetap sama rata. Koalisi ini lolos sampai 4 kali lebih sering daripada strategi terbaik di atas: paling tinggi 22 %, 6 %, dan 0,65 % pada batas 0,9, 0,5, dan 0,1. Itu tetap di bawah batasnya; batasnya 4 sampai 15 kali lebih besar. Batas terbukti berlaku untuk strategi seperti ini juga; simulasi hanya memeriksa contoh yang kami coba. Batas itu mengecil secara eksponensial terhadap m, jadi pada panjang bawaan pun sudah sangat kecil.

## Hasil lain

| Pengujian | Hasil |
|---|---|
| Kumpulan foto sintetis (`make photos` lalu `make bench`): 32 foto layar bersudut 0 sampai 30 derajat dan 8 tangkapan layar dari 4 salinan (halaman 1), dikompresi JPEG dua kali seperti WhatsApp. Satu penerbitan 20 salinan dengan id salinan acak, benih foto 2026 | 39 dari 40 benar, 1 "tidak cukup bukti" (foto dengan 95 % kertas jenuh putih), 0 tuduhan salah. Dua foto dengan 88 dan 90 % kertas jenuh gagal dengan dekoder latar lama dan kini benar ([batasan 4](keamanan.md#batasan)) |
| Foto kertas cetak (`make photos-cetak` lalu `make bench`, dilaporkan terpisah): halaman 1 dan 2 dari 4 salinan yang sama, dicetak printer laser simulasi dengan profil latar bawaan, 16 foto (10 dan 30 derajat, 1600 px) dan 8 pasangan dua halaman | satu halaman 2 dari 16 benar (keduanya halaman 1 salinan #20), dua halaman 3 dari 8, 0 tuduhan salah |
| Foto ponsel dan foto layar simulasi (`make photos-ponsel`, `make photos-layar`, dilaporkan terpisah; [rincian](#foto-ponsel-dan-foto-layar-simulasi)): adegan `make photos` lewat ISP ponsel, dan salinan di monitor simulasi 93 sampai 227 ppi dengan ISP ponsel, 32 foto masing-masing | 32 dari 32 dan 31 dari 32 benar, 0 tuduhan salah (penerbitan di mesin uji) |
| 10 foto sintetis bersudut sampai 30 derajat | 10 dari 10 benar |
| Halaman gabungan digital: setengah atas salinan A, setengah bawah salinan B (2 pasangan) | penerima A dan B dituduh, tidak ada orang lain |
| Teks salinan disalin-tempel (MuPDF dan poppler) | kode utuh, salinan teridentifikasi |
| Teks diketik ulang dengan 5 % salah ketik (kanal semantik) | 4 bit semantik pulih 20 dari 20 percobaan; tidak cukup untuk menyebut nama |
| Teks diketik ulang, kanal pilihan kata ([rincian](#kanal-pilihan-kata-opsional)): dokumen sintetis 6 halaman (47 bit), 200 percobaan untuk N = 20 dan 200 untuk N = 100, pelacakan pertama yang tercatat | 395 dari 400 benar, 0 tuduhan salah; nota dinas contoh 2 halaman (11 bit): "tidak cukup bukti" |
| Dokumen induk hasil pindai (nota dinas sintetis 2 halaman, 300 dpi), 20 salinan: PDF salinan, tangkapan layar, dan foto sintetis halaman 1 ([rincian](keamanan.md#batasan)) | 60 dari 60 benar, 0 tuduhan salah; gabungan sepertiga halaman dari 3 salinan: 15 dari 15 anggota koalisi tertangkap, tidak ada orang lain |
| Penerbitan 20 salinan dokumen 2 halaman | sekitar 4 sampai 5 detik (hasil pindai 300 dpi: sekitar 30 detik) |
| Kanari DNS, pembukaan disimulasikan (kueri langsung ke pendengar lokal) | tercatat dalam sekitar 0,1 detik (syarat: di bawah 5 detik) |
| Registri: verifikasi hanya dengan kunci publik, setiap perubahan baris terdeteksi | lulus |
| `make demo` (skenario lengkap) | sekitar 18 sampai 20 detik di mesin uji yang dipakai bersama, termasuk sekitar 5 detik untuk templat induk tepat pada pelacakan foto |

## Kanal pilihan kata (opsional)

Pengetikan ulang menghapus semua tanda kecuali isi kata-katanya. Kanal ini memberi setiap salinan pilihannya sendiri di antara bentuk yang bermakna sama dalam naskah dinas, misalnya "sehubungan dengan" atau "berkenaan dengan", "terdiri atas" atau "terdiri dari", "dan" atau "serta" di antara dua kata biasa. Kanal ini tidak aktif kecuali penerbit memilihnya dan meninjau setiap titiknya (`tapak leksikal` atau halaman Terbitkan, lihat [operasi](operasi.md#kanal-pilihan-kata-opsional)). Tanpa itu, penerbitan, catatan penerbitan, dan registri sama persis dengan sebelumnya.

* **Tabel leksikon.** Bentuk-bentuknya ada di `tapak/assets/leksikon/naskah_dinas_v1.json` (versi 1). Tabel ini masih **draf** dan belum disahkan peninjau bahasa Tata Naskah Dinas. Versi dan digest tabel dicatat di berkas tinjauan, catatan penerbitan, dan registri. Bentuk dalam satu aturan berbeda sedikitnya 3 karakter, dan tidak ada bentuk yang sama dengan bentuk lain dikurangi satu kata. Dengan begitu, salah ketik atau kata yang terlewat tidak mengubah satu bentuk menjadi bentuk lain.
* **Yang tidak pernah diubah.** Angka, nama, satuan, jabatan, waktu, koordinat, bilangan, perintah, larangan, tenggat, dan kata ingkar tidak pernah diubah. Frasa ditolak bila frasa itu sendiri, atau kata dalam jarak dua kata di kalimat yang sama, termasuk salah satunya. Ungkapan tetap seperti "dan lain-lain", "namun demikian", atau "untuk mereka" juga ditolak. Judul paragraf (juga "14. Maksud dan tujuan."), kepala surat, tanda tangan, tembusan, kaki halaman, dan kalimat kanal semantik tidak disentuh; tanda tangan, tembusan, dan kaki halaman juga tidak dihitung sebagai kata isi. Pemindaian hanya melaporkan jumlah penolakan per kategori, tanpa kata dokumen.
* **Tata letak.** Setiap kombinasi bentuk pada satu baris harus muat kembali di baris yang sama: tepi kiri dan kanan tetap, label "1.", "14." atau "a." dan kata pertama sesudahnya tetap di tempatnya (label dikenali dari bentuknya dan kolom teksnya, bukan dari lebar celahnya), jarak antarkata 1 sampai 3 spasi. Kata lain di baris itu digambar dengan glifnya sendiri dan tetap membawa karakter tak terlihat serta huruf kembarnya. Baris itu keluar dari kanal geser. Pada nota dinas contoh, kanal geser turun dari 183 menjadi 140 bit; pada surat telegram, dari 97 menjadi 84.
* **Peninjauan.** Setiap titik disetujui atau ditolak manusia, dengan melihat seluruh kalimatnya (lintas baris) dan frasanya dalam kurung siku. Penerbitan diblokir selama masih ada titik yang menunggu. Titik dan bentuk yang disunting di luar TAPAK ditolak, karena digest pemindaiannya tidak cocok dan pemindaian ulang dokumen induk memberi titik yang berbeda. Keputusan setuju atau tolak di berkas itu tidak diautentikasi: berkas yang statusnya disunting tangan tetap diterima, jadi `leksikal.json` dijaga seperti dokumen induk.
* **Posisi kode.** Dokumen yang memakai kanal ini mengambil posisi kanal semantik dan pilihan kata hanya dari posisi dengan bias 0,3 sampai 0,7. Keduanya memakai satu urutan berkunci: semantik dari depan, pilihan kata dari belakang. Penerbitan ditolak bila pita itu tidak cukup untuk semua bit keduanya (misalnya c = 1 dengan dokumen panjang), jadi posisinya tidak pernah bertabrakan atau berulang. Aturan ini dicatat sebagai `retype_positions` di catatan penerbitan dan registri; dokumen lama tetap memakai aturan seragam. Pemilihan hanya memakai vektor bias, tidak pernah kode penerima, jadi ambang Chernoff tetap berlaku. Di dekat p = 1/2, satu pembocor menyumbang skor sampai 1 per bit. Sebaliknya, koalisi yang memilih bit minoritas menekan skornya ke sekitar nol, jadi posisi ini hanya menolong untuk pembocor tunggal.
* **Dekode.** Teks bukti disejajarkan dengan teks induk (jarak edit), lalu setiap bentuk dicocokkan bersama konteks 16 karakter di kiri dan kanannya. LLR = 2 x selisih jarak edit, paling besar 6, dan paling besar 2 bila suntingan berkumpul di frasa itu. Frasa yang ditulis ulang atau terpotong dianggap tidak terbaca, bukan dibaca salah. Pengecualiannya titik berkonteks berulang: frasa dan konteksnya juga ada di bagian lain dokumen. Bila pembocor menukar urutan kalimat, titik itu dapat terbaca di tempat lain dengan yakin. Akibatnya skor pembocor turun, tetapi salinan lain tidak pernah tertuduh karenanya. Pemindaian menandai titik seperti ini untuk peninjau; kedua contoh tidak memilikinya. Ambangnya tetap dihitung dari vektor bias dan bobot dekoder.
* **Tanda yang terlihat.** Pilihan kata dan varian kalimat terlihat di kertas. Bila sebuah nama hanya didukung kedua kanal itu (tanpa keduanya salinan itu tidak mencapai ambang), hasil CLI, web, dan berita acara menambahkan peringatan di bawah putusan: siapa pun yang pernah membaca salinan itu dapat meniru pilihan katanya saat mengetik ulang, jadi hasil itu menunjuk pilihan kata salinan tersebut, bukan pengetiknya, dan memerlukan bukti pendukung. Peringatan ini tidak mengubah ambang atau putusan.

Angka di bawah dibuat ulang dengan `research/ketik/ukur.py`; semua pilihan acak berasal dari benih tetap, dan keluarannya disimpan di `research/ketik/hasil/` (`kapasitas.jsonl`, `galat.jsonl`, `atribusi.jsonl`). Pengetikan ulangnya disimulasikan (`tapak/ketik.py`); belum ada orang sungguhan yang mengetik ulang. Semua angka memakai tabel draf tingkat A.

Kapasitas. Dokumen sintetis panjang berisi paragraf isi kedua templat contoh yang diulang 2 sampai 6 kali. Karena paragrafnya berulang, semua titiknya berkonteks berulang: angka atribusi di bawah berlaku untuk bocoran yang tidak menukar urutan kalimat.

| Dokumen | Halaman | Kata isi | Bit pilihan kata |
|---|---|---|---|
| nota dinas contoh | 2 | 307 | 11 |
| surat telegram contoh | 2 (isi 1 halaman) | 137 | 5 |
| sintetis | 4 / 6 / 7 / 8 / 10 | 883 / 1.318 / 1.757 / 2.201 / 2.641 | 31 / 47 / 62 / 78 / 94 |

Rata-ratanya sekitar 3,6 bit per 100 kata isi, atau sekitar 10 bit per halaman isi penuh (sekitar 290 kata).

Galat baca, 500 salinan per dokumen per tingkat derau. Setiap salinan memakai rahasia kode baru, dan setiap sel berisi bit terhapus lalu bit salah di antara yang terbaca. Tingkat "sedang" berarti per kata 5 % salah ketik, 1 % salah baca OCR, 1 % kata hilang, 1 % kata menyatu, dan 5 % tanda baca hilang. "Kebiasaan" berarti pengetik menulis bentuk induk, bukan bentuk salinannya, pada 5 % titik; galat ini sistematis dan tidak terlihat dekoder.

| Derau | nota dinas (5.500 bit) | surat telegram (2.500 bit) | sintetis 6 halaman (23.500 bit) |
|---|---|---|---|
| tanpa derau | 0 %; 0 salah | 0 %; 0 salah | 0 %; 0 salah |
| ringan | 0,7 %; 0,13 % | 0,5 %; 0,48 % | 0,6 %; 0,19 % |
| sedang | 1,3 %; 0,24 % (13 dari 5.428) | 0,8 %; 0,60 % (15 dari 2.480) | 1,3 %; 0,41 % (95 dari 23.206) |
| berat | 4,7 %; 0,63 % | 3,3 %; 2,3 % | 4,1 %; 1,1 % |
| OCR | 0,7 %; 0,13 % | 0,6 %; 0,32 % | 0,6 %; 0,21 % |
| sedang + kebiasaan 5 % | 1,3 %; 2,6 % | 1,0 %; 2,9 % | 1,3 %; 2,9 % |

Atribusi pembocor tunggal, 200 percobaan per sel. Teks salinan diketik ulang pada tingkat sedang dan dibaca dekoder. Putusannya dari `fuse` dan `attribute` dengan jatah eps pelacakan pertama yang tercatat di registri (61 % dari eps = 10^-6), memakai bit pilihan kata saja (tanpa bit semantik).

| Dokumen | Kata isi | Bit | Disebut benar, N = 20 | Disebut benar, N = 100 |
|---|---|---|---|---|
| nota dinas contoh | 307 | 11 | 0 dari 200 | 0 dari 200 |
| sintetis 4 halaman | 883 | 31 | 12 dari 200 | 1 dari 200 |
| sintetis 6 halaman | 1.318 | 47 | 200 dari 200 | 195 dari 200 |
| sintetis 7 halaman | 1.757 | 62 | 200 dari 200 | 200 dari 200 |
| sintetis 8 halaman | 2.201 | 78 | 200 dari 200 | 200 dari 200 |

Tidak ada tuduhan salah dalam 2.000 percobaan. Ada dua angka yang berbeda:

* **Terukur.** Pada derau sedang, deteksi 95 % tercapai di antara 883 kata isi (31 bit) dan 1.318 kata isi (47 bit), kira-kira mulai 1.300 kata isi atau 4 sampai 5 halaman isi penuh. Pelacakan berikutnya memakai jatah eps yang lebih kecil, jadi deteksinya sedikit turun.
* **Batas TAPAK.** Keluaran penerbit baru menyatakan "cukup untuk satu pembocor" mulai 64 bit (bit semantik ikut dihitung), sekitar 1.800 kata isi atau 6 halaman isi penuh dengan tabel ini. Batas ini ditetapkan sebelum pengukuran di atas, dengan cadangan untuk derau berat dan kebiasaan pengetik: simulasi riset menunjukkan 56 sampai 64 bit untuk deteksi 95 % pada kondisi itu. Di bawahnya, penerbit dan berita acara menyebut kekurangan bitnya dan perkiraan kata isi tambahan menurut kepadatan dokumen itu sendiri.

Kolusi tidak tertangani di teks ketikan ulang. Menurut simulasi riset (200 percobaan per sel, derau baca terukur), koalisi 3 orang yang memilih bentuk minoritas tidak pernah tertangkap dengan posisi pita (0 dari 200 sampai 768 bit). Dengan posisi seragam pun koalisi itu baru tertangkap pada sekitar 1.000 sampai 1.500 bit, kira-kira 90 sampai 140 halaman isi dengan tabel ini.

## Salinan yang dicetak

Pola latar bawaan (253 +/- 2) terlalu terang untuk printer. Model printer kami mengasumsikan tingkat abu-abu di atas sekitar 250 tercetak sebagai kertas polos; angka ini belum diukur pada printer sungguhan, dan kesimpulan di bagian ini paling bergantung padanya. Foto salinan yang dicetak karena itu hanya membawa kanal geser, sekitar 80 sampai 100 posisi kode terbaca per halaman. Printer sungguhan belum diuji; angka di bagian ini berasal dari simulator printer dan foto sintetis. Hasil lengkapnya ada di [`results/`](results/) (`cetak_summary.json`, `cetak_visibility.json`, `cetak_calibration.json`, `cetak_needbits.txt`), dan cara membuatnya ulang di [operasi](operasi.md#mengukur-salinan-yang-dicetak).

Angka di bagian ini diukur dengan dekoder produksi sebelum kanal latar memakai strata kejenuhan dan uji pilot ([batasan 4](keamanan.md#batasan)), dan belum diukur ulang. Untuk profil bawaan hal itu praktis tidak berpengaruh, karena di kertas tidak ada pola latar ([batasan 3](keamanan.md#batasan)). Untuk profil cetak, yang hasilnya ditentukan kanal latar, dekoder sekarang dapat memberi angka yang berbeda. Baris foto kertas cetak di [hasil lain](#hasil-lain) memakai dekoder sekarang.

### Simulator printer

`print_page` di `tapak/photos.py` meniru printer laser kantor 600 dpi (preset `INKJET` untuk inkjet). Lembar hasilnya lalu difoto oleh simulator foto yang sama dengan benchmark.

1. Teks dirasterisasi di kisi printer tanpa anti-aliasing, seperti RIP printer.
2. Tingkat abu-abu 250 ke atas menjadi kertas polos (asumsi tanpa angka pabrikan, dapat diatur lewat `white_cutoff`).
3. Warna lain diraster dengan raster AM 106 lpi pada 45 derajat.
4. Banding drum dan roda gigi menggeser garis pindai sampai 25 um.
5. Sebaran sinar laser dan toner, derau toner, dan ambang pengembangan membuat tepi huruf melebar sekitar 22 um dan bergerigi sekitar 15 um.
6. Kertas miring sampai 0,25 derajat, bergeser sampai 1 mm, dan skalanya meleset sampai 0,2 %.
7. Cahaya menyebar di dalam kertas (dot gain optis), dan kertas punya tekstur serat serta awan.

Nilainya dari literatur dan perkiraan orde besaran, bukan dari printer yang diukur. Kalibrasinya (`scripts/cetak/calibrate.py`): abu-abu 50 % tercetak 11,7 poin persentase lebih gelap, dan tingkat 245 sampai 249 tercetak sebagai titik terkecil (dL* -1,9). Yang tidak dimodelkan: koreksi nada driver, mode hemat toner, printer warna, mesin fotokopi dan pemindai, serta pemrosesan gambar di kamera ponsel (ISP ponsel simulasi, [di bawah](#foto-ponsel-dan-foto-layar-simulasi), belum dipakai untuk foto kertas cetak).

### Templat induk tepat

Dekoder geser mencocokkan setiap kelompok kata pada foto dengan templat dari dokumen induk. MuPDF menggambar glif kecil dari cache bitmap pada piksel utuh, jadi templat lama (render 4 kali lebih rapat lalu dirata-rata) menggeser kelompok kata sampai puluhan mikrometer, sama untuk setiap salinan dan foto. Templat tepat dirender pada 3.200 dpi atau lebih, saat glif digambar sebagai kurva tanpa pembulatan, per pita, lalu dirata-rata turun. Render tepat induk pada 4.800 dpi bergeser kurang dari 0,3 um terhadap templat ini untuk setiap kelompok. Hanya pita yang memuat baris teks yang dibaca dekoder geser yang dirender, dipotong ke kolom baris itu; pitanya sama dengan render seluruh halaman, jadi nilai pikselnya identik. Rendernya memerlukan sekitar 5 sampai 7 detik CPU per halaman penuh teks di mesin uji (render seluruh halaman: 7 sampai 12 detik), sekali untuk setiap halaman dan resolusi analisis per proses. `tapak web` menyimpan templat di memori (sampai 320 MB); setiap perintah `tapak trace` merendernya lagi.

Pada foto kertas cetak, templat tepat hampir tidak mengubah hasil (tabel di bawah, dibandingkan dengan templat lama pada foto yang sama). Pada benchmark README putusannya identik untuk ke-64 pelacakan (diukur sebelum strata kejenuhan).

### Hasil dengan profil latar bawaan

Protokol: printer laser simulasi, foto sintetis (sudut pandang diundi 0 sampai 30 derajat, parameter lain diundi), salinan 1 sampai 20 dari 100 (N = 100, c = 3, eps = 10^-6), dekoder produksi sebelum strata kejenuhan. "Dua halaman" menggabungkan foto halaman 1 dan 2 salinan yang sama dalam satu pelacakan.

| | 1600 px (WhatsApp standar) | 4000 px (WhatsApp HD) |
|---|---|---|
| Posisi geser terbaca per halaman (hal. 1 / hal. 2) | 102 / 79 | 103 / 80 |
| Galat bit kanal geser (hal. 1 / hal. 2) | 4,8 % / 3,3 % | 0 % / 0 % |
| Pola latar ditemukan | 0 dari 40 | 0 dari 40 |
| Satu halaman menyebut salinan yang benar | 0 dari 40 | 0 dari 40 |
| Skor salinan yang benar, median (maks.), persen ambang | 59 % (79 %) | 62 % (85 %) |
| Dua halaman menyebut salinan yang benar | 5 dari 20 | 8 dari 20 |
| Tuduhan salah | 0 | 0 |
| Templat lama, foto yang sama: galat bit; dua halaman | 4,6 % / 3,1 %; 4 dari 20 | 0,05 % / 0,19 %; 8 dari 20 |

Salinan yang benar selalu berskor tertinggi, tetapi satu halaman tidak mencapai ambang, bahkan pada 4000 px ketika semua bit yang terbaca benar. Batasnya kapasitas, bukan derau: menurut simulasi tingkat kode dengan vektor bias dokumen ini (`scripts/cetak/needbits.py`), satu pembocor perlu sekitar 300 posisi terbaca (galat sampai 5 %), dan menyebut minimal satu dari tiga anggota koalisi perlu 1.200 sampai 1.500.

### Profil latar cetak (opsional)

`tapak issue ... --latar cetak` menggambar pola latar 242 +/- 5 (tingkat 237 sampai 247), di bawah ambang yang diasumsikan model printer. Dekodernya sama, dan catatan penerbitan menyimpan pengaturan pola. Profil ini dipilih dari tiga kandidat (245 +/- 4, 242 +/- 5, 238 +/- 8) setelah melihat hasilnya pada cetakan dan foto simulasi tertentu. Karena itu angka di bawah diukur ulang dengan protokol dan 100 salinan yang sama, tetapi dengan cetakan, foto, dan koalisi baru yang tidak ikut memilih (pengulangan 1, `results/cetak_summary_r1.json`):

| | 1600 px | 4000 px |
|---|---|---|
| Pola latar ditemukan | 40 dari 40 | 40 dari 40 |
| Galat bit kanal latar (hal. 1 / hal. 2); median per foto | 1,9 % / 0,6 %; 0,4 % / 0,3 % | 2,2 % / 2,9 %; 0,6 % / 0,1 % |
| Satu halaman menyebut salinan yang benar | 40 dari 40 | 40 dari 40 |
| Skor salinan yang benar, median (min.), kali ambang | 4,3 (2,4) | 4,2 (1,7) |
| Dua halaman menyebut salinan yang benar | 20 dari 20 | 20 dari 20 |
| Tuduhan salah; skor tak bersalah tertinggi | 0; 66 % ambang | 0; 64 % ambang |

* **Kolusi c = 3 di kertas.** Tiga salinan dipotong menjadi pita atas, tengah, dan bawah di ruang kosong antarbaris, disatukan dalam satu lembar, dicetak, lalu difoto (16 koalisi baru dari salinan 1 sampai 20, 1600 px). Satu halaman menyebut minimal satu anggota pada 31 dari 32 halaman dan ketiganya pada 23 dari 32. Halaman yang gagal difoto miring 29 derajat dengan resolusi efektif 97 dpi; polanya tidak terdeteksi (z = 0,56), jadi jawabannya "tidak cukup bukti". Dua halaman: 16 dari 16 dan 15 dari 16. Tidak ada orang tak bersalah yang disebut (skor tertinggi 58 % ambang).
* **Printer inkjet simulasi** (halaman 1 salinan 1 sampai 10, 1600 px): 10 dari 10, galat bit 3,6 % (median 0 %).
* **Foto yang buruk** tetap melemahkan pola: tiga foto terburuk bergalat bit 25 sampai 32 % (hanya satu di antaranya terlalu terang, 43 % piksel jenuh), tetapi ketiganya masih menyebut salinan yang benar.
* **Pada cetakan dan foto yang ikut memilih profil** (`results/cetak_summary.json`) hasilnya serupa: satu halaman 40 dari 40 per resolusi, dua halaman 20 dari 20, koalisi 32 dari 32 (ketiganya 27), inkjet 10 dari 10, tanpa tuduhan salah.

Harganya tampilan. Seluruh halaman tampak abu-abu muda: dL* -3,4 terhadap kertas pada laser simulasi dan -4,5 di layar. Teksturnya di ambang terlihat: S-CIELAB pada 35 cm rata-rata 1,1 dan persentil 95 sebesar 3,5 (pola layar bawaan: 0,4 dan 0,8; raster abu-abu polos setingkat: 0,75 dan 2,0), dengan 1 sebagai beda yang nyaris terlihat (`scripts/cetak/visibility.py`). Karena itu profil ini tidak menjadi bawaan dan TAPAK menampilkan peringatan saat dipakai. Printer biasanya menyisakan tepi putih beberapa milimeter, sehingga halaman abu-abu tampak berbingkai putih. Belum diuji dengan printer, ponsel, maupun pengamat sungguhan.

## Foto ponsel dan foto layar (simulasi)

Semua angka di bagian ini berasal dari simulasi. Ponsel, monitor, dan ISP sungguhan belum diuji, jadi angkanya menunjukkan kepekaan dekoder terhadap model kami, bukan hasil di perangkat nyata.

### Simulator

`tapak/ponsel.py` menambah dua bagian opsional ke `tapak/photos.py`. Tanpa keduanya keluaran simulator sama persis dengan sebelumnya: `make photos` dan `make photos-cetak` dengan benih 2026 dibuat ulang dan hash ke-58 berkasnya sama, dan `tests/test_ponsel.py` menyimpan hash emasnya.

**ISP ponsel** (profil `ponsel`; profil `netral` adalah simulator lama). Urutannya mengikuti pipa kamera ponsel [7, 8]:

1. *HDR beruntun*: 2 sampai 8 bingkai yang sengaja kurang terang (0 sampai 2 stop) digabung, sehingga varians derau dibagi jumlah bingkai [7, 8]. Banyaknya kurang terang tidak disebut sumbernya, jadi rentangnya asumsi.
2. *Pengurangan derau*: filter terpandu [11] pada skala halus dan kasar (radius 1 sampai 2 dan 4 sampai 10 piksel bingkai 12 MP), dengan ambang 1 sampai 2,5 kali derau setempat dari model derau dua parameter yang dilaporkan ponsel [9, 10]. Penyaring bilateral bekerja paling baik di sekitar 2 kali derau [12]. Cara ini menghapus tekstur berkontras rendah, yang dikenal sebagai kehilangan tekstur pada ponsel [13, 14].
3. *Pemetaan nada lokal*: lapisan dasar dan detail di ranah log [15]; kontras dasar dikali 0,5 sampai 0,85, detail 1,0 sampai 1,3, bagian terang terbesar diletakkan di 85 sampai 97 % putih, lalu bahu sorotan lembut. Nilainya asumsi di dalam metode itu.
4. *Penajaman*: unsharp mask dengan coring, radius 1 sampai 2 kali blur lensa, kekuatannya diatur agar tepi tajam melampaui 10 sampai 40 %. Imatest mencatat 7 % untuk penajaman sedang di DSLR, menyebut 35 % kemungkinan mengganggu, dan menyebut lingkaran cahaya besar pada ponsel [16].
5. *JPEG kamera*: kualitas 85 sampai 95, "rentang pemakaian umum" `android.jpeg.quality` yang juga mengatur kualitas HEIC [9]. HEIC sendiri tidak disimulasikan. Setelah itu pengguna memotong dan WhatsApp mengecilkan serta mengompresi dua kali seperti sebelumnya.

**Monitor** (jenis `fotolayar`). Penampil PDF menampilkan halaman pas setinggi 80 sampai 92 % layar, dengan latar penampil terang atau gelap.

* Monitor: 23,8 inci 1920 x 1080 (92,6 ppi), 27 inci 2560 x 1440 (108,8 ppi), 27 inci 3840 x 2160 (163,2 ppi), dan laptop 13,3 inci 2560 x 1600 (227 ppi). Kepadatan piksel dihitung dari geometri. Di survei Steam September 2026, 1920 x 1080 adalah layar utama 47,9 % pengguna dan 2560 x 1440 27,0 % [17] (pengguna gim, bukan kantor).
* Subpiksel RGB tegak, masing-masing sepertiga jarak piksel, dengan matriks hitam; bagian menyala 70 sampai 90 % lebarnya dan 75 sampai 92 % tingginya (asumsi).
* Gamma 2,0 sampai 2,4 (sRGB sekitar 2,2 [18], BT.1886 2,4 [19]); putih 100 sampai 300 cd/m2 (layar kantor umumnya berlatar terang 140 sampai 180 cd/m2 [20]); kontras 800 sampai 3000 (asumsi); lampu latar 0 sampai 20 % lebih gelap di sudut (asumsi).
* Penurunan terang menurut sudut pandang: 75 % pada 35 sampai 50 derajat mendatar dan 22 sampai 45 derajat tegak. RTINGS mengukur sudut 75 % itu 39 sampai 42 derajat pada monitor IPS dan 22 derajat dari bawah pada panel lemah [21].
* Pantulan cahaya ruangan 0,5 sampai 4 % putih, dan pantulan lampu (opsional) 5 sampai 50 % putih: lampu kantor paling terang sekitar 3000 cd/m2 pada sudut yang diizinkan [20], dikali pantulan permukaan depan sekitar 1 sampai 4 %.
* Kamera: bingkai 12 MP, setara 26 mm, jarak 25 sampai 60 cm (asumsi), blur lensa sigma 0,45 sampai 0,9 piksel (MTF50 sekitar 0,21 sampai 0,42 siklus per piksel; acuan Imatest tanpa penajaman 0,31 [16]), filter Bayer RGGB dan demosaik peka tepi (OpenCV). Setiap piksel kamera mengintegrasikan 3 x 3 sampel setelah blur lensa, jadi kisi subpiksel tercuplik seperti oleh sensor dan menjadi moire. `tests/test_ponsel.py` memeriksa bahwa puncak spektrumnya berada di frekuensi alias yang diramalkan.

Yang tidak disimulasikan: ponsel dan monitor sungguhan, HEIC, panel 6 bit dengan FRC, kedipan PWM lampu latar, ClearType, OLED dan PenTile, silang warna antara filter kamera dan warna monitor, super-resolusi beruntun pengganti demosaik, dan ISP berbasis model.

### Protokol

Protokol dan semua benih ditetapkan di `research/ponsel/ukur.py` sebelum pengukuran pertama dan masuk riwayat repositori lebih dulu.

* Dua dokumen induk fiktif, nota dinas dan surat telegram contoh, masing-masing diterbitkan untuk N = 20 penerima (c = 3, eps = 10^-6) dengan id salinan berbenih. Bukti adalah halaman 1.
* Dua set benih yang terpisah: set **pengembangan** dipakai untuk memilih perubahan dekoder, set **uji** dibuat dan dilacak sekali di akhir dengan kedua dekoder.
* Setiap salinan menghasilkan satu gambar per kondisi. Kondisi foto berbagi adegan, pose, dan derau sensor, begitu pula kondisi layar, jadi selisihnya hanya ISP atau layar:
  * `foto_netral` (foto `make photos`), `foto_ponsel` (ISP penuh), dan `foto_nr`, `foto_hdr`, `foto_nada`, `foto_tajam`, `foto_jpeg` (satu langkah ISP saja, untuk ablasi);
  * `layar_ideal` (monitor tanpa struktur subpiksel), `layar_netral` (dengan subpiksel, jadi moire), `layar_ponsel` (ditambah ISP), `layar_silau` (ditambah pantulan lampu).
* Sudut pandang 0, 10, 20, dan 30 derajat, keempat monitor, dan jarak 30, 45, dan 60 cm mengikuti rancangan tetap per salinan.
* Halaman 1 dokumen induk tanpa tanda difoto lewat `foto_ponsel`, `layar_netral`, dan `layar_ponsel`, 10 gambar per dokumen, kondisi, dan set. Tidak boleh ada yang dituduh.
* Pelacakan seperti `make bench`: tanpa registri, seluruh eps. Galat bit dihitung terhadap kode salinan yang bocor.

### Perubahan dekoder

Hanya kanal latar pada bukti gambar yang berubah. Halaman PDF yang diteruskan didekode persis seperti sebelumnya.

1. **Penyaring komponen berkala.** Moire adalah beberapa sinusoid kuat di kertas, sedangkan pola latar berpita lebar (sel berkunci yang saling bebas). Dalam petak 128 piksel yang bertumpuk setengah, setiap puncak spektrum yang lebih dari 6 kali rata-rata tetangganya, dan tidak dekat frekuensi nol, dibuang bersama tetangga terdekatnya (`suppress_periodic`). Frekuensi moire bergeser di sepanjang halaman karena perspektif, jadi penyaringan dilakukan per petak.
2. **Penyisihan pencilan dua arah.** Piksel yang menyimpang lebih dari 8 % dari tingkat kertas sudah disisihkan bila lebih gelap (tinta tambahan). Kini piksel yang lebih terang juga disisihkan: lingkaran cahaya penajaman di sisi teks. Penyisihan dilakukan setelah penyaringan, supaya puncak moire tidak ikut terbuang, lalu modulasi dihitung ulang dan disaring sekali lagi.

Keduanya hanya melihat bukti, sebelum tanda sel berkunci diterapkan, jadi uji umpan, uji pilot, dan batas tuduhan salah tidak berubah. Tidak ada ambang atau aturan putusan yang diubah. `tests/test_background_moire.py` memeriksa bahwa mengganti semua kode penerima tidak mengubah satu pengamatan pun.

Metode dipilih pada set pengembangan saja (`research/ponsel/kandidat.py`, ringkasan di `research/ponsel/hasil/pengembangan_kandidat.jsonl`). Aturan pemilihan, dinyatakan setelah kandidat pertama dan grid kecil dinilai tetapi sebelum kandidat terakhir: tidak boleh ada putusan yang hilang di kondisi mana pun, tidak boleh ada tuduhan pada induk tanpa tanda, dan margin harus membaik pada foto yang terpengaruh. Kandidat lain ditolak: strata "tanpa tekstur" (kertas rata, perluasan bobot kliping) kehilangan putusan pada empat kondisi, dan penyisihan pencilan terang pada 5 % tidak stabil (foto ponsel jauh lebih baik, tetapi foto dengan penajaman saja turun dari 37 menjadi 34 benar).

### Hasil

Set uji yang ditahan, dilacak sekali dengan dekoder lama (sebelum studi ini) dan sekali dengan dekoder baru. Setiap baris berisi 40 foto (2 dokumen x 20 salinan); baris induk tanpa tanda berisi 20. "tcb" berarti "tidak cukup bukti". Galat bit dan z pola dihitung per foto, lalu diambil mediannya. Kolom geser memakai dekoder baru; kanal geser tidak berubah.

| Kondisi | Benar / tcb / salah, lama | Benar / tcb / salah, baru | Galat bit latar, median per foto (lama; baru) | z pola median (lama; baru) | Geser: posisi; galat median |
|---|---|---|---|---|---|
| foto tanpa ISP | 38 / 2 / 0 | 38 / 2 / 0 | 1,5 %; 1,5 % | 49,4; 49,4 | 97; 4,6 % |
| foto, ISP ponsel | 40 / 0 / 0 | 40 / 0 / 0 | 9,1 %; 5,0 % | 30,0; 36,0 | 97; 3,3 % |
| hanya pengurangan derau | 38 / 2 / 0 | 38 / 2 / 0 | 2,1 %; 2,0 % | 46,5; 46,5 | 97; 4,6 % |
| hanya HDR beruntun | 40 / 0 / 0 | 40 / 0 / 0 | 1,8 %; 1,7 % | 50,4; 50,6 | 97; 4,6 % |
| hanya pemetaan nada lokal | 37 / 3 / 0 | 37 / 3 / 0 | 2,4 %; 2,3 % | 46,2; 46,3 | 97; 4,4 % |
| hanya penajaman | 38 / 2 / 0 | 38 / 2 / 0 | 8,8 %; 7,4 % | 30,4; 33,9 | 97; 3,3 % |
| hanya JPEG kamera | 38 / 2 / 0 | 38 / 2 / 0 | 1,6 %; 1,6 % | 49,0; 49,1 | 97; 5,2 % |
| monitor tanpa subpiksel, tanpa ISP | 31 / 9 / 0 | 31 / 9 / 0 | 2,7 %; 2,5 % | 31,8; 32,1 | 94; 3,9 % |
| monitor (moire), tanpa ISP | 32 / 8 / 0 | 32 / 8 / 0 | 5,8 %; 4,1 % | 27,5; 30,2 | 94; 3,9 % |
| monitor (moire), ISP ponsel | 39 / 1 / 0 | 39 / 1 / 0 | 4,5 %; 3,1 % | 38,5; 41,2 | 94; 3,9 % |
| monitor, ISP ponsel, silau | 39 / 1 / 0 | 39 / 1 / 0 | 3,5 %; 3,3 % | 40,0; 41,0 | 94; 3,3 % |
| induk tanpa tanda, foto, ISP ponsel | 0 / 20 / 0 | 0 / 20 / 0 | - | 0,2; 0,5 | - |
| induk tanpa tanda, monitor (moire), tanpa ISP | 0 / 20 / 0 | 0 / 20 / 0 | - | 0,6; 0,6 | - |
| induk tanpa tanda, monitor (moire), ISP ponsel | 0 / 20 / 0 | 0 / 20 / 0 | - | 0,4; 0,3 | - |

* **Tidak ada tuduhan salah** pada 1.000 pelacakan per dekoder (set pengembangan dan uji), termasuk 120 foto induk tanpa tanda. Gerbang pola latar lolos sekali pada induk tanpa tanda (dekoder lama, set pengembangan, z = 3,00 tepat di ambang); tidak ada yang dituduh, sesuai laju lolos gerbang yang terukur di [batasan 4](keamanan.md#batasan).
* **Tahap yang paling merugikan pola latar adalah penajaman.** Dengan dekoder lama, penajaman saja menaikkan galat bit latar dari 1,5 % menjadi 8,8 % dan menurunkan z dari 49 menjadi 30. Penajaman yang sama justru memperbaiki kanal geser (galat 4,6 % menjadi 3,3 %). Moire menaikkan galat latar dari 2,7 % menjadi 5,8 % (monitor yang sama dengan dan tanpa subpiksel). Pengurangan derau hampir tidak merugikan (2,1 %), JPEG kamera tidak berpengaruh, dan HDR beruntun mencegah kertas jenuh (40 dari 40).
* **Kegagalan yang tersisa tidak disebabkan ISP atau moire.** Tanpa HDR, setiap "tidak cukup bukti" terjadi pada foto yang 87 sampai 99,5 % kertasnya jenuh di sensor ([batasan 4](keamanan.md#batasan)), sebagian juga beresolusi rendah (laptop 13 inci dari 45 cm, 43 sampai 46 dpi efektif). Pemetaan nada lokal tanpa HDR menggeser kertas jenuh itu ke bawah putih menjadi bidang rata, sehingga strata kejenuhan tidak mengenalinya: 3 gagal, sedangkan tanpa ISP 2. Dengan ISP ponsel penuh, HDR dan pemetaan nada lokal dalam model kami menjaga kertas di bawah putih; satu-satunya kegagalan adalah laptop dari 60 cm, ketika halaman hanya mengisi 20 % bingkai dan tidak ditemukan.
* **Per monitor dan jarak** (ISP ponsel, kedua dekoder): 23,8 inci, 27 inci QHD, dan 27 inci 4K masing-masing 10 dari 10, laptop 9 dari 10; 30 cm 16 dari 16, 45 cm 16 dari 16, 60 cm 7 dari 8. Tanpa ISP: 23,8 inci 7 dari 10, QHD 10 dari 10, 4K 8 dari 10, laptop 7 dari 10.
* **Dekoder baru** tidak mengubah putusan di set uji, tetapi memperlebar margin: pada foto dengan ISP ponsel galat bit latar turun dari 9,1 % menjadi 5,0 % (z 30 menjadi 36), pada monitor tanpa ISP dari 5,8 % menjadi 4,1 %, dan batas peluang tuduhan salah terlemah di antara jawaban benar di baris itu membaik dari 10^-6,0 menjadi 10^-13,6. Di set pengembangan dekoder baru menambah satu jawaban benar pada monitor tanpa ISP dan satu pada pemetaan nada lokal saja.
* **Benchmark** (`make bench`, penerbitan 20 salinan dengan id acak di mesin uji, benih foto 2026): `make photos-ponsel` 32 dari 32 benar, `make photos-layar` 31 dari 32 (gagal: laptop dari 45 cm, halaman mengisi 26 % bingkai), tanpa tuduhan salah. Pada `make photos` dan `make photos-cetak` dari penerbitan yang sama, putusan dekoder lama dan baru sama untuk ke-64 pelacakan; batas peluang tuduhan salah hanya bergeser sedikit (median perubahan log10 -0,005). Hasilnya ada di `research/ponsel/hasil/bench_lama.json` dan `bench_baru.json`.

Yang belum diuji: ponsel, monitor, dan ISP sungguhan. Semua angka di atas bergantung pada model dan rentang parameter yang kami pilih; ISP ponsel yang menajamkan lebih keras, mengurangi derau lebih agresif pada skala sel pola (2 mm), atau mengompresi sorotan lebih rata dapat memberi hasil yang lebih buruk. Pembacaan kanal geser pada foto layar (sekitar 94 posisi per halaman) tidak cukup sendirian untuk menyebut nama, jadi foto layar bergantung pada pola latar seperti foto biasa.

## Keputusan desain yang menyimpang dari spesifikasi awal

| Spesifikasi | Yang dibangun | Alasan |
|---|---|---|
| Kode penuh ditanam di setiap kanal | kanal teks membawa seluruh m bit; setiap halaman membawa irisannya sendiri di kanal fisik; tuduhan hanya dihitung atas posisi yang terbaca dengan ambang ketat untuk himpunan itu | c=3, eps=10^-6 memerlukan sekitar 3000 bit, sedangkan geser kata dan baris hanya memuat sekitar 90 bit per halaman. Skala c^2 ln(1/eps) adalah batas bawah untuk kode tahan kolusi apa pun |
| Geser 0,01 sampai 0,03 mm | 0,05 mm (dapat diatur, maksimum 0,05 mm) | 0,01 sampai 0,03 mm hanya 0,1 sampai 0,3 piksel pada foto ponsel satu halaman A4; tidak terukur setelah JPEG |
| "Selisih piksel tak terlihat" | didefinisikan secara geometris: di antara dua salinan mana pun, tidak ada glif yang bergeser lebih dari 0,1 mm per sumbu (1 menit busur pada jarak baca 35 cm). Diuji pada 600 dpi: perbedaan piksel hanya ada di kotak kata yang digeser (di luar itu hanya pola latar, maksimum 4 tingkat abu-abu) dan pusat tinta bergeser sesuai rencana | tanda geometris mengubah posisi tepi, bukan kontras; ambang tingkat abu-abu tidak bermakna untuk itu |
| Pola latar didekode dengan korelasi terhadap kandidat | korelasi buta per bit (spread spectrum) | korelasi terhadap kandidat memakai kode penerima dan merusak jaminan tuduhan salah Tardos |
| Registri menyimpan kode | registri menyimpan komitmen (`code_digest`); kode diturunkan ulang dari rahasia kode | siapa pun yang dapat membaca kode dapat memfitnah penerima |
| Kanari DOCX lewat referensi font eksternal | relasi gambar eksternal | Word tidak mengambil font eksternal |
| Banyak simbol lebar-nol di akhir kata | paling banyak dua simbol per posisi (sebelum dan sesudah kata), dari alfabet berbeda | MuPDF dan poppler membuang glif identik yang ditumpuk di posisi yang sama (dianggap tebal palsu) |
| Ambang Z ditetapkan sebelum analisis | aturan ambang ditetapkan saat penerbitan; nilai Z dihitung setelah dekode dari posisi yang benar-benar terbaca, sebelum skor dihitung | kanal yang rusak menghapus posisi; ambang tetap untuk pembacaan penuh akan terlalu ketat untuk bukti parsial. Aturannya tetap dan tidak pernah melihat kode penerima, sehingga tidak dapat disesuaikan setelah melihat hasil |
| Konstanta "Skoric 2006, 2 pi^2" | dipertahankan sebagai bawaan, atribusi dikoreksi | 2 pi^2 berasal dari Skoric, Vladimirova, Celik, dan Talstra untuk skor asimetris (pendekatan Gauss). Dengan skor simetris konstanta asimtotiknya pi^2/2, jadi ada margin sekitar 4 kali. Untuk c kecil kecukupannya kini dihitung langsung: batas terbukti peluang koalisi lolos paling besar 5 x 10^-17 untuk c = 2 sampai 5 (eps = 10^-6, N paling sedikit 20, pembacaan penuh; [batas deteksi terbukti](#batas-deteksi-terbukti)). Jaminan tuduhan salah tidak bergantung pada K karena berasal dari ambang Chernoff |

## Referensi

1. G. Tardos. Optimal probabilistic fingerprint codes. Proc. 35th ACM STOC, 2003, hlm. 116-125. Versi jurnal: J. ACM 55(2), 2008.
2. B. Skoric, T. U. Vladimirova, M. Celik, J. C. Talstra. Tardos fingerprinting is better than we thought. IEEE Trans. Inf. Theory 54(8):3663-3676, 2008. arXiv:cs/0607131.
3. B. Skoric, S. Katzenbeisser, M. U. Celik. Symmetric Tardos fingerprinting codes for arbitrary alphabet sizes. Des. Codes Cryptogr. 46(2):137-166, 2008. IACR ePrint 2007/041.
4. T. Laarhoven, B. de Weger. Optimal symmetric Tardos traitor tracing schemes. Des. Codes Cryptogr. 71(1):83-103, 2014. arXiv:1107.3441.
5. J. T. Brassil, S. Low, N. F. Maxemchuk. Copyright protection for the electronic distribution of text documents. Proc. IEEE 87(7), 1999 (pergeseran baris dan kata).
6. M. Tancik, B. Mildenhall, R. Ng. StegaStamp: Invisible hyperlinks in physical photographs. CVPR 2020.
7. M. Delbracio, D. Kelly, M. S. Brown, P. Milanfar. Mobile computational photography: a tour. Annu. Rev. Vis. Sci. 7, 2021. arXiv:2102.09000 (bagian 3.3.3: HDR+ menggabung 2 sampai 8 bingkai yang sengaja kurang terang).
8. S. W. Hasinoff dkk. Burst photography for high dynamic range and low-light imaging on mobile cameras. ACM Trans. Graph. 35(6), 2016.
9. AOSP, metadata kamera Android (`camera/docs/metadata_definitions.xml`): `android.jpeg.quality` ("85-95 is typical usage range", juga untuk HEIC) dan `android.sensor.noiseProfile` (N(x) = sqrt(S x + O)).
10. A. Foi, M. Trimeche, V. Katkovnik, K. Egiazarian. Practical Poissonian-Gaussian noise modeling and fitting for single-image raw-data. IEEE Trans. Image Process. 17(10), 2008.
11. K. He, J. Sun, X. Tang. Guided image filtering. IEEE TPAMI 35(6), 2013.
12. M. Zhang, B. K. Gunturk. Multiresolution bilateral filtering for image denoising. IEEE Trans. Image Process. 17(12), 2008.
13. F. Cao, F. Guichard, H. Hornung. Dead leaves model for measuring texture quality on a digital camera. Proc. SPIE 7537, 2010.
14. IEEE 1858-2016, Camera Phone Image Quality (metrik kehilangan tekstur).
15. F. Durand, J. Dorsey. Fast bilateral filtering for the display of high-dynamic-range images. ACM Trans. Graph. 21(3), 2002.
16. Imatest, dokumentasi Sharpening (imatest.com/docs/sharpening).
17. Steam Hardware and Software Survey, September 2026 (store.steampowered.com/hwsurvey).
18. IEC 61966-2-1:1999, sRGB.
19. ITU-R BT.1886, EOTF acuan layar datar.
20. Trilux, pencahayaan kantor dan stasiun kerja layar: batas luminans menurut EN 12464-1.
21. RTINGS, uji sudut pandang monitor (rtings.com/monitor/tests/picture-quality/viewing-angle).
