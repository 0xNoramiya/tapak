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

Aturan ambang ditetapkan saat penerbitan dan dicatat di registri, bersama ambang Z untuk pembacaan penuh. Untuk setiap bukti, TAPAK menghitung ambang Z setelah dekode, dengan batas Chernoff yang dihitung dari vektor bias dokumen yang sebenarnya dan bobot dekoder. Posisi yang tidak terbaca tidak dihitung, dan setiap posisi memakai bit bocor terburuk. Perhitungan ini tidak melihat kode penerima mana pun (tahap lanjutan [pelacakan bertahap](#pelacakan-bertahap) memakai kode salinan yang sudah dituduh, tetapi tidak pernah kode salinan yang sedang dinilai). Nilainya dicatat dengan cap waktu di hasil dan berita acara, baru kemudian skor dihitung.

Jaminan tuduhan salah karenanya tidak bergantung pada konstanta K maupun pendekatan Gauss. K hanya memengaruhi deteksi. Peluang koalisi lolos juga dibatasi secara matematis, untuk pembacaan penuh dan juga untuk bit salah dan bobot lunak dekoder, selama derau kanal tidak bergantung pada kode ([batas deteksi terbukti](#batas-deteksi-terbukti)). Penghapusan yang sengaja menyasar posisi tempat salinan koalisi sama tidak tercakup dan hanya diukur.

Satu kebocoran dapat dilacak berulang kali, misalnya dengan potongan atau gabungan bukti yang berbeda. Karena itu setiap pelacakan dokumen yang tercatat lebih dulu ditulis di registri dengan nomor urut k per dokumen, sebelum bukti dibaca. Pelacakan ke-k memakai eps_k = eps x 6 / (pi^2 k^2) dan eps1 = eps_k / N, untuk ambang gabungan maupun ambang tiap kanal. Jumlah 1/k^2 untuk semua k adalah pi^2/6, jadi jumlah semua eps_k tepat eps: batas tuduhan salah berlaku untuk semua pelacakan dokumen bersama, selama bukti tiap pelacakan tidak dipilih berdasarkan skor pelacakan sebelumnya ([batasan 13](keamanan.md#batasan)). Peluang tuduhan salah per salinan juga dibagi dengan 6 / (pi^2 k^2). Pelacakan yang tidak tercatat (mode lepas, atau dokumen yang diterbitkan tanpa registri) memakai seluruh eps dan hasilnya menyatakannya. Di dalam satu pelacakan, jatah eps_k dibagi lagi antartahap [pelacakan bertahap](#pelacakan-bertahap).

## Fusi bukti

Setiap kanal menghasilkan rasio log-kemungkinan (LLR) per posisi kode tanpa pernah melihat kode penerima. LLR dijumlahkan; keputusan y_i = tanda LLR, bobot w_i = tanh(|LLR|/2). Skor tuduhan dihitung pada hasil fusi dan pada setiap kanal fisik secara terpisah, sehingga laporan menyebut berapa kanal yang sepakat secara independen. Kanal yang saling bertentangan dilaporkan sebagai kemungkinan manipulasi.

## Pelacakan bertahap

Koalisi yang lebih besar dari c biasanya hanya tertangkap sebagian oleh tuduhan biasa. Pelacakan bertahap mencari anggota lainnya dengan bantuan salinan yang sudah dituduh. Turunan lengkap dan buktinya ada di docstring `tapak/tardos/staged.py`.

* **Tahap 1** adalah tuduhan biasa di atas.
* **Tahap 2.** Bila tahap 1 menuduh salinan, setiap salinan lain dinilai ulang dengan bobot baru. Posisi yang bit bocornya tidak dimiliki satu pun salinan yang sudah dituduh disebut posisi tak terjelaskan. Menurut asumsi penandaan, di posisi itu sedikitnya satu anggota koalisi lain memegang bit bocor, jadi hanya posisi itu yang diberi bobot. Di posisi lain, isi salinan anggota yang tersisa bergantung pada strategi koalisi (mayoritas atau minoritas), jadi bobotnya nol.
* **Besar bobot** diturunkan dari sumbangan skor yang diharapkan dari anggota yang belum dituduh, dengan model acuan dua anggota tersisa, lalu dipadankan dengan ambang Chernoff: sqrt(q(1-q)) ln(1/q) bila bit bocor adalah simbol yang lebih jarang (q = min(p, 1-p)), jauh lebih kecil bila bit bocor adalah simbol yang umum. Bobot terbesar jatuh pada q sekitar 0,1. Model acuan ditetapkan sebelum simulasi dan hanya memengaruhi deteksi. Bobot dekoder ikut dikalikan.
* **Tahap 3 dan 4** mengulang langkah yang sama dengan semua salinan yang sudah dituduh. Pelacakan berhenti pada tahap pertama yang tidak menuduh siapa pun. Salinan yang sudah dituduh tidak dinilai lagi.
* **Ambang.** Setiap tahap memakai ambang Chernoff yang sama dengan bobot tahapnya dan jatah eps-nya sendiri. Ambang itu dicatat dengan cap waktu sebelum skor tahap tersebut dihitung.

**Jaminan tuduhan salah.** Bobot dan ambang tahap lanjutan memakai kata kode salinan yang sudah dituduh, dan itu kode penerima. Keduanya tidak pernah memakai kata kode salinan yang sedang dinilai. Untuk salinan tak bersalah j yang belum dituduh, himpunan salinan yang sudah dituduh sama dengan hasil prosedur yang sama tanpa salinan j, jadi tidak bergantung pada kode j. Batas Chernoff tahap itu lalu berlaku persis seperti pada tahap 1. Peluang j dituduh pada tahap mana pun paling besar jumlah eps1 semua tahap, dan jumlah itu sama dengan jatah pelacakan dibagi n_max. Bukti ini tidak mengandaikan salinan yang sudah dituduh benar anggota koalisi.

**Anggaran.** Kebijakan `bertahap-v1` memberi tahap 1 90 % jatah pelacakan. Tahap 2, 3, dan 4 membagi 10 % sisanya dengan perbandingan 1 : 1/4 : 1/9, yaitu 7,3 %, 1,8 %, dan 0,8 % jatah pelacakan. Kebijakan dan eps setiap tahap ditulis di entri `trace` registri bersama nomor pelacakan, sebelum bukti dibaca. Pelacakan lewat `--doc` dan halaman Lacak selalu bertahap. Entri `trace` lama tanpa kolom ini tetap lulus verifikasi dan diulang dengan satu tahap. Di mode lepas, `--bertahap` mengulang pelacakan bertahap seperti tercatat di berita acara; tanpa itu mode lepas tetap satu tahap. Peluang tuduhan salah per salinan dibagi jatah tahap yang menuduhnya.

**Harga untuk tahap 1.** Ambang tahap 1 naik sekitar 0,3 %: untuk N = 20 dan c = 3, dari 345,4 menjadi 346,5 pada pelacakan pertama. Batas terbukti peluang koalisi lolos naik sekitar 1,4 kali (9,1 x 10^-23 menjadi 1,3 x 10^-22). Pada simulasi di bawah, harga ini tidak terlihat untuk koalisi paling banyak c. Untuk 6 sampai 8 orang, tempat tahap 1 hanya kadang berhasil, peluang menangkap minimal satu anggota turun paling banyak 2 poin persentase.

**Tampilan.** Putusan tetap putusan tahap 1, dan tahap lanjutan hanya berjalan setelah tahap 1 menyebut nama. Hasil, CLI, dan berita acara menulis nama tahap lanjutan bersama dasarnya, misalnya "tahap 2: dituduh berdasarkan salinan yang sudah dituduh #3, #7", dengan skor tahap, ambang tahap, dan peluang tuduhan salahnya sendiri. Halaman Lacak di web belum menampilkan tahap lanjutan; berita acara yang diunduh dari halaman itu sudah memuatnya.

**Angka.** `research/bertahap/ukur.py`; grid, benih, dan kebijakan ditetapkan sebelum simulasi dijalankan, angka mentah di `research/bertahap/hasil/`. Kode c = 3, eps = 10^-6 sebagai jatah satu pelacakan, pembacaan penuh tanpa derau, 1.000 percobaan per strategi. Rentang mencakup 7 strategi termasuk terburuk; strategi hapus dibahas di bawah.

| N = 100, koalisi | Anggota tertangkap, satu tahap | Bertahap | Semua tertangkap, satu tahap | Bertahap | Minimal 1 tertangkap, satu tahap / bertahap |
|---|---|---|---|---|---|
| 4 | 99,7 sampai 100 % | 99,8 sampai 100 % | 98,9 sampai 99,9 % | 99,2 sampai 100 % | 100 / 100 % |
| 5 | 85 sampai 86 % | 87 sampai 100 % | 44 sampai 47 % | 48 sampai 100 % | 100 / 100 % |
| 6 | 39 sampai 44 % | 70 sampai 96 % | 0,2 sampai 1,4 % | 22 sampai 96 % | 94 sampai 98 / 94 sampai 98 % |
| 7 | 12 sampai 14 % | 29,5 sampai 56 % | 0 % | 0,9 sampai 55 % | 59 sampai 65 / 58 sampai 64 % |
| 8 | 3,3 sampai 3,7 % | 6 sampai 19 % | 0 % | 0 sampai 14 % | 24 sampai 26 / 22 sampai 25 % |

Untuk N = 20 angkanya serupa: anggota tertangkap 83 sampai 86 % menjadi 87 sampai 100 % (5 orang), 39 sampai 44 % menjadi 67 sampai 96 % (6 orang), 14 sampai 15 % menjadi 30 sampai 61 % (7 orang), dan 4 sampai 5 % menjadi 7 sampai 20 % (8 orang).

* **Batas bawah rentang** berasal dari strategi mayoritas (5 dan 6 orang) dan campur acak (7 dan 8 orang). Bit mayoritas hampir selalu dimiliki salinan yang sudah dituduh, jadi posisi tak terjelaskan jarang ada: untuk 5 orang anggota tertangkap hanya naik dari 86 menjadi 87 %. Strategi minoritas dan terburuk, yang paling menekan tahap 1, paling terbantu: untuk 6 orang dari sekitar 39 % menjadi sekitar 94 %.
* **Strategi hapus** tertangkap semua atau tidak sama sekali, karena posisi yang tersisa sama di semua salinan koalisi. Sampai 7 orang hasilnya 100 %; untuk 8 orang turun dari 92,7 menjadi 90,7 % (N = 100) karena ambang tahap 1 sedikit lebih tinggi.
* **Koalisi paling banyak c** (1, 2, dan 3 orang, N = 20 dan 100): semua anggota tertangkap pada semua percobaan, dengan dan tanpa tahap lanjutan. Dengan kanal berderau (5 % bit salah, 35 % terhapus, N = 100, 3 orang), anggota tertangkap 99,3 sampai 99,7 % menjadi 99,5 sampai 100 %, dan semua tertangkap 97,9 sampai 99,0 % menjadi 98,5 sampai 100 %.
* **Tuduhan salah.** Nol di semua tahap dalam 136.000 percobaan (17 sel, 8 strategi, 1.000 percobaan per strategi). Skor tertinggi penerima tak bersalah adalah 79 % dari ambang di tahap 1, 74 % di tahap 2, 66 % di tahap 3, dan 62 % di tahap 4. Pada target yang dapat diukur, skor penerima tak bersalah di tahap 2 sampai 4 melewati ambang tahapnya pada laju 1,1 x 10^-3 untuk target 10^-2 dan 9,3 x 10^-5 untuk target 10^-3, dari 3,28 juta skor. Keduanya di bawah batasnya.

## Aturan keluaran

Nama hanya muncul bersama skor, ambang, dan peluang tuduhan salahnya. Bila tidak ada salinan yang melewati ambang, keluarannya "tidak cukup bukti" dan tidak ada nama yang disebut. Nama dari tahap lanjutan pelacakan bertahap selalu muncul bersama salinan yang menjadi dasarnya.

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
  tardos/       params, code (SHAKE-256), accuse (skor simetris, ambang Chernoff), spending (jatah eps),
                staged (pelacakan bertahap), detection, attacks, simulate
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
  ketik.py      simulator pengetikan ulang dan OCR (untuk pengujian dan pengukuran)
  service.py    alur bersama CLI, web, dan demo
  cli.py        tapak issue | trace | simulate | verify | demo | ...
samples/        templat nota dinas dan surat telegram fiktif, PDF contoh, daftar penerima
scripts/        alat ukur dan eksperimen (scripts/cetak: pengukuran salinan cetak)
tests/          pytest (tanpa GPU, tanpa model LLM, tanpa jaringan)
research/ketik/ pengukuran kanal pilihan kata (kapasitas, galat baca, atribusi)
research/pindaian/ pengukuran induk hasil pindai (protokol, hasil, potongan gambar)
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
| sama, [pelacakan bertahap](#pelacakan-bertahap), 1.000 percobaan | 0 | 100 % | 48 sampai 100 % (mayoritas 48 %, 6 strategi lain dan hapus 100 %) |

Untuk kanal berderau di baris kedua, batas terbukti peluang koalisi paling banyak 3 orang lolos adalah 3,4 x 10^-5 (`tapak deteksi --n 100 --ber 0.05 --erasure 0.35`; [bit salah dan bobot lunak](#bit-salah-dan-bobot-lunak)).

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
* **Cakupan.** Pembacaan penuh dengan bit pasti, juga penghapusan di posisi tempat salinan koalisi berbeda (strategi hapus) dan penghapusan yang tidak bergantung pada kode (batasnya lalu dihitung dengan jumlah posisi yang terbaca). Bit salah dan bobot lunak tercakup dengan syarat pada kanal ([di bawah](#bit-salah-dan-bobot-lunak)). Penghapusan yang menyasar posisi tempat salinan koalisi sama hanya diukur ([batasan 12](keamanan.md#batasan)).
* **Strategi terburuk.** Strategi `worst-case` (terburuk) membocorkan bit yang membuat rata-rata skor koalisi per posisi paling kecil. Dengan sebaran bias TAPAK, rumus tertutupnya menunjukkan bahwa ini selalu bit minoritas. Faktor Chernoff justru terbesar untuk bit mayoritas pada parameter TAPAK, karena ekor bawah skornya lebih berat. Keduanya ikut dalam simulasi, dan batasnya berlaku untuk keduanya.

| c | batas lolos terbukti, K = 2 pi^2 (N = 20 / 100) | K untuk batas 10^-3 (N = 20 / 100) | K untuk batas 10^-6 (N = 20 / 100) |
|---|---|---|---|
| 2 | 5 x 10^-17 / 2 x 10^-18 | 10,9 / 10,7 | 13,3 / 12,9 |
| 3 | 2 x 10^-23 / 1 x 10^-25 | 9,7 / 9,5 | 11,7 / 11,4 |
| 4 | 5 x 10^-31 / 6 x 10^-34 | 9,0 / 8,8 | 10,6 / 10,4 |
| 5 | 2 x 10^-38 / 4 x 10^-42 | 8,5 / 8,4 | 9,9 / 9,7 |

Batas ini mencakup setiap koalisi berukuran paling banyak c dan memakai ambang pembacaan penuh untuk seluruh eps. Pelacakan yang tercatat memakai jatah eps yang lebih kecil, jadi ambangnya lebih tinggi dan batasnya naik pelan dengan nomor pelacakan: untuk N paling sedikit 20, paling besar 2,4 x 10^-16 pada pelacakan pertama, 5,3 x 10^-12 pada pelacakan ke-10, dan 1,7 x 10^-8 pada pelacakan ke-100, dengan ambang tahap 1 [pelacakan bertahap](#pelacakan-bertahap) (tanpa tahap: 2 x 10^-16, 4,3 x 10^-12, dan 1,4 x 10^-8; angka mentah di `research/bertahap/hasil/batas.jsonl`). Batas ini hanya untuk tahap 1; yang ditambahkan tahap lanjutan hanya diukur. Untuk N di bawah 20 batasnya juga sedikit lebih besar (4,5 x 10^-14 untuk c = 2 dan N = 1, seluruh eps). Jadi konstanta bawaan cukup dengan margin lebar.

Perbandingan dengan simulasi (`research/deteksi/ukur.py`; grid ditetapkan sebelum simulasi dijalankan, angka mentah di `research/deteksi/hasil/`): c = 2 sampai 5, N = 20 dan 100, 8 strategi, 1.000 percobaan per strategi. Pada panjang bawaan tidak ada koalisi yang lolos. Pada kode pendek yang sengaja dibuat lemah:

| Batas terbukti | 0,9 | 0,5 | 0,1 | 0,01 |
|---|---|---|---|---|
| Panjang kode (c = 3, N = 20) | 973 | 1070 | 1212 | 1353 |
| Laju lolos terukur tertinggi (semua c, N, dan strategi) | 14 % | 4,4 % | 0,6 % | 0,1 % |

Tidak ada laju terukur yang melampaui batasnya, dan tidak ada tuduhan salah. Batasnya longgar: laju terukur tertinggi 6 sampai 17 kali lebih kecil.

Strategi terburuk hanya terburuk untuk rata-rata skor per posisi, dan kedelapan strategi itu memilih bit dari satu posisi saja. Pemeriksaan ulang (`research/deteksi/penyeimbang.py`, c = 2 sampai 4, N = 20, 2.000 percobaan per sel) memakai koalisi yang melihat semua posisi dan memilih bit agar perkiraan skor anggotanya tetap sama rata. Koalisi ini lolos sampai 4 kali lebih sering daripada strategi terbaik di atas: paling tinggi 22 %, 6 %, dan 0,65 % pada batas 0,9, 0,5, dan 0,1. Itu tetap di bawah batasnya; batasnya 4 sampai 15 kali lebih besar. Batas terbukti berlaku untuk strategi seperti ini juga; simulasi hanya memeriksa contoh yang kami coba. Batas itu mengecil secara eksponensial terhadap m, jadi pada panjang bawaan pun sudah sangat kecil.

#### Bit salah dan bobot lunak

Dekoder tidak melihat kata bocoran y, tetapi bacaannya: bit yang mungkin terbalik dan bobot w_i = tanh(|LLR|/2). Bit yang terbalik membalik tanda skor koalisi di posisi itu, jadi rata-rata skor koalisi menyusut menjadi w_i (1 - 2 e_i) kali semula, dengan e_i peluang bit itu terbalik. Ambang Z(p, w) dibatasi seperti pada pembacaan penuh, dengan fungsi Chernoff berbobot yang memang dipakai TAPAK. Buktinya memerlukan dua syarat:

1. Derau kanal terjadi setelah koalisi memilih bitnya, dan tidak bergantung pada kode, pada pilihan koalisi, maupun pada bit yang dibocorkan. Kanal simetris memenuhinya: |LLR| dan benar-salahnya keputusan hanya bergantung pada derau.
2. Dengan bobot diketahui, bit yang terbalik saling bebas antarposisi, dengan laju e_i yang diketahui.

Syarat 1 menjamin bahwa, dengan bobot diketahui, kode masih tersebar seperti tanpa kanal, sehingga batas Chernoff tetap terpecah menjadi hasil kali per posisi. Syarat 2 membuat faktor setiap posisi menjadi rata-rata dua kemungkinan (terbalik atau tidak) di dalam maksimum atas bit bocor. Hasilnya batas peluang lolos bila bobot yang terbaca diketahui (`read_miss_bound`) dan bila setiap posisi, bebas dari posisi lain, mengambil bobot dan laju salahnya dari satu sebaran (`channel_miss_bound`, juga di `tapak deteksi`). Batas kedua juga mencakup strategi hapus, tetapi tidak berlaku untuk satu bacaan yang bobotnya bergerak bersama (foto yang baik atau buruk secara keseluruhan); untuk bacaan seperti itu batasnya dihitung dari bobotnya sendiri. Tanpa derau (w = 1, e = 0) hasilnya sama dengan batas pembacaan penuh. Bila syarat 1 gagal, misalnya bobot nol justru jatuh di posisi tempat salinan koalisi sama, sebaran kode di posisi yang terbaca berubah dan batasnya tidak berlaku (tabel terakhir di bawah). Dekoder foto TAPAK sendiri tidak memenuhi syarat 1 secara persis: kanal latar memakai vektor bias sebagai pilot untuk memperkirakan penguatannya per strata dan untuk memutuskan ada tidaknya pola, jadi bobotnya bergantung pada kode lewat beberapa angka bersama untuk satu halaman. Pengaruhnya per posisi kecil, tetapi tidak dimodelkan. Turunan lengkapnya ada di docstring `tapak/tardos/detection.py`.

Sebaran bobot dekoder diukur pada 40 foto layar dan tangkapan layar sintetis dari benchmark (`research/deteksi/llr_foto.py`, angka di `research/deteksi/hasil/llr_foto.json`). Dari posisi yang terbaca, 82 % berbobot di atas 0,95 dan 4 % terhapus. Di bobot menengah laju salahnya beberapa poin persentase di atas atau di bawah laju terkalibrasi (1 - w)/2, tetapi di bobot tertinggi dekoder terlalu yakin: bobot di atas 0,95 (rata-rata 0,998) salah 0,33 %, 2,8 kali perkiraan 0,12 %, dan bobot 0,9 sampai 0,95 salah 5,3 %, 1,5 kali perkiraannya. Karena itu batas dengan laju (1 - w)/2 tidak sah untuk foto ini, dan model "foto" di bawah memakai laju salah terukur per kelompok bobot. Laju itu juga berbeda per foto: jumlah bit salah tiap foto 0,5 sampai 4,3 kali perkiraan terkalibrasinya. Foto dengan lebih dari 100 bit salah terkalibrasi baik (0,85 sampai 1,14 kali), sedangkan foto bersih dan tangkapan layar yang hanya salah beberapa bit cenderung terlalu yakin.

Sebaran ini menggabungkan posisi dari 40 gambar, dan setiap gambar hanya memuat halaman 1 (sekitar 1.990 dari 2.987 posisi). Di dalam satu foto bobot tidak bebas antarposisi: foto baik atau buruk secara keseluruhan (jumlah w^2 per foto 86 sampai 1.986). Jadi kolom "bobot foto" di bawah adalah batas untuk pembacaan semua posisi dengan bobot seperti foto yang diundi bebas per posisi, bukan batas untuk satu foto. Batas satu foto dihitung dari bobotnya sendiri (`read_miss_bound`; `research/deteksi/baca_foto.py`, angka di `research/deteksi/hasil/baca_foto.jsonl`). Dengan laju salah terukur gabungan per kelompok bobot, untuk koalisi paling banyak 3 orang batasnya paling kecil 6 x 10^-9 (tangkapan layar) dan mediannya 2 x 10^-8. Pada 9 dari 40 gambar batasnya di atas 10^-6, dan 5 gambar tidak memberi jaminan (0,85 sampai 1). Sebaran gabungan memberi 1 x 10^-17 untuk kode yang sama.

Batas pada panjang bawaan (K = 2 pi^2, N = 20, seluruh eps, koalisi paling banyak c):

| c | bit pasti | bit salah 2 % | 5 % | 10 % | 20 % | bobot foto, laju terukur | K untuk batas 10^-6: bit salah 5 % / 10 % / 20 % / bobot foto |
|---|---|---|---|---|---|---|---|
| 2 | 5 x 10^-17 | 2 x 10^-14 | 7 x 10^-11 | 4 x 10^-6 | 0,40 | 1 x 10^-12 | 16,3 / 20,4 / 35,8 / 15,2 |
| 3 | 2 x 10^-23 | 5 x 10^-20 | 3 x 10^-15 | 8 x 10^-9 | 0,21 | 1 x 10^-17 | 14,3 / 17,9 / 31,2 / 13,4 |
| 4 | 5 x 10^-31 | 2 x 10^-26 | 3 x 10^-20 | 1 x 10^-11 | 0,10 | 2 x 10^-23 | 13,0 / 16,3 / 28,6 / 12,2 |
| 5 | 2 x 10^-38 | 9 x 10^-33 | 5 x 10^-25 | 2 x 10^-14 | 0,05 | 4 x 10^-29 | 12,2 / 15,3 / 26,9 / 11,4 |

Bit pasti memerlukan K 13,3 / 11,7 / 10,6 / 9,9 untuk 10^-6 (tabel sebelumnya). Dengan 10 % bit salah, K bawaan masih cukup untuk 10^-6 kecuali pada c = 2 (perlu 20,4). Dengan 20 % bit salah, kode bawaan tidak memberi jaminan yang berarti (batas 0,05 sampai 0,40). Laju terkalibrasi (1 - w)/2 memberi batas sedikit lebih kecil daripada laju terukur, tetapi tidak sah untuk foto. Untuk N = 100 batasnya sedikit lebih kecil (angka mentah di `research/deteksi/hasil/batas_kanal.jsonl`).

Perbandingan dengan simulasi (`research/deteksi/kanal.py`, bagian `derau`; grid ditetapkan dan dicatat di git sebelum simulasi dijalankan): N = 20, c = 2 sampai 5, 8 strategi, 1.000 percobaan per sel. Panjang kode setiap sel adalah kode terpendek yang batasnya 0,5 atau 0,1 untuk model baca itu, dihitung dari batas saja. Bit salah dan bobot diundi per posisi setelah koalisi memilih bitnya, dan ambang Z(p, w) dihitung dari bobot yang terbaca, seperti di dekoder. "Bobot foto" berarti bobot diundi dari sebaran terukur di atas; bit salahnya diundi bebas dari bobot, kecuali di dua baris terakhir.

| Model baca | K untuk batas 0,5 (c = 2 sampai 5) | Laju lolos tertinggi | K untuk batas 0,1 | Laju lolos tertinggi |
|---|---|---|---|---|
| bobot 1, tanpa bit salah | 6,5 sampai 7,7 | 3,9 % | 7,2 sampai 8,8 | 0,4 % |
| bobot 1, bit salah 2 % | 7,0 sampai 8,2 | 4,6 % | 7,8 sampai 9,5 | 0,5 % |
| bobot 1, bit salah 5 % | 7,9 sampai 9,2 | 4,1 % | 8,8 sampai 10,7 | 0,4 % |
| bobot 1, bit salah 10 % | 9,8 sampai 11,4 | 4,9 % | 11,0 sampai 13,2 | 0,7 % |
| bobot 1, bit salah 20 % | 16,9 sampai 19,2 | 5,9 % | 19,0 sampai 22,6 | 0,5 % |
| bobot foto, tanpa bit salah | 7,0 sampai 8,3 | 4,6 % | 7,7 sampai 9,5 | 0,8 % |
| bobot foto, bit salah 2 % | 7,5 sampai 8,9 | 4,4 % | 8,4 sampai 10,2 | 0,5 % |
| bobot foto, bit salah 5 % | 8,4 sampai 9,9 | 5,3 % | 9,4 sampai 11,5 | 0,5 % |
| bobot foto, bit salah 10 % | 10,5 sampai 12,3 | 4,9 % | 11,8 sampai 14,2 | 0,5 % |
| bobot foto, bit salah 20 % | 18,1 sampai 20,6 | 4,9 % | 20,4 sampai 24,3 | 0,6 % |
| bobot foto, laju (1 - w)/2 | 7,3 sampai 8,7 | 4,5 % | 8,2 sampai 10,0 | 0,4 % |
| bobot foto, laju terukur (model foto) | 7,4 sampai 8,7 | 4,8 % | 8,2 sampai 10,1 | 0,5 % |

Di 96 sel (768.000 serangan) tidak ada laju lolos yang melampaui batasnya. Laju terukur tertinggi 5,9 % untuk batas 0,5 dan 0,8 % untuk batas 0,1, jadi batasnya 8 sampai 12 kali di atas laju terukur tertinggi. Batasnya makin longgar untuk koalisi besar: 8 sampai 12 kali untuk c = 2, 20 sampai 23 kali untuk c = 3, 33 sampai 45 kali untuk c = 4, dan 71 sampai 100 kali untuk c = 5 (di 9 sel dengan batas 0,1 tidak ada koalisi yang lolos). Strategi yang paling sering lolos berbeda dari sel ke sel. Harga bit salah terlihat di kolom K: dengan 20 % bit salah, kode perlu sekitar 2,5 kali lebih panjang untuk batas yang sama, mendekati faktor 1/(1 - 2e)^2 = 2,8.

Penghapusan yang menyasar posisi tempat salinan koalisi sama (`kanal.py`, bagian `sasaran`; panjang bawaan, N = 20, pembacaan tanpa bit salah, 8 strategi, 1.000 percobaan per sel). Koalisi melihat di mana salinannya sama, dan asumsi penandaan saja tidak melarang menghapus tanda di sana. Setiap posisi itu dihapus dengan peluang r, di atas strategi biasa di posisi yang berbeda:

| r | 0 | 50 % | 80 % | 90 % sampai 100 % |
|---|---|---|---|---|
| Laju lolos tertinggi, c = 2 / 3 / 4 / 5 | 0 / 0 / 0 / 0 | 1,6 / 0,5 / 0,3 / 0 % | 99,9 / 96 / 96 / 97 % | 99,4 sampai 100 % untuk setiap strategi |
| Batas untuk penghapusan acak yang menyisakan jumlah posisi sama (tidak berlaku di sini) | 5 x 10^-17 sampai 2 x 10^-38 | 1 x 10^-5 sampai 2 x 10^-21 | 0,29 sampai 1 x 10^-12 | 1 sampai 4 x 10^-10 |

Posisi tempat salinan koalisi sama membawa hampir seluruh skor koalisi. Bila separuhnya masih terbaca, deteksi tetap hampir pasti; bila sebagian besar terhapus, koalisi lolos, jauh di atas batas yang berlaku untuk penghapusan acak. Penghapusan seperti ini menuntut koalisi menghapus tanda di bagian yang salinannya sama (misalnya meratakan pola latar di sana) tanpa menyentuh bagian yang berbeda. Batas terbukti tidak mencakupnya.

## Hasil lain

| Pengujian | Hasil |
|---|---|
| Kumpulan foto sintetis (`make photos` lalu `make bench`): 32 foto layar bersudut 0 sampai 30 derajat dan 8 tangkapan layar dari 4 salinan (halaman 1), dikompresi JPEG dua kali seperti WhatsApp. Satu penerbitan 20 salinan; rahasia kode dan id salinan dari benih riset 2026, benih foto 2026, jadi hasilnya terulang persis ([operasi](operasi.md#benchmark-foto)) | 39 dari 40 benar, 1 "tidak cukup bukti" (foto dengan 95 % kertas jenuh putih), 0 tuduhan salah. Dua foto dengan 88 dan 90 % kertas jenuh gagal dengan dekoder latar lama dan kini benar ([batasan 4](keamanan.md#batasan)) |
| Foto kertas cetak (`make photos-cetak` lalu `make bench`, dilaporkan terpisah): halaman 1 dan 2 dari 4 salinan yang sama, dicetak printer laser simulasi dengan profil latar bawaan, 16 foto (10 dan 30 derajat, 1600 px) dan 8 pasangan dua halaman | satu halaman 0 dari 16 benar, dua halaman 8 dari 8 dengan skor hanya 1,02 sampai 1,19 kali ambang, 0 tuduhan salah |
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

Nilainya dari literatur dan perkiraan orde besaran, bukan dari printer yang diukur. Kalibrasinya (`scripts/cetak/calibrate.py`): abu-abu 50 % tercetak 11,7 poin persentase lebih gelap, dan tingkat 245 sampai 249 tercetak sebagai titik terkecil (dL* -1,9). Yang tidak dimodelkan: koreksi nada driver, mode hemat toner, printer warna, mesin fotokopi dan pemindai, serta pemrosesan gambar di kamera ponsel.

### Templat induk tepat

Dekoder geser mencocokkan setiap kelompok kata pada foto dengan templat dari dokumen induk. MuPDF menggambar glif kecil dari cache bitmap pada piksel utuh, jadi templat lama (render 4 kali lebih rapat lalu dirata-rata) menggeser kelompok kata sampai puluhan mikrometer, sama untuk setiap salinan dan foto. Templat tepat dirender pada 3.200 dpi atau lebih, saat glif digambar sebagai kurva tanpa pembulatan, per pita, lalu dirata-rata turun. Render tepat induk pada 4.800 dpi bergeser kurang dari 0,3 um terhadap templat ini untuk setiap kelompok. Hanya pita yang memuat baris teks yang dibaca dekoder geser yang dirender, dipotong ke kolom baris itu; pitanya sama dengan render seluruh halaman, jadi nilai pikselnya identik. Rendernya memerlukan sekitar 5 sampai 7 detik CPU per halaman penuh teks di mesin uji (render seluruh halaman: 7 sampai 12 detik), sekali untuk setiap halaman dan resolusi analisis per proses. `tapak web` menyimpan templat di memori (sampai 320 MB); setiap perintah `tapak trace` merendernya lagi.

Pada foto kertas cetak, templat tepat hampir tidak mengubah hasil (tabel di bawah, dibandingkan dengan templat lama pada foto yang sama). Pada benchmark README putusannya identik untuk ke-64 pelacakan; hanya batas peluang tuduhan salahnya yang bergeser.

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
| Ambang Z ditetapkan sebelum analisis | aturan ambang ditetapkan saat penerbitan; nilai Z dihitung setelah dekode dari posisi yang benar-benar terbaca, sebelum skor dihitung | kanal yang rusak menghapus posisi; ambang tetap untuk pembacaan penuh akan terlalu ketat untuk bukti parsial. Aturannya tetap dan tidak pernah melihat kode salinan yang dinilai (tahap 1 tidak melihat kode penerima mana pun; tahap lanjutan pelacakan bertahap hanya melihat kode salinan yang sudah dituduh), sehingga tidak dapat disesuaikan setelah melihat hasil |
| Konstanta "Skoric 2006, 2 pi^2" | dipertahankan sebagai bawaan, atribusi dikoreksi | 2 pi^2 berasal dari Skoric, Vladimirova, Celik, dan Talstra untuk skor asimetris (pendekatan Gauss). Dengan skor simetris konstanta asimtotiknya pi^2/2, jadi ada margin sekitar 4 kali. Untuk c kecil kecukupannya kini dihitung langsung: batas terbukti peluang koalisi lolos paling besar 5 x 10^-17 untuk c = 2 sampai 5 (eps = 10^-6, N paling sedikit 20, pembacaan penuh; [batas deteksi terbukti](#batas-deteksi-terbukti)). Jaminan tuduhan salah tidak bergantung pada K karena berasal dari ambang Chernoff |

## Referensi

1. G. Tardos. Optimal probabilistic fingerprint codes. Proc. 35th ACM STOC, 2003, hlm. 116-125. Versi jurnal: J. ACM 55(2), 2008.
2. B. Skoric, T. U. Vladimirova, M. Celik, J. C. Talstra. Tardos fingerprinting is better than we thought. IEEE Trans. Inf. Theory 54(8):3663-3676, 2008. arXiv:cs/0607131.
3. B. Skoric, S. Katzenbeisser, M. U. Celik. Symmetric Tardos fingerprinting codes for arbitrary alphabet sizes. Des. Codes Cryptogr. 46(2):137-166, 2008. IACR ePrint 2007/041.
4. T. Laarhoven, B. de Weger. Optimal symmetric Tardos traitor tracing schemes. Des. Codes Cryptogr. 71(1):83-103, 2014. arXiv:1107.3441.
5. J. T. Brassil, S. Low, N. F. Maxemchuk. Copyright protection for the electronic distribution of text documents. Proc. IEEE 87(7), 1999 (pergeseran baris dan kata).
6. M. Tancik, B. Mildenhall, R. Ng. StegaStamp: Invisible hyperlinks in physical photographs. CVPR 2020.
